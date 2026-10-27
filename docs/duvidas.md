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
| 11 | `starlette` 1.10 (dependência do `mcp` 2.3.0) exige Python ≥ 3.11; o desafio fala em 3.10+ para o validador. | **`requires-python = ">=3.11"`** para os dois processos; o validador (stdlib) continua rodando em 3.10. Documentado no README. | Travar `starlette<1.10` para manter 3.10 |
| 12 | `responsavel` não tem regra no enunciado. | **Exigir nome não vazio com até 100 caracteres** (`Responsavel invalido: ...`), validado antes de qualquer pausa. | Aceitar qualquer string |
| 13 | Replay do mesmo `requestState` + `inputResponses` dentro do TTL (ex.: retry duplicado escolhendo outra alternativa) cria outra reserva. | **Aceitar**: cada retry é um request independente e a spec não exige uso único; o SDK re-pergunta se a lista mudou. Vai para a seção de decisões técnicas do README final (T07). | Deduplicar por (sala, inicio, fim, responsavel) ou nonce de uso único |
| 14 | O `Client` de longa duração do SDK 2.3.0 fica inutilizável após uma falha de conexão (task group cancelado) e exige `__aenter__`/`__aexit__` na mesma task. | **Pool HTTP por processo + `Client` por operação**, reservando atomicamente uma janela de 4 ids por operação e semeando com ela o contador privado `_next_id` do dispatcher, para ids JSON-RPC únicos e crescentes mesmo com Tasks concorrentes (testes sequencial e concorrente; SDK pinado; remover o truque quando o SDK expuser um gerador de ids). | `Client` único reciclado por uma task supervisora |
| 15 | A ponte conhece o formato do `structuredContent` de `reservar_sala` (campos do artifact, `reservado`, texto de confirmação). | **Aceitar**: há uma única tool; o mapeamento fica concentrado em `ponte.py` e documentado. | Módulo de "apresentação" injetável por tool |
| 16 | Store de Tasks sem limite. | **Teto de 10.000 Tasks** com expurgo das terminais mais antigas; Tasks vivas nunca saem. Corpo do POST limitado a 64 KB. | TTL por Task |
| 17 | `SendMessage` repetido (retry de rede com o mesmo `messageId`) abre outra Task e outro `tools/call`; se o MCP cair depois de gravar, o cliente vê FAILED com a sala já reservada. | **Não deduplicar** (o enunciado não pede idempotência; a reserva atômica no MCP evita sobreposição). Documentado como limitação no README. | Mapa `messageId → Task` no store |

Preencha-se durante a implementação; itens novos vão ao final.
