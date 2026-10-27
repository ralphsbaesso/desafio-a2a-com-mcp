# Spec 06 — Entrega, scripts e README

Cobre o requisito 6 e o bloco "Validação e entrega" do desafio, mais as duas seções pedidas em [task.md](../../task.md).

## Scripts de subida (raiz)

`Makefile` com alvos:

| Alvo | Faz |
|---|---|
| `install` | `uv sync` (cria `.venv`, instala com versões do `uv.lock`) |
| `mcp` | `uv run python servidor-mcp/servidor.py` (exige `REQUEST_STATE_SECRET`) |
| `agente` | `uv run python agente/agente.py` |
| `validar` | `python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301` |
| `test` | `uv run pytest` |
| `secret` | imprime um segredo novo (`python3 -c "import secrets; print(secrets.token_hex(32))"`) |

`.env.example` lista as variáveis da spec 00 com valores de exemplo (`REQUEST_STATE_SECRET=<gere com make secret>`). `.env` está no `.gitignore`.

## Estrutura do README.md final

1. **Título + descrição do projeto** (pedido do task.md): o que é, os dois processos, stack, diagrama curto.
2. **Como rodar**: pré-requisitos (Python ≥ 3.11 para os processos, `uv`; o validador roda em 3.10+), clone, `make install`, gerar e exportar `REQUEST_STATE_SECRET`, terminal 1 `make mcp`, terminal 2 `make agente`, `make validar`. Comandos literais, testados a partir de um clone limpo. Também os comandos sem `make`.
3. **Onde a ponte acontece**: parágrafo apontando `agente/ponte.py::pausar` (o `input_required` vira `TASK_STATE_INPUT_REQUIRED`) e `agente/ponte.py::retomar` (o `requestState` volta ao servidor em `host_mcp.py::reservar`), com o par de ids no stderr do servidor.
4. **Decisões técnicas**: proteção do `requestState` (AES-256-GCM via `RequestStateSecurity` do SDK, chave do ambiente, HKDF), validade (TTL 600 s configurável 300–1800), estado das Tasks (dicionário em memória no agente, pendência por Task), capability `form`+`url` emitida pelo SDK, logging de requests barrados pelo transporte, retry re-perguntando quando a lista muda, mensagens de erro com prefixo do SDK.
5. **Saída do validador**: bloco de código com a saída completa da última execução (36 PASS).
6. **Fluxo manual do avaliador**: os `curl` dos passos 7–13 prontos para colar.
7. **Testes**: `make test`.
8. **Sobre este repositório** (última seção, pedido do task.md): desafio do curso de MCP e A2A do MBA Engenharia de Software com IA (Full Cycle), link do starter, aviso de que `dados/`, `validador/` e `exemplos/` são do starter e não foram alterados.

## Checklist de entrega

- [ ] `git diff --stat` mostra zero mudanças em `dados/`, `validador/`, `exemplos/`, `docs/challenge.md`.
- [ ] `uv.lock` commitado; `pyproject.toml` sem SDK de LLM.
- [ ] Validador 36/36 com os dois processos recém-subidos; saída colada no README.
- [ ] Passo 12 do avaliador (restart do MCP entre pausa e retry) executado à mão e registrado no README.
- [ ] `docs/duvidas.md` com os pontos que dependem de decisão do autor.
- [ ] Todas as tasks em `docs/tasks/done/`.
