"""Domínio da Central de Salas: dados do starter, regras da política e mensagens de erro.

Tudo aqui é determinístico e não depende da data de hoje. As reservas vivem em
memória e são reiniciadas a cada subida do processo (permitido pelo desafio).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

DADOS = Path(__file__).resolve().parent.parent / "dados"

FUSO_POLITICA = timezone(timedelta(hours=-3))
JANELA_INICIO = time(8, 0)
JANELA_FIM = time(20, 0)
DURACAO_MAXIMA = timedelta(hours=2)
MAX_ALTERNATIVAS = 3

ERRO_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"
ERRO_SEM_ALTERNATIVA = "Sem alternativas disponiveis no intervalo"
ERRO_SALA_OCUPADA = "Sala ocupada: o intervalo foi reservado por outro pedido antes de concluir"
ERRO_RESPONSAVEL = "Responsavel invalido: informe um nome nao vazio, imprimivel, com ate 100 caracteres"
RESPONSAVEL_MAXIMO = 100


def erro_sala_inexistente(sala: str) -> str:
    return f"Sala inexistente: {sala}"


SALAS: list[dict[str, Any]] = json.loads((DADOS / "salas.json").read_text(encoding="utf-8"))
POLITICA_TEXTO: str = (DADOS / "politica-de-uso.md").read_text(encoding="utf-8")
POLITICA_VERSAO: str = POLITICA_TEXTO.splitlines()[0].split(":", 1)[1].strip()

RESERVAS: list[dict[str, Any]] = []
# O SDK executa tools sincronas em thread: a checagem de conflito e a gravacao
# acontecem sob este lock para que duas reservas simultaneas nao se sobreponham.
TRAVA = threading.Lock()
_proximo_id = 1


def reiniciar_reservas() -> None:
    """Volta as reservas ao estado do starter (usado na subida e nos testes)."""
    global _proximo_id
    with TRAVA:
        RESERVAS[:] = json.loads((DADOS / "reservas.json").read_text(encoding="utf-8"))
        _proximo_id = len(RESERVAS) + 1


reiniciar_reservas()


def obter_sala(sala: str) -> dict[str, Any]:
    for s in SALAS:
        if s["id"] == sala:
            return s
    raise ToolError(erro_sala_inexistente(sala))


def _instante(texto: str) -> datetime:
    try:
        valor = datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ToolError(f"Intervalo invalido: data fora do formato ISO 8601: {texto}") from None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=FUSO_POLITICA)
    return valor.astimezone(FUSO_POLITICA)


def validar_responsavel(responsavel: str) -> str:
    nome = responsavel.strip()
    if not nome or len(nome) > RESPONSAVEL_MAXIMO or not nome.isprintable():
        raise ToolError(ERRO_RESPONSAVEL)
    return nome


def validar_pedido(sala: str, inicio: str, fim: str) -> tuple[datetime, datetime]:
    """Aplica, nesta ordem: sala existe, datas válidas, fim > inicio, janela, duração."""
    obter_sala(sala)
    ini, end = _instante(inicio), _instante(fim)
    if end <= ini:
        raise ToolError(ERRO_INTERVALO)
    for t in (ini, end):
        if not (JANELA_INICIO <= t.time() <= JANELA_FIM):
            raise ToolError(ERRO_JANELA)
    if end - ini > DURACAO_MAXIMA:
        raise ToolError(ERRO_DURACAO)
    return ini, end


def conflitos(sala: str, ini: datetime, end: datetime) -> list[dict[str, Any]]:
    """Reservas da sala que se sobrepõem ao intervalo (bordas iguais não conflitam).

    Leitura sem a trava, sobre um snapshot: pode ficar um instante defasada, e por isso
    a decisão final de gravar é sempre revalidada dentro de `reservar_se_livre`.
    """
    achados = []
    for r in tuple(RESERVAS):
        if r["sala"] != sala:
            continue
        if _instante(r["inicio"]) < end and ini < _instante(r["fim"]):
            achados.append(r)
    return achados


def alternativas(sala: str, ini: datetime, end: datetime) -> list[str]:
    """Salas livres no intervalo com capacidade >= à pedida, por (capacidade, id), no máximo três."""
    capacidade = obter_sala(sala)["capacidade"]
    candidatas = [
        s for s in SALAS
        if s["id"] != sala and s["capacidade"] >= capacidade and not conflitos(s["id"], ini, end)
    ]
    candidatas.sort(key=lambda s: (s["capacidade"], s["id"]))
    return [s["id"] for s in candidatas[:MAX_ALTERNATIVAS]]


def reservar_se_livre(sala: str, inicio: str, fim: str, responsavel: str) -> dict[str, Any]:
    """Seção crítica: revalida o pedido, confere o conflito e grava, tudo sob o lock."""
    global _proximo_id
    ini, end = validar_pedido(sala, inicio, fim)
    with TRAVA:
        if conflitos(sala, ini, end):
            raise ToolError(ERRO_SALA_OCUPADA)
        reserva = {
            "id": f"res-{_proximo_id:04d}",
            "sala": sala,
            "inicio": inicio,
            "fim": fim,
            "responsavel": responsavel,
        }
        _proximo_id += 1
        RESERVAS.append(reserva)
    return reserva
