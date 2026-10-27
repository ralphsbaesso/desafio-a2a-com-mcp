"""Task A2A: modelo, máquina de estados e store em memória (spec 04).

Nada aqui conhece MCP nem regra de sala. A Task tem identidade (`id`, `contextId`),
estado (`TASK_STATE_*`) e produto (`artifacts`). A `Pendencia` guarda o que a ponte
precisa para retomar um `input_required` e NUNCA é serializada para o cliente A2A.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

SUBMITTED = "TASK_STATE_SUBMITTED"
WORKING = "TASK_STATE_WORKING"
INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
COMPLETED = "TASK_STATE_COMPLETED"
FAILED = "TASK_STATE_FAILED"
CANCELED = "TASK_STATE_CANCELED"

TERMINAIS = frozenset({COMPLETED, FAILED, CANCELED})
TRANSICOES: dict[str, frozenset[str]] = {
    SUBMITTED: frozenset({WORKING}),
    WORKING: frozenset({COMPLETED, FAILED, CANCELED, INPUT_REQUIRED}),
    INPUT_REQUIRED: frozenset({WORKING, INPUT_REQUIRED}),
}

ROLE_USER = "ROLE_USER"
ROLE_AGENT = "ROLE_AGENT"


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_hex(6)}"


class EstadoTerminal(Exception):
    """A Task já terminou; nenhuma transição é aceita."""


class TransicaoInvalida(Exception):
    """Transição fora da tabela da máquina de estados."""


@dataclass
class Mensagem:
    message_id: str
    role: str
    texto: str
    task_id: str | None = None
    context_id: str | None = None

    def para_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"messageId": self.message_id, "role": self.role, "parts": [{"text": self.texto}]}
        if self.task_id:
            wire["taskId"] = self.task_id
        if self.context_id:
            wire["contextId"] = self.context_id
        return wire


@dataclass
class Artifact:
    name: str
    texto: str
    artifact_id: str = field(default_factory=lambda: novo_id("art"))

    def para_wire(self) -> dict[str, Any]:
        return {"artifactId": self.artifact_id, "name": self.name, "parts": [{"text": self.texto}]}


@dataclass
class Pendencia:
    """O que a ponte guarda entre o `input_required` do MCP e a resposta do cliente A2A."""

    chave: str              # chave única de inputRequests, ecoada em inputResponses
    request_state: str      # opaco: guardado e ecoado byte a byte, nunca decodificado
    alternativas: list[str] # o enum (ou [const]) do requestedSchema, na ordem recebida


@dataclass
class Tarefa:
    id: str
    context_id: str
    estado: str = SUBMITTED
    mensagem_status: Mensagem | None = None
    historico: list[Mensagem] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    traceparent: str | None = None
    pedido: dict[str, Any] | None = None   # argumentos do tools/call original
    pendencia: Pendencia | None = None     # spec 05; nunca vai para o wire
    trava: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    @property
    def terminal(self) -> bool:
        return self.estado in TERMINAIS

    def transitar(self, novo: str) -> None:
        if self.terminal:
            raise EstadoTerminal(f"Task {self.id} ja esta em {self.estado}")
        if novo not in TRANSICOES.get(self.estado, frozenset()):
            raise TransicaoInvalida(f"Task {self.id}: {self.estado} -> {novo} nao e permitido")
        self.estado = novo
        if novo in TERMINAIS:
            self.pendencia = None

    def receber(self, mensagem: Mensagem) -> None:
        """Anexa a mensagem do usuário ao histórico, carimbando a Task."""
        mensagem.task_id = self.id
        mensagem.context_id = self.context_id
        self.historico.append(mensagem)

    def responder(self, texto: str) -> Mensagem:
        """Mensagem do agente: vira a mensagem de status e entra no histórico."""
        mensagem = Mensagem(novo_id("msg"), ROLE_AGENT, texto, self.id, self.context_id)
        self.historico.append(mensagem)
        self.mensagem_status = mensagem
        return mensagem

    def para_wire(self) -> dict[str, Any]:
        status: dict[str, Any] = {"state": self.estado}
        if self.mensagem_status is not None:
            status["message"] = self.mensagem_status.para_wire()
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": [m.para_wire() for m in self.historico],
            "artifacts": [a.para_wire() for a in self.artifacts],
        }


class Store:
    """Tasks em memória, por processo (não sobrevivem a restart; permitido pelo desafio).

    Ao atingir `teto`, as Tasks terminais mais antigas são expurgadas; Tasks vivas
    (WORKING / INPUT_REQUIRED) nunca são removidas.
    """

    def __init__(self, teto: int = 10_000) -> None:
        self._tarefas: dict[str, Tarefa] = {}
        self._teto = teto

    def criar(self, traceparent: str | None = None, context_id: str | None = None) -> Tarefa:
        if len(self._tarefas) >= self._teto:
            self._expurgar()
        tarefa = Tarefa(id=novo_id("task"), context_id=context_id or novo_id("ctx"), traceparent=traceparent)
        self._tarefas[tarefa.id] = tarefa
        return tarefa

    def _expurgar(self) -> None:
        excedente = len(self._tarefas) - self._teto + 1
        for task_id in [t.id for t in self._tarefas.values() if t.terminal][:excedente]:
            del self._tarefas[task_id]

    def obter(self, task_id: str) -> Tarefa | None:
        return self._tarefas.get(task_id)

    def __len__(self) -> int:
        return len(self._tarefas)
