# T04 — Agente como host MCP

Spec: [03-agente-host-mcp](../../specs/03-agente-host-mcp.md)

## Entregas

- [x] `agente/host_mcp.py`: classe `HostMCP` (`abrir/fechar`, `descobrir`, `versao_politica`, `reservar`), geração de `traceparent` com span novo, `_meta` por request.
- [x] `agente/demo_host.py`: script que percorre o ciclo MRTR na mão contra o servidor em `MCP_URL`.
- [x] Testes `agente/tests/test_host_mcp.py` com o servidor in-process.

## Critério de pronto

- `make test` verde.
- `uv run python agente/demo_host.py` contra o servidor real mostra: `tools/list` antes do primeiro `tools/call` no stderr do servidor, o `input_required` cru, o retry com id novo e a reserva concluída, com o mesmo trace-id em todas as linhas.

## Registro da conclusão

- Demo contra o servidor real: stderr mostra `tools/list` (id 1) → `resources/read` (id 2) → `tools/call` → `tools/call retry=sim`, ids distintos, mesmo trace-id e span-id novo em cada linha.
- Sonda manual de resiliência: reserva, servidor MCP morto → `ConnectError` isolado, servidor de volta → reserva seguinte conclui sem reiniciar o agente.
- Painel de QA: 3 rodadas. Achados que mudaram o desenho: falta de timeout (servidor mudo prendia o lock de descoberta); `Client` de longa duração do SDK inutilizável após falha de conexão → pool HTTP + `Client` por operação; ids JSON-RPC colidindo sob concorrência → janela atômica de ids por operação (duvidas #14).
