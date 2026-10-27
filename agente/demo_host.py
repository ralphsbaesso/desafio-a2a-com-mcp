"""Passo 6 da ordem sugerida do desafio: o agente como cliente MCP puro, sem A2A.

Descobre as tools, lê o resource, pede uma sala ocupada, mostra o `input_required` cru,
responde a elicitation na mão (primeira alternativa) e imprime a reserva. Rode com o
servidor MCP no ar:

    uv run python agente/demo_host.py [traceparent]
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys

import httpx2
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult

from host_mcp import HostMCP, traceparent_valido

PEDIDO = {
    "sala": "sala-garagem",
    "inicio": "2026-11-03T14:00:00-03:00",
    "fim": "2026-11-03T15:00:00-03:00",
    "responsavel": "Marty",
}


def mostrar(titulo: str, dado: object) -> None:
    print(f"\n== {titulo}")
    print(json.dumps(dado, ensure_ascii=False, indent=2))


def concluiu(resultado: CallToolResult | InputRequiredResult, etapa: str) -> bool:
    """Imprime o diagnostico de um tools/call; True quando e uma reserva concluida sem erro."""
    mostrar(etapa, resultado.model_dump(by_alias=True, exclude_none=True))
    if isinstance(resultado, InputRequiredResult):
        return False
    if resultado.is_error:
        texto = getattr(resultado.content[0], "text", "") if resultado.content else ""
        print(f"\nerro de execucao da tool: {texto or resultado.model_dump(by_alias=True)}")
        print("reinicie o servidor MCP para voltar ao estado inicial das reservas.")
    return not resultado.is_error


async def main() -> None:
    url = os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp")
    traceparent = traceparent_valido(sys.argv[1]) if len(sys.argv) > 1 else None
    if len(sys.argv) > 1 and traceparent is None:
        print(f"aviso: traceparent invalido ({sys.argv[1]!r}); usando um gerado", file=sys.stderr)
    traceparent = traceparent or f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
    try:
        host = HostMCP(url)
    except ValueError as erro:
        print(f"configuracao invalida: {erro}", file=sys.stderr)
        raise SystemExit(1) from None
    await host.abrir()
    try:
        await host.preparar(traceparent)
        mostrar("tools descobertas (tools/list antes do primeiro tools/call)", host.tools)
        mostrar("versao da politica (resources/read politica://uso)", host.versao_politica)

        resultado = await host.reservar(PEDIDO, traceparent)
        if isinstance(resultado, CallToolResult):
            if concluiu(resultado, "primeiro tools/call"):
                print("\nsala livre: nao houve pausa. Rode de novo para ver o input_required.")
            return

        concluiu(resultado, "primeiro tools/call")
        if len(resultado.input_requests or {}) != 1:
            print("\ninput_required sem exatamente uma pergunta; nao sei responder.", file=sys.stderr)
            raise SystemExit(1)
        chave, pedido = next(iter(resultado.input_requests.items()))
        campo = (getattr(pedido.params, "requested_schema", None) or {}).get("properties", {}).get("sala", {})
        alternativas = campo.get("enum") or ([campo["const"]] if "const" in campo else [])
        if not alternativas:
            print("\na elicitation nao trouxe alternativas em properties.sala (enum/const).", file=sys.stderr)
            raise SystemExit(1)
        mostrar("alternativas oferecidas", alternativas)

        escolha = alternativas[0]
        print(f"\nrespondendo a elicitation na mao: escolha={escolha} (retry com id JSON-RPC novo)")
        retry = await host.reservar(
            PEDIDO,
            traceparent,
            input_responses={chave: ElicitResult(action="accept", content={"sala": escolha})},
            request_state=resultado.request_state,
        )
        if concluiu(retry, "retry"):
            print(f"\nconfira no stderr do servidor MCP o trace-id {traceparent.split('-')[1]} em todas as linhas.")
    except httpx2.TransportError as erro:
        print(f"\nnao consegui falar com o servidor MCP em {url}: {erro!r}\nsuba-o com: make mcp", file=sys.stderr)
        raise SystemExit(1) from None
    except MCPError as erro:
        print(f"\no servidor em {url} respondeu erro MCP {erro.code}: {erro.message}\nconfira MCP_URL (termina em /mcp?) e o stderr do servidor.", file=sys.stderr)
        raise SystemExit(1) from None
    except RuntimeError as erro:
        print(f"\nfalha ao usar o servidor MCP em {url}: {erro}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        await host.fechar()


if __name__ == "__main__":
    asyncio.run(main())
