# Spec 01 — Servidor MCP: transporte, tools de consulta, resource e log

Cobre o requisito 1 do desafio (exceto `reservar_sala`, que está na spec 02).
Arquivos: `servidor-mcp/dominio.py`, `servidor-mcp/servidor.py`.

## Transporte

- `MCPServer(name="central-de-salas", version="1.0.0")` do SDK, rodando `streamable-http` com `json_response=True` e `stateless_http=True`, host/porta das variáveis `MCP_HOST`/`MCP_PORT` (padrão `127.0.0.1:7301`), caminho `/mcp`.
- O SDK, ao receber `MCP-Protocol-Version: 2026-07-28`, usa a entrada "moderna": um POST por request, sem `initialize`, sem `Mcp-Session-Id`. É ele quem:
  - rejeita `_meta` sem `io.modelcontextprotocol/protocolVersion` ou sem `io.modelcontextprotocol/clientCapabilities` com `-32602` e HTTP `400` (verificado no estudo: validador 04 e 05 passam);
  - rejeita header `Mcp-Method`/`Mcp-Name`/`MCP-Protocol-Version` que não bate com o corpo com `-32020`;
  - mapeia código de erro → status HTTP (`-32602`→400, `-32021`→400).
- Nada é inferido de request anterior: não há estado de protocolo no processo.

## Capabilities declaradas

`tools` e `resources` (o `MCPServer` declara automaticamente ao registrar ao menos uma tool e um resource). Sem prompts, sem subscriptions.

## Domínio (`dominio.py`)

Carregado uma vez na subida, de `dados/` (caminho relativo à raiz do repositório, resolvido a partir do arquivo):

- `SALAS`: lista de `dados/salas.json`.
- `RESERVAS`: lista mutável iniciada de `dados/reservas.json`. Em memória; ids novos seguem `res-NNNN` com `len+1`.
- `POLITICA_TEXTO`: conteúdo de `dados/politica-de-uso.md`; `POLITICA_VERSAO` = valor após `versao:` na primeira linha (`2026-11-01`).

Funções puras (todas levantam `ToolError` com as mensagens exatas abaixo):

| Função | Regra | Mensagem |
|---|---|---|
| `obter_sala(id)` | id precisa existir em `SALAS` | `Sala inexistente: <id informado>` |
| `validar_pedido(sala, inicio, fim)` | ordem: sala → parse ISO-8601 → `fim > inicio` → janela → duração | ver abaixo |
| janela | `inicio` e `fim` convertidos para `-03:00` (horário de São Paulo, como diz a política; sem offset assume `-03:00`) e então entre `08:00` e `20:00` inclusive | `Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00` |
| duração | `fim - inicio <= 2h` | `Duracao acima do limite: a politica permite no maximo 2 horas` |
| intervalo | `fim <= inicio` | `Intervalo invalido: fim deve ser posterior a inicio` |
| `conflitos(sala, inicio, fim)` | reservas da sala com `r.inicio < fim and inicio < r.fim` | — |
| `alternativas(sala, inicio, fim)` | salas ≠ pedida, `capacidade >= capacidade da pedida`, sem conflito no intervalo, ordenadas por `(capacidade, id)`, no máximo 3 | — |

Ordem de validação fixada para que um pedido com vários defeitos devolva sempre a mesma mensagem (determinismo). Datas inválidas (não ISO) caem em `Intervalo invalido: ...` com o detalhe do parser; o validador nunca envia esse caso.

Nenhuma regra olha para "hoje".

## Tools

Todas registradas com `@mcp.tool()`; o SDK gera `inputSchema` (objeto JSON Schema) e `outputSchema` a partir das anotações, e devolve `structuredContent` + um `TextContent` com o mesmo JSON (indent 2). O validador compara `json.loads(texto) == structuredContent` (verificado).

### `listar_salas() -> ListaDeSalas`
- Sem parâmetros. `ListaDeSalas{salas: list[SalaOut{id, nome, capacidade, recursos}]}`.
- Descrição: "Lista todas as salas com capacidade e recursos."

### `consultar_disponibilidade(sala, inicio, fim) -> Disponibilidade`
- Aplica `validar_pedido` (mesmos erros da reserva).
- `Disponibilidade{sala, livre: bool, conflitos: list[ConflitoOut{id, inicio, fim, responsavel}]}`.
- Descrição: "Diz se uma sala esta livre no intervalo, e quais reservas conflitam."

### `reservar_sala` — spec 02.

## Erros

- **Execução** (`ToolError` dentro da tool): o SDK devolve `result.isError: true` com `content[0].text = "Error executing tool <nome>: <mensagem>"`. O prefixo é aceito pelo desafio; a mensagem após o prefixo é exata.
- **Protocolo**: tool inexistente → o SDK devolve `isError` com `Unknown tool` (aceito). `resources/read` de URI desconhecida → `ResourceNotFoundError` do SDK → `-32602` (verificado: validador 08).

## Resource

- `@mcp.resource("politica://uso", mime_type="text/markdown")` devolvendo `POLITICA_TEXTO` inteiro.
- Resposta: `contents[0] = {uri, mimeType: "text/markdown", text}`.

## Log no stderr

Um `ServerMiddleware` registrado em `MCPServer(middleware=[...])` imprime, para **todo** request que chega ao dispatcher, uma linha:

```
[mcp] method=tools/call id=4 traceparent=00-<trace-id>-<span-id>-01 name=reservar_sala
```

- `traceparent` lido de `ctx.meta["traceparent"]`, impresso só se casar com o formato W3C (`-` quando ausente ou inválido); `name` é `params.name` ou `params.uri` quando existir. Campos vindos do cliente entram escapados (sem quebra de linha) e truncados em 128 caracteres, para que um cliente não forje linhas no log.
- Para dar visibilidade ao avaliador do `tools/list` antes do primeiro `tools/call` e do par de ids inicial/retry, o middleware também marca `retry=sim` quando `params.requestState` está presente.
- Requests barrados antes do dispatcher (sem `_meta` obrigatório) são logados pelo `uvicorn` com o status 400; não passam pelo middleware. Isso é documentado no README.
- Saída via `print(..., file=sys.stderr, flush=True)`; o logging do `uvicorn` continua no padrão.

## Subida

`servidor-mcp/servidor.py` como script: lê env, exige `REQUEST_STATE_SECRET` (falha com mensagem clara se ausente ou < 32 bytes), constrói o `MCPServer` e chama `mcp.run("streamable-http", ...)`.

## Testes (`servidor-mcp/tests/`)

- `test_dominio.py`: cada mensagem de erro, ordem de validação, conflito de borda (`fim == inicio` de outra reserva não conflita), alternativas (capacidade, ordem, limite 3, exclusão da própria sala).
- `test_servidor.py`: usando `Client(mcp_server, mode="2026-07-28")` in-process: `tools/list` com as três tools e `inputSchema.type == object`; `listar_salas` texto == structured; resource lido com a versão; URI inexistente → `MCPError` `-32602`.

## Critérios de aceite cobertos

Todos do bloco "Servidor MCP" do desafio, exceto os de `reservar_sala` (spec 02).
