# Spec 04 — Agente como servidor A2A

Cobre o requisito 4 do desafio. Arquivos: `agente/tarefas.py`, `agente/a2a.py`, `agente/agente.py`.

## Endpoints (Starlette + uvicorn, porta `AGENTE_PORT`=7300)

| Rota | Método | Conteúdo |
|---|---|---|
| `/.well-known/agent-card.json` | GET | Agent Card v1.0, JSON |
| `/a2a` | POST | JSON-RPC 2.0: `SendMessage`, `GetTask` |

## Agent Card

Igual ao wire 07, com `supportedInterfaces[0].url = AGENTE_URL_PUBLICA`:

```json
{
  "name": "Central de Salas", "description": "Reserva salas de reuniao da Hill Valley Tech.",
  "provider": {"organization": "Hill Valley Tech", "url": "https://hillvalley.example"},
  "version": "1.0.0",
  "supportedInterfaces": [{"url": "...", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
  "capabilities": {"streaming": false, "pushNotifications": false, "extendedAgentCard": false},
  "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
  "skills": [{"id": "reservar-sala", "name": "Reservar sala", "description": "...", "tags": ["salas","agenda"],
              "inputModes": ["text/plain"], "outputModes": ["text/plain"], "examples": ["reservar sala=..."]}]
}
```
Sem `securitySchemes` (fora de escopo). Nenhum campo com `requestState`.

## Modelo de Task (`tarefas.py`)

```python
@dataclass
class Tarefa:
    id: str                 # "task-" + 12 hex
    context_id: str         # "ctx-" + 12 hex
    estado: str             # TASK_STATE_*
    mensagem_status: Mensagem | None
    historico: list[Mensagem]
    artifacts: list[Artifact]
    traceparent: str | None       # trace do SendMessage que abriu a Task
    pedido: dict | None           # argumentos do tools/call original (sala, inicio, fim, responsavel)
    pendencia: Pendencia | None   # spec 05: chave do inputRequests, requestState, enum
```

Serialização para o wire (`para_wire()`): `{id, contextId, status: {state, message?}, history, artifacts}`. O campo `pendencia` **nunca** é serializado.

`Mensagem`: `{messageId, role: ROLE_USER|ROLE_AGENT, parts: [{text}], taskId?, contextId?}`; mensagens do agente sempre levam `taskId` e `contextId`. `Artifact`: `{artifactId: "art-"+12hex, name, parts: [{text}]}`.

### Store

`dict[str, Tarefa]` em memória, protegido por um `asyncio.Lock` por Task para serializar duas continuações simultâneas da mesma Task. Não sobrevive a restart (permitido).

### Máquina de estados

```
SUBMITTED → WORKING → COMPLETED | FAILED | INPUT_REQUIRED
INPUT_REQUIRED → WORKING → COMPLETED | FAILED | CANCELED | INPUT_REQUIRED
```
- `transitar(tarefa, novo)` valida a tabela acima e levanta `EstadoTerminal` se o atual é `COMPLETED`, `CANCELED` ou `FAILED`.
- Dentro de um único `SendMessage` a Task passa por `SUBMITTED` e `WORKING` antes de terminar: as transições são aplicadas no objeto do store (um `GetTask` concorrente vê o estado corrente) e a resposta do `SendMessage` traz o estado final daquela rodada.

## JSON-RPC (`a2a.py`)

Envelope: `{"jsonrpc": "2.0", "id", "method", "params"}`. Respostas: `{"jsonrpc":"2.0","id",...,"result": {"task": {...}}}` (wire 08/10) ou `{"error": {"code","message","data?"}}`. HTTP sempre 200 para JSON-RPC válido (erro A2A vai no corpo); corpo não-JSON → `-32700`; envelope inválido → `-32600`; método desconhecido → `-32601`; params inválidos → `-32602`.

Códigos A2A usados:

| Situação | Código | Nome A2A |
|---|---|---|
| `GetTask`/`SendMessage` com `taskId` desconhecido | `-32001` | TaskNotFoundError |
| `SendMessage` referenciando Task em estado terminal | `-32004` | UnsupportedOperationError (spec A2A §3.1.1) |
| texto do pedido fora do formato fixo | `-32602` | InvalidParams |

### `SendMessage`

`params.message`: `{messageId, role, parts: [{text}], taskId?}`. Texto = concatenação dos `parts[].text`.

1. Lê `traceparent` do header HTTP (case-insensitive). Valida o formato `00-<32hex>-<16hex>-<2hex>`; inválido = ausente.
2. **Sem `taskId`**: parseia `reservar sala=<id> inicio=<iso> fim=<iso> responsavel=<nome>` (tokens `chave=valor` separados por espaço; `responsavel` recebe o resto da linha para permitir nomes com espaço). Formato inválido → erro `-32602` sem abrir Task. Cria a Task (`SUBMITTED`, histórico com a mensagem do usuário), muda para `WORKING`, chama a ponte (spec 05) e devolve a Task.
3. **Com `taskId`**: Task inexistente → `-32001`; terminal → `-32004`; em `INPUT_REQUIRED` → anexa a mensagem ao histórico e entrega à ponte com o texto `escolha=<valor>`; em `WORKING` (continuação concorrente) → `-32004`.
4. Resposta: `{"result": {"task": tarefa.para_wire()}}`.

### `GetTask`

`params.id` (o nome do campo na v1.0). Devolve `{"result": {"task": ...}}` ou `-32001`. `historyLength` é ignorado (fora de escopo).

## Conclusão com sucesso

- Artifact `name="reserva"`, uma part com o JSON **compacto e com chaves nesta ordem**: `reserva, sala, inicio, fim, responsavel, politica` (wire 10). `politica` vem da versão lida no resource (spec 03), não do `structuredContent` da tool, para provar que o agente leu o resource — os dois valores coincidem.
- Mensagem de status: `Reserva <id> confirmada na <sala>.` (wire 10), `role: ROLE_AGENT`, também anexada ao histórico.

## Falha

`isError` da tool → `TASK_STATE_FAILED`, mensagem de status e histórico com o `content[0].text` da tool (contém `Sala inexistente: sala-delorean`). Sem artifact.

## Fora de escopo (recusados explicitamente)

`SendStreamingMessage`, `CancelTask`, push notifications → `-32601`/`-32004`. Sem autenticação.

## Testes (`agente/tests/test_a2a.py`)

Com `starlette.testclient` e o `HostMCP` substituído por um dublê que devolve `CallToolResult`/`InputRequiredResult` prontos: card válido; Task nova com `id`/`contextId`; `COMPLETED` com artifact e `politica`; `GetTask`; terminal recusado com `-32004`; `taskId` desconhecido `-32001`; `FAILED` com mensagem exata; formato inválido `-32602`.

## Critérios de aceite cobertos

Bloco "Agente como servidor A2A".
