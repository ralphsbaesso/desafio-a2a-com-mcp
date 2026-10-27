# T02 — Servidor MCP: transporte, `listar_salas`, `consultar_disponibilidade`, resource e log

Spec: [01-servidor-mcp-base](../../specs/01-servidor-mcp-base.md)

## Entregas

- [x] `servidor-mcp/dominio.py`: carga de `dados/`, `obter_sala`, `validar_pedido`, `conflitos`, `alternativas`, constantes de mensagens, `POLITICA_VERSAO`.
- [x] `servidor-mcp/servidor.py`: `MCPServer("central-de-salas")`, tools `listar_salas` e `consultar_disponibilidade` com modelos de saída, resource `politica://uso` (`text/markdown`), middleware de log no stderr, `main` lendo env e exigindo `REQUEST_STATE_SECRET` (já configurando `RequestStateSecurity`, usado na T03).
- [x] Configuração: variável de ambiente vazia conta como ausente; porta e `REQUEST_STATE_TTL` inválidos saem com mensagem clara (sem traceback).
- [x] Testes `servidor-mcp/tests/test_dominio.py` e `test_servidor.py`.

## Critério de pronto

- `make test` verde.
- Com o servidor no ar, `python3 validador/validar.py` passa nas verificações 01–12 (as 13–20 dependem da T03).
- stderr mostra `method`, `id` e `traceparent` de cada request.
