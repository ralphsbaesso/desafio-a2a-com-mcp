# T04 — Agente como host MCP

Spec: [03-agente-host-mcp](../../specs/03-agente-host-mcp.md)

## Entregas

- [ ] `agente/host_mcp.py`: classe `HostMCP` (`abrir/fechar`, `descobrir`, `versao_politica`, `reservar`), geração de `traceparent` com span novo, `_meta` por request.
- [ ] `agente/demo_host.py`: script que percorre o ciclo MRTR na mão contra o servidor em `MCP_URL`.
- [ ] Testes `agente/tests/test_host_mcp.py` com o servidor in-process.

## Critério de pronto

- `make test` verde.
- `uv run python agente/demo_host.py` contra o servidor real mostra: `tools/list` antes do primeiro `tools/call` no stderr do servidor, o `input_required` cru, o retry com id novo e a reserva concluída, com o mesmo trace-id em todas as linhas.
