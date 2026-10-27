"""Agente Central de Salas: servidor A2A por fora (porta 7300), host MCP por dentro.

    uv run python agente/agente.py

Rotas: GET /.well-known/agent-card.json e POST /a2a (JSON-RPC 2.0: SendMessage, GetTask).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from servidor_a2a import ServidorA2A, agent_card
from host_mcp import HostMCP
from tarefas import Store

LIMITE_DO_CORPO = 64 * 1024  # o maior pedido legitimo tem poucas centenas de bytes


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    mcp_url: str
    url_publica: str


def _env(nome: str, padrao: str) -> str:
    return os.environ.get(nome, "").strip() or padrao


def carregar_config() -> Config:
    try:
        port = int(_env("AGENTE_PORT", "7300"))
    except ValueError:
        raise SystemExit("AGENTE_PORT precisa ser numerica") from None
    if not 1 <= port <= 65535:
        raise SystemExit("AGENTE_PORT precisa ficar entre 1 e 65535")
    host = _env("AGENTE_HOST", "127.0.0.1")
    return Config(
        host=host,
        port=port,
        mcp_url=_env("MCP_URL", "http://127.0.0.1:7301/mcp"),
        url_publica=_env("AGENTE_URL_PUBLICA", f"http://{host}:{port}/a2a"),
    )


def _corpo_grande() -> Response:
    return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Corpo grande demais"}}, status_code=413)


def criar_app(host_mcp: HostMCP, url_publica: str, store: Store | None = None) -> Starlette:
    servidor = ServidorA2A(host_mcp, store or Store(), url_publica)

    async def card(_: Request) -> Response:
        return JSONResponse(agent_card(url_publica))

    async def rpc(request: Request) -> Response:
        declarado = request.headers.get("content-length")
        if declarado and declarado.isdigit() and int(declarado) > LIMITE_DO_CORPO:
            return _corpo_grande()
        bruto = b""
        async for pedaco in request.stream():
            bruto += pedaco
            if len(bruto) > LIMITE_DO_CORPO:
                return _corpo_grande()
        try:
            corpo = json.loads(bruto)
        except (ValueError, RecursionError):  # JSON invalido ou aninhado demais: nunca um 500
            corpo = None
        resposta = await servidor.tratar(corpo, dict(request.headers))
        return JSONResponse(resposta)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        await host_mcp.abrir()
        try:
            yield
        finally:
            await host_mcp.fechar()

    app = Starlette(
        routes=[Route("/.well-known/agent-card.json", card, methods=["GET"]), Route("/a2a", rpc, methods=["POST"])],
        lifespan=lifespan,
    )
    app.state.servidor = servidor
    return app


def main() -> None:
    config = carregar_config()
    try:
        host_mcp = HostMCP(config.mcp_url)
    except ValueError as erro:
        raise SystemExit(str(erro)) from None
    if config.host not in ("127.0.0.1", "localhost") and not _env("AGENTE_URL_PUBLICA", ""):
        print(f"[agente] aviso: AGENTE_HOST={config.host} sem AGENTE_URL_PUBLICA; o card anuncia {config.url_publica}", file=sys.stderr, flush=True)
    print(
        f"[agente] central-de-salas em http://{config.host}:{config.port}/a2a "
        f"(card em /.well-known/agent-card.json; servidor MCP em {config.mcp_url})",
        file=sys.stderr,
        flush=True,
    )
    uvicorn.run(criar_app(host_mcp, config.url_publica), host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
