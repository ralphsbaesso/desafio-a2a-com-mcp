# Dúvidas e decisões tomadas sem consulta

Pontos que precisaram de uma decisão durante a implementação. Cada um foi resolvido com a opção marcada, para não travar o trabalho; se discordar, basta trocar.

| # | Ponto | Decisão tomada | Alternativa |
|---|---|---|---|
| 1 | Linguagem: o Node local é 18 (desafio exige 20+), e os wires do starter vieram do SDK Python. | **Python 3.10+ com `mcp==2.3.0`** | Instalar Node 20 e usar `@modelcontextprotocol/server` |
| 2 | O SDK Python declara a capability como `{"elicitation": {"form": {}, "url": {}}}`; o enunciado escreve `{"elicitation": {"form": {}}}`. Não há API pública para suprimir `url`. | **Manter a forma do SDK** (contém a exigida; o enunciado diz para não forçar o SDK a imitar o outro). Documentado no README. | Monkeypatch de `ClientSession._build_capabilities` para omitir `url` |
| 3 | Requests barrados pelo transporte antes do dispatcher (sem `_meta` obrigatório) não passam pelo middleware de log do servidor; aparecem só na linha de acesso do uvicorn (400). | **Aceitar e documentar** (o critério pede método/id/traceparent dos requests processados). | Middleware ASGI que lê o corpo de todo POST e loga antes do SDK |
| 4 | Onde guardar o estado das Tasks do agente. | **Dicionário em memória** (permitido pelo enunciado; não sobrevive a restart). | SQLite/arquivo JSON para sobreviver a restart |
| 5 | `responsavel` com espaços no pedido em formato fixo. | **Aceitar**: `responsavel=` consome o resto da linha. | Rejeitar com `-32602` |
| 6 | Código JSON-RPC para `SendMessage` em Task terminal. | **`-32004` UnsupportedOperationError** (spec A2A v1.0 §3.1.1) | `-32002` TaskNotCancelableError ou `-32600` |
| 7 | TTL do `requestState`. | **600 s**, configurável por `REQUEST_STATE_TTL` dentro de 300–1800. | Fixar sem variável |
| 8 | Um único `pyproject.toml` na raiz para os dois processos. | **Sim** (um `uv sync` sobe tudo; dois processos continuam separados). | Um `pyproject` por diretório |
| 9 | Na retomada, se a alternativa escolhida foi ocupada entre a pausa e o retry, o SDK re-pergunta com nova lista. | **Agente re-pausa a Task** com a lista nova (mantém `INPUT_REQUIRED`). | Falhar a Task |
| 10 | Ferramenta de QA: o `qa-panel` roda 5 agentes por task. | **Rodado após cada task** conforme pedido. | — |

Preencha-se durante a implementação; itens novos vão ao final.
