# T06 — A ponte

Spec: [05-ponte](../../specs/05-ponte.md)

## Entregas

- [ ] `agente/ponte.py`: `Pendencia`, `tratar_resultado`, `pausar`, `retomar`, parser de `escolha=`.
- [ ] Integração em `a2a.py`: continuação com `taskId` em `INPUT_REQUIRED` passa pela ponte.
- [ ] Garantia de que `GetTask`, `SendMessage` e o card nunca serializam `Pendencia`.
- [ ] Máquina de estados: `INPUT_REQUIRED` também pode ir a `FAILED`/`CANCELED`; `retomar` transita para `WORKING` sob o lock da Task antes de qualquer `await` (segunda continuação concorrente recebe `-32004`).
- [ ] Tasks pausadas abandonadas: TTL (ex.: 30 min) que as leva a `FAILED` por abandono, para o teto do store valer.
- [ ] Testes `agente/tests/test_ponte.py`.

## Critério de pronto

- `make test` verde.
- `python3 validador/validar.py` **36/36** com os dois processos recém-subidos.
- stderr do servidor MCP mostra o par de `tools/call` (inicial e retry) com ids diferentes e o trace-id impresso pelo validador.
