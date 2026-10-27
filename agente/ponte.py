"""A ponte: o resultado cru do servidor MCP vira estado de Task A2A (spec 05).

É AQUI que os dois mecanismos de estado se encontram:

- `pausar()`: o `input_required` do MCP vira `TASK_STATE_INPUT_REQUIRED`; a chave do
  `inputRequests`, o `requestState` (opaco, nunca lido) e as alternativas ficam guardados
  na `Pendencia` da Task, que nunca vai para o wire A2A.
- `retomar()`: a resposta `escolha=<valor>` do cliente A2A vira `inputResponses`, e o
  `requestState` volta ao servidor no retry de `tools/call` (id JSON-RPC novo, mesmos
  argumentos do pedido original).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

import httpx2
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult

import tarefas
from host_mcp import HostMCP
from tarefas import Tarefa

ORDEM_DO_ARTIFACT = ("reserva", "sala", "inicio", "fim", "responsavel", "politica")
ESCOLHA_RE = re.compile(r"^escolha=(\S+)$")
ESCOLHA_VALIDA_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")  # ids de sala: sem espaco, sem virgula (a linha usa ", ")
RECUSAR = "recusar"


def _texto(resultado: CallToolResult) -> str:
    partes = [getattr(p, "text", "") for p in resultado.content or []]
    return " ".join(t for t in partes if t) or "a tool nao devolveu texto"


def concluir_com_reserva(tarefa: Tarefa, dados: dict[str, Any], versao_politica: str) -> None:
    """COMPLETED com o artifact `reserva` (JSON da reserva, com `politica` lida do resource)."""
    reserva = {chave: dados.get(chave) for chave in ORDEM_DO_ARTIFACT}
    reserva["politica"] = versao_politica
    tarefa.artifacts.append(tarefas.Artifact("reserva", json.dumps(reserva, ensure_ascii=False)))
    tarefa.responder(f"Reserva {reserva['reserva']} confirmada na {reserva['sala']}.")
    tarefa.transitar(tarefas.COMPLETED)
    registrar(tarefa, f"motivo='reserva confirmada' reserva={reserva['reserva']!r} sala={reserva['sala']!r}")


def registrar(tarefa: Tarefa, detalhe: str = "") -> None:
    """Uma linha no stderr por mudança de estado relevante: correlaciona Task e trace."""
    print(f"[agente] task={tarefa.id} estado={tarefa.estado} traceparent={tarefa.traceparent or '-'} {detalhe}".rstrip(), file=sys.stderr, flush=True)


def falhar(tarefa: Tarefa, motivo: str, detalhe_interno: str = "") -> None:
    if tarefa.terminal:  # a Task ja terminou (ex.: erro depois do COMPLETED): so registra, nao mascara o resultado
        registrar(tarefa, f"falha-apos-terminal motivo={motivo!r} interno={detalhe_interno!r}")
        return
    tarefa.responder(motivo)
    tarefa.transitar(tarefas.FAILED)
    registrar(tarefa, f"motivo={motivo!r}" + (f" interno={detalhe_interno!r}" if detalhe_interno else ""))


def tratar_resultado(tarefa: Tarefa, resultado: CallToolResult | InputRequiredResult, host: HostMCP) -> None:
    """Tabela da spec 05: o que cada resultado MCP faz com a Task."""
    if isinstance(resultado, InputRequiredResult):
        pausar(tarefa, resultado)
        return
    if resultado.is_error:
        falhar(tarefa, _texto(resultado))
        return
    dados = resultado.structured_content or {}
    if dados.get("reservado") is False:
        tarefa.responder("Reserva recusada.")
        tarefa.transitar(tarefas.CANCELED)
        registrar(tarefa, "motivo='recusada pelo usuario'")
        return
    if not dados.get("reserva"):
        falhar(tarefa, f"Resposta MCP inesperada: {_texto(resultado)}")
        return
    versao = host.versao_politica or dados.get("politica")
    if not isinstance(versao, str) or not versao:
        falhar(tarefa, "Erro interno do agente", "versao da politica desconhecida")
        return
    concluir_com_reserva(tarefa, dados, versao)


def _alternativas_da_elicitation(resultado: InputRequiredResult) -> tuple[str, list[str]] | str:
    """Extrai (chave, alternativas) de um `input_required` no formato do contrato; senão o motivo."""
    pedidos = resultado.input_requests or {}
    if len(pedidos) != 1:
        return f"esperava exatamente uma pergunta em inputRequests, vieram {len(pedidos)}"
    chave, pedido = next(iter(pedidos.items()))
    params = pedido.params
    if pedido.method != "elicitation/create" or getattr(params, "mode", None) != "form":
        return "a pergunta nao e uma elicitation em form mode"
    schema = getattr(params, "requested_schema", None) or {}
    campo = (schema.get("properties") or {}).get("sala") or {}
    alternativas = campo.get("enum") or ([campo["const"]] if "const" in campo else [])
    if not alternativas or not all(isinstance(a, str) and ESCOLHA_VALIDA_RE.match(a) and a != RECUSAR for a in alternativas):
        return "requestedSchema.properties.sala sem enum/const de ids de sala validos"
    if not isinstance(resultado.request_state, str) or not resultado.request_state:
        return "input_required sem requestState"
    return chave, list(alternativas)


def _linha_de_alternativas(alternativas: list[str]) -> str:
    return "alternativas: " + ", ".join(alternativas)


def pausar(tarefa: Tarefa, resultado: InputRequiredResult) -> None:
    """input_required → TASK_STATE_INPUT_REQUIRED. O requestState fica na Pendencia, fora do wire."""
    extraido = _alternativas_da_elicitation(resultado)
    if isinstance(extraido, str):
        falhar(tarefa, "Resposta MCP inesperada; nao foi possivel oferecer alternativas.", extraido)
        return
    chave, alternativas = extraido
    tarefa.rodadas += 1
    if tarefa.rodadas > tarefas.MAX_RODADAS:
        falhar(tarefa, "O servidor de salas pediu escolha vezes demais; refaca o pedido.", f"rodadas={tarefa.rodadas}")
        return
    tarefa.pendencia = tarefas.Pendencia(chave=chave, request_state=resultado.request_state, alternativas=alternativas)
    tarefa.marcar_pausa()
    tarefa.responder(_linha_de_alternativas(alternativas))
    tarefa.transitar(tarefas.INPUT_REQUIRED)
    registrar(tarefa, f"motivo='aguardando escolha' alternativas={alternativas}")


def interpretar_escolha(texto: str) -> str | None:
    m = ESCOLHA_RE.match(texto.strip())
    return m.group(1) if m else None


async def retomar(tarefa: Tarefa, texto: str, host: HostMCP) -> None:
    """`escolha=<valor>` → inputResponses + requestState ecoado → retry do tools/call com id novo.

    Chamada com o lock da Task já adquirido: a transição para WORKING acontece antes de
    qualquer `await`, então uma segunda continuação concorrente é recusada pelo estado.
    """
    pendencia = tarefa.pendencia
    if pendencia is None:
        falhar(tarefa, "Erro interno do agente", "task em INPUT_REQUIRED sem pendencia")
        return
    escolha = interpretar_escolha(texto)
    if escolha is None or (escolha != RECUSAR and escolha not in pendencia.alternativas):
        tarefa.escolhas_invalidas += 1
        if tarefa.escolhas_invalidas >= tarefas.MAX_ESCOLHAS_INVALIDAS:
            falhar(tarefa, "Muitas escolhas invalidas; refaca o pedido.", f"tentativas={tarefa.escolhas_invalidas}")
            return
        # Fora do enum: continua pausada e repete a lista, sem tocar na pendência (TTL renovado: há atividade).
        tarefa.marcar_pausa()
        tarefa.responder(_linha_de_alternativas(pendencia.alternativas))
        tarefa.transitar(tarefas.INPUT_REQUIRED)
        registrar(tarefa, f"motivo='escolha invalida' texto={texto[:80]!r}")
        return
    if escolha == RECUSAR:
        resposta = ElicitResult(action="decline")
    else:
        resposta = ElicitResult(action="accept", content={"sala": escolha})
    # Sob a trava do chamador e antes de qualquer await: uma segunda continuação vê WORKING e é recusada.
    tarefa.transitar(tarefas.WORKING)
    await chamar_mcp(
        tarefa,
        host,
        input_responses={pendencia.chave: resposta},
        request_state=pendencia.request_state,   # ecoado byte a byte
    )


async def chamar_mcp(tarefa: Tarefa, host: HostMCP, **kwargs: Any) -> None:
    """Uma rodada de `tools/call`: a Task sempre sai daqui em estado definido (nunca presa em WORKING)."""
    if tarefa.pedido is None:
        falhar(tarefa, "Erro interno do agente", "task sem pedido")
        return
    try:
        resultado = await host.reservar(tarefa.pedido, tarefa.traceparent, **kwargs)
        tratar_resultado(tarefa, resultado, host)
    except MCPError as erro:
        # Erro de protocolo (ex.: requestState expirado): o codigo vai ao cliente, o texto do servidor so ao log.
        falhar(tarefa, f"Servidor de salas recusou a chamada (erro MCP {erro.code}).", erro.message)
    except httpx2.TransportError as erro:
        # Para o cliente, só o fato; a URL interna e o texto da biblioteca ficam no log.
        falhar(tarefa, "Servidor de salas indisponivel.", repr(erro))
    except asyncio.CancelledError:  # shutdown ou cancelamento do handler: a Task nao pode ficar em WORKING
        falhar(tarefa, "Processamento interrompido.", "CancelledError")
        raise
    except Exception as erro:  # noqa: BLE001 - fronteira: nada deixa a Task presa em WORKING
        falhar(tarefa, "Erro interno do agente", repr(erro))


async def executar(tarefa: Tarefa, host: HostMCP) -> None:
    """Abre a rodada: Task em WORKING, `tools/call` inicial, resultado traduzido."""
    # Sob a trava do chamador e antes de qualquer await: uma segunda continuação vê WORKING e é recusada.
    tarefa.transitar(tarefas.WORKING)
    await chamar_mcp(tarefa, host)
