"""A ponte: o resultado cru do servidor MCP vira estado de Task A2A (spec 05).

Nesta task (T05) a ponte trata o resultado `complete` (reserva, recusa, erro de
execução) e os erros de transporte/protocolo. A pausa em `TASK_STATE_INPUT_REQUIRED`
e a retomada com `requestState` entram na T06.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx2
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, InputRequiredResult

import tarefas
from host_mcp import HostMCP
from tarefas import Tarefa

ORDEM_DO_ARTIFACT = ("reserva", "sala", "inicio", "fim", "responsavel", "politica")


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
    registrar(tarefa, f"motivo='reserva confirmada' reserva={reserva['reserva']} sala={reserva['sala']}")


def registrar(tarefa: Tarefa, detalhe: str = "") -> None:
    """Uma linha no stderr por mudança de estado relevante: correlaciona Task e trace."""
    print(f"[agente] task={tarefa.id} estado={tarefa.estado} traceparent={tarefa.traceparent or '-'} {detalhe}".rstrip(), file=sys.stderr, flush=True)


def falhar(tarefa: Tarefa, motivo: str, detalhe_interno: str = "") -> None:
    if tarefa.terminal:  # a Task ja terminou (ex.: erro depois do COMPLETED): so registra, nao mascara o resultado
        registrar(tarefa, f"falha-apos-terminal motivo={motivo!r} interno={detalhe_interno}")
        return
    tarefa.responder(motivo)
    tarefa.transitar(tarefas.FAILED)
    registrar(tarefa, f"motivo={motivo!r}" + (f" interno={detalhe_interno}" if detalhe_interno else ""))


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


def pausar(tarefa: Tarefa, resultado: InputRequiredResult) -> None:
    falhar(tarefa, "Pausa em input_required ainda nao implementada (T06).")


async def retomar(tarefa: Tarefa, texto: str, host: HostMCP) -> None:
    falhar(tarefa, "Retomada ainda nao implementada (T06).")


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
    tarefa.transitar(tarefas.WORKING)
    await chamar_mcp(tarefa, host)
