"""Servidor MCP da Central de Salas (Streamable HTTP, spec 2026-07-28).

Expõe três tools e um resource. `reservar_sala` usa o ciclo MRTR do SDK: quando a sala
está ocupada, o resolver `escolha_de_sala` devolve uma elicitation em form mode e o SDK
responde `input_required` com um `requestState` selado (AES-256-GCM, chave de
REQUEST_STATE_SECRET); o cliente retorna com `inputResponses` + `requestState` e a tool
conclui. Cada request recebido é registrado no stderr com método, id e traceparent.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import AcceptedElicitation, Elicit, ElicitationResult, Resolve
from mcp.server.request_state import RequestStateSecurity
from pydantic import BaseModel, Field, create_model

import dominio

TTL_MINIMO, TTL_MAXIMO = 300, 1800
TAMANHO_MINIMO_SEGREDO = 32


# --------------------------------------------------------------------------- modelos de saída


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


class ReservaOut(BaseModel):
    reserva: str | None = None
    reservado: bool = True
    sala: str | None = None
    inicio: str | None = None
    fim: str | None = None
    responsavel: str | None = None
    politica: str | None = None
    motivo: str | None = None


# --------------------------------------------------------------------------- tools e resource


def listar_salas() -> ListaDeSalas:
    """Lista todas as salas com capacidade e recursos."""
    return ListaDeSalas(salas=[SalaOut(**s) for s in dominio.SALAS])


def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
    """Diz se uma sala esta livre no intervalo, e quais reservas conflitam."""
    ini, end = dominio.validar_pedido(sala, inicio, fim)
    achados = dominio.conflitos(sala, ini, end)
    return Disponibilidade(
        sala=sala,
        livre=not achados,
        conflitos=[ConflitoOut(id=r["id"], inicio=r["inicio"], fim=r["fim"], responsavel=r["responsavel"]) for r in achados],
    )


MENSAGEM_ESCOLHA = "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."


def escolha_de_sala(sala: str, inicio: str, fim: str, responsavel: str) -> Elicit[Any] | None:
    """Resolver MRTR: sem conflito devolve None; com conflito pede a escolha entre as alternativas.

    Roda antes do corpo de `reservar_sala` (e de novo no retry). O SDK transforma o `Elicit`
    em `input_required` + `requestState`; no retry, injeta a resposta do cliente se a
    pergunta renderizada for a mesma que foi feita.
    """
    ini, end = dominio.validar_pedido(sala, inicio, fim)
    dominio.validar_responsavel(responsavel)
    if not dominio.conflitos(sala, ini, end):
        return None
    alternativas = dominio.alternativas(sala, ini, end)
    if not alternativas:
        raise ToolError(dominio.ERRO_SEM_ALTERNATIVA)
    # Schema plano: uma propriedade `sala` restrita às alternativas (enum; const com uma só).
    Escolha = create_model(
        "Escolha", sala=(Literal[tuple(alternativas)], Field(description="Sala alternativa escolhida"))
    )
    return Elicit(MENSAGEM_ESCOLHA, Escolha)


def reservar_sala(
    sala: str,
    inicio: str,
    fim: str,
    responsavel: str,
    escolha: Annotated[ElicitationResult[Any], Resolve(escolha_de_sala)],
) -> ReservaOut:
    """Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar."""
    if not isinstance(escolha, AcceptedElicitation):
        return ReservaOut(reservado=False, motivo="recusado")
    destino = sala if escolha.data is None else escolha.data.sala
    nome = dominio.validar_responsavel(responsavel)
    reserva = dominio.reservar_se_livre(destino, inicio, fim, nome)
    return ReservaOut(
        reserva=reserva["id"],
        sala=destino,
        inicio=inicio,
        fim=fim,
        responsavel=nome,
        politica=dominio.POLITICA_VERSAO,
    )


def politica_de_uso() -> str:
    return dominio.POLITICA_TEXTO


# --------------------------------------------------------------------------- log no stderr


TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def _campo_de_log(valor: Any, limite: int = 128) -> str:
    """Valores vindos do cliente entram no log sem quebras de linha e com tamanho limitado."""
    texto = str(valor).encode("unicode_escape").decode("ascii")
    return texto if len(texto) <= limite else texto[:limite] + "..."


async def registrar_request(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
    meta = ctx.meta or {}
    params = ctx.params or {}
    traceparent = meta.get("traceparent")
    if not isinstance(traceparent, str) or not TRACEPARENT_RE.match(traceparent):
        traceparent = "-"
    nome = _campo_de_log(params.get("name") or params.get("uri") or "-")
    retry = " retry=sim" if params.get("requestState") is not None else ""
    print(
        f"[mcp] method={ctx.method} id={_campo_de_log(ctx.request_id)} traceparent={traceparent} name={nome}{retry}",
        file=sys.stderr,
        flush=True,
    )
    return await call_next(ctx)


# --------------------------------------------------------------------------- construção


def validar_seguranca(segredo: str, ttl: float) -> None:
    if len(segredo.encode()) < TAMANHO_MINIMO_SEGREDO:
        raise ValueError(f"REQUEST_STATE_SECRET precisa ter pelo menos {TAMANHO_MINIMO_SEGREDO} bytes")
    if not TTL_MINIMO <= ttl <= TTL_MAXIMO:
        raise ValueError(f"REQUEST_STATE_TTL precisa ficar entre {TTL_MINIMO} e {TTL_MAXIMO} segundos")


def criar_servidor(segredo: str, ttl: float = 600.0) -> MCPServer:
    validar_seguranca(segredo, ttl)
    mcp = MCPServer(
        name="central-de-salas",
        version="1.0.0",
        request_state_security=RequestStateSecurity(keys=[segredo], ttl=ttl),
        middleware=[registrar_request],
    )
    mcp.tool()(listar_salas)
    mcp.tool()(consultar_disponibilidade)
    mcp.tool()(reservar_sala)
    mcp.resource("politica://uso", mime_type="text/markdown")(politica_de_uso)
    return mcp


# --------------------------------------------------------------------------- configuração


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    segredo: str
    ttl: float


def _env(nome: str, padrao: str | None = None) -> str | None:
    valor = os.environ.get(nome, "")
    return valor.strip() or padrao


def carregar_config() -> Config:
    segredo = _env("REQUEST_STATE_SECRET")
    if segredo is None:
        raise SystemExit(
            "REQUEST_STATE_SECRET nao definida. Gere com: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )
    try:
        port = int(_env("MCP_PORT", "7301"))
        ttl = float(_env("REQUEST_STATE_TTL", "600"))
    except ValueError:
        raise SystemExit("MCP_PORT e REQUEST_STATE_TTL precisam ser numericos") from None
    if not 1 <= port <= 65535:
        raise SystemExit("MCP_PORT precisa ficar entre 1 e 65535")
    try:
        validar_seguranca(segredo, ttl)
    except ValueError as erro:
        raise SystemExit(str(erro)) from None
    return Config(host=_env("MCP_HOST", "127.0.0.1"), port=port, segredo=segredo, ttl=ttl)


def main() -> None:
    config = carregar_config()
    mcp = criar_servidor(config.segredo, config.ttl)
    print(f"[mcp] central-de-salas em http://{config.host}:{config.port}/mcp (ttl do requestState: {config.ttl:.0f}s)", file=sys.stderr, flush=True)
    mcp.run(
        "streamable-http",
        host=config.host,
        port=config.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
