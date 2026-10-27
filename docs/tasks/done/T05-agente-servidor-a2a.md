# T05 — Agente como servidor A2A (card, Task, SendMessage, GetTask)

Spec: [04-agente-servidor-a2a](../../specs/04-agente-servidor-a2a.md)

## Entregas

- [x] `agente/tarefas.py`: `Mensagem`, `Artifact`, `Tarefa`, store, máquina de estados com `EstadoTerminal`.
- [x] `agente/a2a.py`: card, parser do pedido fixo, handlers JSON-RPC `SendMessage`/`GetTask`, erros `-32700/-32600/-32601/-32602/-32001/-32004`.
- [x] `agente/agente.py`: app Starlette (rotas), lifespan abrindo o `HostMCP`, `main` com uvicorn.
- [x] Caminhos implementados nesta task: sala livre → `COMPLETED` com artifact; `isError` → `FAILED`; terminal recusado; `GetTask`. O `InputRequiredResult` é entregue a `ponte.py` (T06); até lá, a ponte apenas falha a Task com "não implementado".
- [x] Testes `agente/tests/test_a2a.py` com dublê do host.

## Critério de pronto

- `make test` verde.
- Validador: verificações 21–26, 31 e 35 passam (as de pausa vêm na T06).

## Registro da conclusão

- Validador com os dois processos reais: 21–26, 31, 34 e 35 PASS (27–30, 32, 33 e 36 dependem da pausa, T06).
- Painel de QA: 3 rodadas. Mudanças que vieram do painel: Task nunca fica presa em WORKING (qualquer exceção, inclusive cancelamento, leva a FAILED); mensagens ao cliente sem detalhe interno; log de transições terminais; limite de corpo por header e stream; `RecursionError` de JSON aninhado tratado; teto do store; `contextId` do cliente respeitado; módulo renomeado para `servidor_a2a.py`.
