# T03 — Servidor MCP: `reservar_sala` com o ciclo MRTR

Spec: [02-servidor-mcp-mrtr](../../specs/02-servidor-mcp-mrtr.md)

## Entregas

- [x] Resolver `escolha_de_sala` (validação, conflito, alternativas, `Elicit` com schema dinâmico, `ToolError` sem alternativas).
- [x] Tool `reservar_sala` com `Annotated[ElicitationResult, Resolve(escolha_de_sala)]`, caminho feliz, recusa e gravação em memória.
- [x] `RequestStateSecurity(keys=[REQUEST_STATE_SECRET], ttl=REQUEST_STATE_TTL)` com validação do TTL (300–1800).
- [x] Testes `servidor-mcp/tests/test_mrtr.py` cobrindo a lista da spec.

## Critério de pronto

- `make test` verde.
- `python3 validador/validar.py` passa nas verificações 01–20 com o servidor recém-subido.
- Teste manual: pegar o `requestState` do conflito, reiniciar o servidor com o mesmo segredo, fazer o retry e concluir a reserva (passo 12 do avaliador). Registrar o resultado na task ao movê-la para done.

## Registro da conclusão

- Validador do starter: verificações 01–20 PASS com o servidor recém-subido.
- Passo 12 do avaliador executado à mão: `requestState` obtido com o corpo do wire 03, servidor reiniciado com o mesmo `REQUEST_STATE_SECRET`, retry com o corpo do wire 04 → `complete` com `res-0003` em `sala-fusca`. Com um caractere trocado → HTTP 400, `-32602` "Invalid or expired requestState".
- Painel de QA: 2 rodadas; a primeira apontou checa-e-grava não atômico (tools síncronas rodam em thread no SDK), corrigido com lock e contador de id.
