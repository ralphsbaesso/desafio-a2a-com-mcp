# T06 — A ponte

Spec: [05-ponte](../../specs/05-ponte.md)

## Entregas

- [x] `agente/ponte.py`: `Pendencia`, `tratar_resultado`, `pausar`, `retomar`, parser de `escolha=`.
- [x] Integração em `a2a.py`: continuação com `taskId` em `INPUT_REQUIRED` passa pela ponte.
- [x] Garantia de que `GetTask`, `SendMessage` e o card nunca serializam `Pendencia`.
- [x] Máquina de estados: `INPUT_REQUIRED` também pode ir a `FAILED`/`CANCELED`; `retomar` transita para `WORKING` sob o lock da Task antes de qualquer `await` (segunda continuação concorrente recebe `-32004`).
- [x] Tasks pausadas abandonadas: TTL (ex.: 30 min) que as leva a `FAILED` por abandono, para o teto do store valer.
- [x] Testes `agente/tests/test_ponte.py`.

## Critério de pronto

- `make test` verde.
- `python3 validador/validar.py` **36/36** com os dois processos recém-subidos.
- stderr do servidor MCP mostra o par de `tools/call` (inicial e retry) com ids diferentes e o trace-id impresso pelo validador.

## Registro da conclusão

- Validador do starter com os dois processos recém-subidos: **36/36**.
- stderr do servidor MCP: `tools/list` (id 1) do agente antes do primeiro `tools/call`; todas as linhas do agente com o trace-id impresso pelo validador e span-id novo; par `tools/call` inicial/retry (`retry=sim`) com ids diferentes.
- Painel de QA: 2 rodadas. Mudanças que vieram do painel: TTL de pausa aplicado também no `GetTask` (por Task, com log), limite de escolhas inválidas e de rodadas de pausa por Task, validação das alternativas vindas do servidor, recusa com erro quando o store só tem Tasks vivas, quoting no log.
