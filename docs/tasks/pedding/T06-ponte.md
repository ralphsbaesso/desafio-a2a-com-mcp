# T06 — A ponte

Spec: [05-ponte](../../specs/05-ponte.md)

## Entregas

- [ ] `agente/ponte.py`: `Pendencia`, `tratar_resultado`, `pausar`, `retomar`, parser de `escolha=`.
- [ ] Integração em `a2a.py`: continuação com `taskId` em `INPUT_REQUIRED` passa pela ponte.
- [ ] Garantia de que `GetTask`, `SendMessage` e o card nunca serializam `Pendencia`.
- [ ] Testes `agente/tests/test_ponte.py`.

## Critério de pronto

- `make test` verde.
- `python3 validador/validar.py` **36/36** com os dois processos recém-subidos.
- stderr do servidor MCP mostra o par de `tools/call` (inicial e retry) com ids diferentes e o trace-id impresso pelo validador.
