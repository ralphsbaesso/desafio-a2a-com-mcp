# T05 — Agente como servidor A2A (card, Task, SendMessage, GetTask)

Spec: [04-agente-servidor-a2a](../../specs/04-agente-servidor-a2a.md)

## Entregas

- [ ] `agente/tarefas.py`: `Mensagem`, `Artifact`, `Tarefa`, store, máquina de estados com `EstadoTerminal`.
- [ ] `agente/a2a.py`: card, parser do pedido fixo, handlers JSON-RPC `SendMessage`/`GetTask`, erros `-32700/-32600/-32601/-32602/-32001/-32004`.
- [ ] `agente/agente.py`: app Starlette (rotas), lifespan abrindo o `HostMCP`, `main` com uvicorn.
- [ ] Caminhos implementados nesta task: sala livre → `COMPLETED` com artifact; `isError` → `FAILED`; terminal recusado; `GetTask`. O `InputRequiredResult` é entregue a `ponte.py` (T06); até lá, a ponte apenas falha a Task com "não implementado".
- [ ] Testes `agente/tests/test_a2a.py` com dublê do host.

## Critério de pronto

- `make test` verde.
- Validador: verificações 21–26, 31 e 35 passam (as de pausa vêm na T06).
