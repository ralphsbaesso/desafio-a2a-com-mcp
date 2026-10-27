# T03 — Servidor MCP: `reservar_sala` com o ciclo MRTR

Spec: [02-servidor-mcp-mrtr](../../specs/02-servidor-mcp-mrtr.md)

## Entregas

- [ ] Resolver `escolha_de_sala` (validação, conflito, alternativas, `Elicit` com schema dinâmico, `ToolError` sem alternativas).
- [ ] Tool `reservar_sala` com `Annotated[ElicitationResult, Resolve(escolha_de_sala)]`, caminho feliz, recusa e gravação em memória.
- [ ] `RequestStateSecurity(keys=[REQUEST_STATE_SECRET], ttl=REQUEST_STATE_TTL)` com validação do TTL (300–1800).
- [ ] Testes `servidor-mcp/tests/test_mrtr.py` cobrindo a lista da spec.

## Critério de pronto

- `make test` verde.
- `python3 validador/validar.py` passa nas verificações 01–20 com o servidor recém-subido.
- Teste manual: pegar o `requestState` do conflito, reiniciar o servidor com o mesmo segredo, fazer o retry e concluir a reserva (passo 12 do avaliador). Registrar o resultado na task ao movê-la para done.
