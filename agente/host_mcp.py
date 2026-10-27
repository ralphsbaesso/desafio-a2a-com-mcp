"""O agente como host MCP: um cliente do SDK que fala com o servidor por HTTP.

Regras deste módulo (spec 03):
- descobre as tools por `tools/list` antes do primeiro `tools/call` do processo;
- lê o resource `politica://uso` e guarda a versão da primeira linha;
- devolve o `input_required` **cru**: nunca responde uma elicitation por conta própria;
- propaga o trace-id do cliente A2A em `_meta.traceparent`, com span-id novo por request.

Desenho da conexão: o transporte 2026-07-28 não tem sessão (cada request é um POST
independente), então o que vive durante o processo é o **pool HTTP** (`httpx2.AsyncClient`).
Cada operação abre um `mcp.Client` leve sobre esse pool, na própria task que a executa.
Isso evita dois problemas do `Client` de longa duração do SDK: uma falha de conexão
cancela o task group dele e o deixa inutilizável, e `__aenter__`/`__aexit__` precisam
rodar na mesma task. Os ids JSON-RPC continuam crescentes por processo (ver `_sessao`),
para que o retry nunca repita o id do request inicial.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    Implementation,
    InputRequiredResult,
    InputResponses,
)
from pydantic import TypeAdapter

if TYPE_CHECKING:  # o objeto in-process só existe nos testes; em produção o alvo é a URL
    from mcp.server.mcpserver import MCPServer

TRACEPARENT_RE = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
URI_POLITICA = "politica://uso"
TOOL_RESERVA = "reservar_sala"
CLIENT_INFO = Implementation(name="agente-central-de-salas", version="1.0.0")
TIMEOUT_PADRAO = 30.0
# Cada operação do host recebe uma janela de ids JSON-RPC reservada atomicamente no
# processo; nenhuma operação faz mais que 2 requests, então ids nunca colidem nem regridem.
JANELA_DE_IDS = 4
# O retorno cru de tools/call: completo ou pedindo input. Sem validação de outputSchema no
# cliente (ela faria um tools/list extra por chamada) e sem o driver automático de MRTR.
RESULTADO_RESERVA = TypeAdapter(CallToolResult | InputRequiredResult)


def traceparent_valido(valor: str | None) -> str | None:
    """Normaliza (minúsculas, sem espaços) um traceparent W3C válido; qualquer outra coisa vira `None`.

    Além do formato, a W3C proíbe a versão `ff` e trace-id ou span-id todos zero.
    """
    if not isinstance(valor, str):
        return None
    texto = valor.strip().lower()
    m = TRACEPARENT_RE.match(texto)
    if not m or m.group(1) == "ff" or set(m.group(2)) == {"0"} or set(m.group(3)) == {"0"}:
        return None
    return texto


def novo_span(traceparent: str) -> str | None:
    """Mesmo trace-id e flags, span-id novo: cada request MCP é um span filho. Inválido vira `None`."""
    valido = traceparent_valido(traceparent)
    if valido is None:
        return None
    versao, trace_id, _span, flags = valido.split("-")
    return f"{versao}-{trace_id}-{secrets.token_hex(8)}-{flags}"


def versao_da_politica(texto: str) -> str:
    primeira = texto.splitlines()[0] if texto else ""
    chave, _, valor = primeira.partition(":")
    if chave.strip() != "versao" or not valor.strip():
        raise ValueError("o resource politica://uso nao comeca com 'versao: <valor>'")
    return valor.strip()


async def _elicitation_nunca_chamada(*args: Any, **kwargs: Any) -> Any:
    # Existe só para o SDK declarar a capability `elicitation.form` no `_meta`.
    # No transporte 2026-07-28 o servidor não inicia requests, e o agente usa
    # `allow_input_required=True`, então este callback nunca executa.
    raise RuntimeError("o agente nao responde elicitation sozinho: o input_required deve voltar ao cliente A2A")


def _timeout_valido(valor: Any) -> float:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return TIMEOUT_PADRAO
    try:
        segundos = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"MCP_TIMEOUT invalido: {valor!r} (use segundos, ex.: 30)") from None
    if not (0 < segundos < float("inf")):
        raise ValueError(f"MCP_TIMEOUT invalido: {valor!r} (precisa ser um numero positivo de segundos)")
    return segundos


def _causa_unica(grupo: BaseExceptionGroup[Any]) -> BaseException:
    """Desce por grupos de uma única exceção até a causa real; grupos múltiplos voltam como estão."""
    atual: BaseException = grupo
    while isinstance(atual, BaseExceptionGroup) and len(atual.exceptions) == 1:
        atual = atual.exceptions[0]
    return atual


class HostMCP:
    """Host MCP do agente: um pool HTTP por processo, um `Client` leve por operação."""

    def __init__(self, alvo: str | MCPServer, timeout: float | None = None) -> None:
        self._alvo = alvo
        self._timeout = _timeout_valido(timeout if timeout is not None else os.environ.get("MCP_TIMEOUT"))
        self._http: httpx2.AsyncClient | None = None
        self._descoberta = asyncio.Lock()
        self._proximo_id = 0
        self.tools: list[str] = []
        self.versao_politica: str | None = None

    async def abrir(self) -> None:
        """Cria o pool HTTP (idempotente). Nenhum request é feito aqui."""
        if self._http is None and isinstance(self._alvo, str):
            self._http = httpx2.AsyncClient(timeout=httpx2.Timeout(self._timeout, connect=min(10.0, self._timeout)))

    async def fechar(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @asynccontextmanager
    async def _sessao(self) -> AsyncIterator[Client]:
        """Um `Client` para a operação corrente, na task corrente, com ids crescentes por processo.

        Erros do transporte saem do `Client` embrulhados em `ExceptionGroup` (task group do
        SDK); quando o grupo tem uma única causa, ela é relançada direto.
        """
        if isinstance(self._alvo, str):
            if self._http is None:
                raise RuntimeError("HostMCP.abrir() precisa ser chamado antes")
            alvo: Any = streamable_http_client(self._alvo, http_client=self._http)
        else:
            alvo = self._alvo
        try:
            async with Client(
                alvo,
                mode="2026-07-28",
                client_info=CLIENT_INFO,
                elicitation_callback=_elicitation_nunca_chamada,
                # Sem timeout um servidor mudo prenderia o lock de descoberta e travaria o agente.
                read_timeout_seconds=self._timeout,
            ) as client:
                # Reserva atômica (sem await entre ler e avançar) de uma janela de ids para esta operação.
                base, self._proximo_id = self._proximo_id, self._proximo_id + JANELA_DE_IDS
                contadores = self._contadores_de_id(client)
                for contador in contadores:
                    contador._next_id = base  # noqa: SLF001
                try:
                    yield client
                finally:
                    usado = max(c._next_id for c in contadores)  # noqa: SLF001
                    if usado > base + JANELA_DE_IDS:
                        # Estouro da janela: avança o contador global para não colidir e avisa alto.
                        self._proximo_id = max(self._proximo_id, usado)
                        print(f"[agente] aviso: operacao MCP usou {usado - base} ids, acima da janela de {JANELA_DE_IDS}", file=sys.stderr, flush=True)
        except BaseExceptionGroup as grupo:
            raise _causa_unica(grupo) from None

    @staticmethod
    def _contadores_de_id(client: Client) -> list[Any]:
        """Os objetos do SDK (pinado em 2.3.0) que cunham o id JSON-RPC: o dispatcher e, in-process, o par dele."""
        dispatcher = client.session._dispatcher  # noqa: SLF001
        candidatos = [dispatcher, getattr(dispatcher, "_peer", None)]
        contadores = [c for c in candidatos if c is not None and hasattr(c, "_next_id")]
        if not contadores:
            raise RuntimeError("o dispatcher do SDK mudou: nao encontrei o contador de ids JSON-RPC")
        return contadores

    @staticmethod
    def _meta(traceparent: str | None) -> dict[str, Any] | None:
        """`_meta` extra do request: só o traceparent (as chaves reservadas o SDK carimba)."""
        filho = novo_span(traceparent) if traceparent else None
        return {"traceparent": filho} if filho else None

    async def preparar(self, traceparent: str | None = None) -> None:
        """Descoberta em runtime (uma vez por processo): `tools/list` e leitura da política."""
        async with self._descoberta:
            if self.versao_politica is not None:
                return
            async with self._sessao() as client:
                listagem = await client.list_tools(meta=self._meta(traceparent), cache_mode="bypass")
                nomes = [t.name for t in listagem.tools]
                if TOOL_RESERVA not in nomes:
                    raise RuntimeError(f"o servidor MCP nao expoe a tool {TOOL_RESERVA!r}; encontrei {nomes}")
                recurso = await client.read_resource(URI_POLITICA, meta=self._meta(traceparent))
            texto = getattr(recurso.contents[0], "text", None) if recurso.contents else None
            if not isinstance(texto, str):
                raise RuntimeError(f"o resource {URI_POLITICA} nao devolveu conteudo de texto")
            self.tools = nomes
            self.versao_politica = versao_da_politica(texto)

    async def reservar(
        self,
        argumentos: dict[str, Any],
        traceparent: str | None = None,
        *,
        input_responses: InputResponses | None = None,
        request_state: str | None = None,
    ) -> CallToolResult | InputRequiredResult:
        """`tools/call reservar_sala` cru. `request_state` é ecoado byte a byte, nunca lido.

        O id JSON-RPC vem da janela reservada para esta operação, então o retry nunca
        reaproveita o id do request inicial, mesmo com operações concorrentes.
        """
        await self.preparar(traceparent)
        pedido = CallToolRequest(
            params=CallToolRequestParams(
                name=TOOL_RESERVA,
                arguments=argumentos,
                input_responses=input_responses,
                request_state=request_state,
                _meta=self._meta(traceparent),
            )
        )
        async with self._sessao() as client:
            return await client.session.send_request(pedido, RESULTADO_RESERVA)
