"""O agente como servidor A2A v1.0: Agent Card e binding JSON-RPC 2.0 (spec 04).

Métodos: `SendMessage` e `GetTask`. Tudo fora disso é recusado. O agente não tem LLM:
o pedido chega em formato fixo e é interpretado por regra.
"""

from __future__ import annotations

import re
import sys
from typing import Any

import ponte
import tarefas
from host_mcp import HostMCP, traceparent_valido
from tarefas import Mensagem, Store, Tarefa

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001           # A2A TaskNotFoundError
UNSUPPORTED_OPERATION = -32004    # A2A UnsupportedOperationError

PEDIDO_RE = re.compile(r"^reservar\s+sala=(\S+)\s+inicio=(\S+)\s+fim=(\S+)\s+responsavel=(.+)$")
FORMATO_PEDIDO = "reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>"


class ErroA2A(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def para_wire(self) -> dict[str, Any]:
        erro: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            erro["data"] = self.data
        return erro


def agent_card(url_publica: str) -> dict[str, Any]:
    return {
        "name": "Central de Salas",
        "description": "Reserva salas de reuniao da Hill Valley Tech.",
        "provider": {"organization": "Hill Valley Tech", "url": "https://hillvalley.example"},
        "version": "1.0.0",
        "supportedInterfaces": [{"url": url_publica, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "reservar-sala",
                "name": "Reservar sala",
                "description": "Reserva uma sala em um intervalo. Se houver conflito, pergunta qual alternativa usar.",
                "tags": ["salas", "agenda"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
                "examples": ["reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Marty"],
            }
        ],
    }


def interpretar_pedido(texto: str) -> dict[str, str]:
    """Formato fixo, sem LLM. `responsavel` consome o resto da linha (nomes com espaço)."""
    m = PEDIDO_RE.match(texto.strip())
    if not m:
        raise ErroA2A(INVALID_PARAMS, f"Pedido fora do formato esperado: {FORMATO_PEDIDO}")
    sala, inicio, fim, responsavel = m.groups()
    return {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel.strip()}


def _texto_da_mensagem(mensagem: Any) -> str:
    if not isinstance(mensagem, dict):
        raise ErroA2A(INVALID_PARAMS, "params.message precisa ser um objeto")
    partes = mensagem.get("parts")
    if not isinstance(partes, list) or not partes:
        raise ErroA2A(INVALID_PARAMS, "params.message.parts precisa ser uma lista com ao menos uma parte")
    textos = [p.get("text") for p in partes if isinstance(p, dict) and isinstance(p.get("text"), str)]
    if not textos:
        raise ErroA2A(INVALID_PARAMS, "params.message.parts precisa ter uma parte de texto")
    return " ".join(t.strip() for t in textos).strip()


class ServidorA2A:
    def __init__(self, host: HostMCP, store: Store, url_publica: str) -> None:
        self.host = host
        self.store = store
        self.url_publica = url_publica

    # ------------------------------------------------------------------ envelope JSON-RPC

    async def tratar(self, corpo: Any, headers: dict[str, str]) -> dict[str, Any]:
        """Recebe o corpo já decodificado (ou `None` se o JSON era inválido) e devolve o envelope."""
        if corpo is None:
            return self._erro(None, ErroA2A(PARSE_ERROR, "Corpo nao e JSON valido"))
        if not isinstance(corpo, dict) or corpo.get("jsonrpc") != "2.0" or not isinstance(corpo.get("method"), str):
            return self._erro(corpo.get("id") if isinstance(corpo, dict) else None, ErroA2A(INVALID_REQUEST, "Envelope JSON-RPC 2.0 invalido"))
        req_id = corpo.get("id")
        params = corpo.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._erro(req_id, ErroA2A(INVALID_PARAMS, "params precisa ser um objeto"))
        traceparent = traceparent_valido(_header(headers, "traceparent"))
        try:
            if corpo["method"] == "SendMessage":
                tarefa = await self.send_message(params, traceparent)
            elif corpo["method"] == "GetTask":
                tarefa = self.get_task(params)
            else:
                raise ErroA2A(METHOD_NOT_FOUND, f"Metodo nao suportado: {corpo['method']}")
        except ErroA2A as erro:
            return self._erro(req_id, erro)
        except Exception as erro:  # noqa: BLE001 - fronteira: nada interno vaza para o wire
            print(f"[agente] erro interno em {corpo['method']}: {erro!r}", file=sys.stderr, flush=True)
            return self._erro(req_id, ErroA2A(INTERNAL_ERROR, "Erro interno do agente"))
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": tarefa.para_wire()}}

    @staticmethod
    def _erro(req_id: Any, erro: ErroA2A) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": erro.para_wire()}

    # ------------------------------------------------------------------ métodos A2A

    async def send_message(self, params: dict[str, Any], traceparent: str | None) -> Tarefa:
        mensagem = params.get("message")
        texto = _texto_da_mensagem(mensagem)
        message_id = mensagem.get("messageId") if isinstance(mensagem.get("messageId"), str) else tarefas.novo_id("msg")
        entrada = Mensagem(message_id, tarefas.ROLE_USER, texto)
        task_id = mensagem.get("taskId")
        context_id = mensagem.get("contextId")
        if context_id is not None and not isinstance(context_id, str):
            raise ErroA2A(INVALID_PARAMS, "params.message.contextId precisa ser string")

        if task_id is None:
            pedido = interpretar_pedido(texto)          # antes de abrir a Task: pedido inválido não cria Task
            tarefa = self.store.criar(traceparent, context_id)
            tarefa.pedido = pedido
            tarefa.receber(entrada)
            await ponte.executar(tarefa, self.host)
            return tarefa

        tarefa = self._obter(task_id)
        if context_id is not None and context_id != tarefa.context_id:
            raise ErroA2A(INVALID_PARAMS, f"contextId {context_id!r} nao pertence a Task {tarefa.id}")
        async with tarefa.trava:
            if tarefa.terminal:
                raise ErroA2A(UNSUPPORTED_OPERATION, f"Task {tarefa.id} ja terminou em {tarefa.estado} e nao aceita novas mensagens")
            if tarefa.estado != tarefas.INPUT_REQUIRED:
                raise ErroA2A(UNSUPPORTED_OPERATION, f"Task {tarefa.id} esta em {tarefa.estado} e nao espera mensagem")
            if traceparent:
                tarefa.traceparent = traceparent
            tarefa.receber(entrada)
            await ponte.retomar(tarefa, texto, self.host)
            return tarefa

    def get_task(self, params: dict[str, Any]) -> Tarefa:
        return self._obter(params.get("id"))

    def _obter(self, task_id: Any) -> Tarefa:
        tarefa = self.store.obter(task_id) if isinstance(task_id, str) else None
        if tarefa is None:
            raise ErroA2A(TASK_NOT_FOUND, f"Task nao encontrada: {task_id!r}")
        return tarefa


def _header(headers: dict[str, str], nome: str) -> str | None:
    for chave, valor in headers.items():
        if chave.lower() == nome:
            return valor
    return None
