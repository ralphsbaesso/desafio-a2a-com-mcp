# Spec 05 — A ponte: `input_required` ⇄ `TASK_STATE_INPUT_REQUIRED`

Cobre o requisito 5 do desafio. Arquivo: `agente/ponte.py`. É o ponto que o README precisa apontar.

## Responsabilidade

Traduzir, para uma Task A2A, o resultado cru de um `tools/call reservar_sala`:

| Resultado MCP | Efeito na Task |
|---|---|
| `CallToolResult` sem `isError` e `structuredContent.reservado == true` | `COMPLETED` + artifact `reserva` + mensagem de confirmação |
| `CallToolResult` sem `isError` e `reservado == false` (decline) | `CANCELED` + mensagem `Reserva recusada.` |
| `CallToolResult` com `isError` | `FAILED` + mensagem com o texto exato da tool |
| `InputRequiredResult` | `INPUT_REQUIRED` + mensagem `alternativas: ...` + pendência guardada |
| `MCPError` (ex.: `-32602` estado expirado/adulterado, `-32021`) | `FAILED` + mensagem `Erro MCP <code>: <message>` |

## Pendência (estado guardado por Task)

```python
@dataclass
class Pendencia:
    chave: str              # a chave única de inputRequests, ecoada em inputResponses
    request_state: str      # opaco: guardado e ecoado byte a byte, nunca decodificado
    alternativas: list[str] # o enum (ou [const]) do requestedSchema, na ordem recebida
```

- Vive só dentro de `Tarefa.pendencia`, no store em memória do agente. Não é serializada em `GetTask`, não vai para o card, não vai para o histórico nem para o artifact. O validador varre todas as respostas A2A em busca do prefixo do `requestState` (verificação 34).
- Uma Task tem no máximo uma pendência; uma nova pergunta substitui a anterior.

## Pausa (`input_required` → `INPUT_REQUIRED`)

1. Exige exatamente **uma** entrada em `inputRequests`; `params.mode == "form"`; `requestedSchema.properties.sala` com `enum` (ou `const`). Qualquer outra forma → `FAILED` com `Resposta MCP inesperada: ...` (o agente não inventa resposta).
2. Monta `alternativas` = `enum` na ordem recebida (ou `[const]`).
3. `tarefa.pendencia = Pendencia(chave, requestState, alternativas)`.
4. Estado `INPUT_REQUIRED`; mensagem de status **exatamente** `alternativas: ` + `", ".join(alternativas)` (sem prefixo, sem saudação, sem ponto final); mesma mensagem anexada ao histórico.

## Retomada (`escolha=<valor>` → retry com id novo)

1. Parseia `escolha=<valor>` (único token aceito). Texto fora desse formato ou `valor` fora de `alternativas` e diferente de `recusar` → **mantém** `INPUT_REQUIRED`, anexa a mensagem do usuário ao histórico e repete, como nova mensagem de status e de histórico, a linha `alternativas: ...`. Pendência intacta.
2. `recusar` → `inputResponses = {chave: {"action": "decline"}}`; `<id válido>` → `{chave: {"action": "accept", "content": {"sala": <id>}}}`.
3. Task → `WORKING`. Chama `host.reservar(tarefa.pedido, traceparent, input_responses, request_state)` com os **mesmos argumentos** do pedido original (guardados em `Tarefa.pedido`) e o `requestState` ecoado sem modificação. O id JSON-RPC é novo por construção (gerado pelo `ClientSession`).
4. Resultado tratado pela tabela acima. Em particular, um novo `InputRequiredResult` (a pergunta mudou no servidor porque a alternativa foi ocupada) volta a pausar a Task com a nova lista — a pendência antiga é substituída.
5. Depois de `COMPLETED`/`CANCELED`/`FAILED`, `tarefa.pendencia = None`.

## Isolamento por Task

Cada Task carrega sua própria `Pendencia`; nada é global. Duas Tasks pausadas ao mesmo tempo concluem cada uma com sua reserva (validador 33). O `asyncio.Lock` por Task (spec 04) impede duas retomadas simultâneas da mesma Task.

## Traceparent

Todos os requests MCP de uma Task, incluindo o retry, usam o trace-id guardado em `Tarefa.traceparent` (o do `SendMessage` que abriu a Task). Se a continuação vier com outro `traceparent` válido, ele substitui o guardado (a Task segue o trace de quem a retomou); se vier sem, usa o guardado.

## Onde está "a ponte" no código (para o README)

- `agente/ponte.py::pausar()` — `InputRequiredResult` vira `TASK_STATE_INPUT_REQUIRED` e guarda o `requestState`.
- `agente/ponte.py::retomar()` — lê a `Pendencia`, monta `inputResponses`, chama `host.reservar(..., request_state=...)`; o `requestState` volta ao servidor aqui.

## Testes (`agente/tests/test_ponte.py`)

Com o `HostMCP` dublê: pausa com a linha exata; retomada aceita → `COMPLETED` na sala escolhida e `request_state` ecoado idêntico; recusa → `CANCELED`; escolha inválida mantém `INPUT_REQUIRED` e repete a lista; duas Tasks com `request_state` distintos não se misturam; `GetTask` da Task pausada não contém o `request_state`; novo `InputRequiredResult` no retry re-pausa.

## Critérios de aceite cobertos

Bloco "A ponte".
