# Spec 03 — Agente como host MCP

Cobre o requisito 3 do desafio. Arquivo: `agente/host_mcp.py`.

## Papel

O agente mantém **um pool HTTP** (`httpx2.AsyncClient`) vivo durante todo o processo e abre um `mcp.Client` leve por operação sobre esse pool, na task que executa a operação. Cada chamada é um POST independente com `_meta` completo; não há sessão de protocolo. O cliente **nunca** resolve `input_required` sozinho: ele devolve o resultado cru para a ponte (spec 05).

Por que não um `Client` de longa duração (que o enunciado permite): no SDK 2.3.0 uma falha de conexão cancela o task group interno do `Client` e ele fica inutilizável até reiniciar o processo, e `__aenter__`/`__aexit__` precisam rodar na mesma task. Com um `Client` por operação, uma queda do servidor MCP afeta só aquele pedido (verificado: o pedido seguinte, após o servidor voltar, conclui). Os ids JSON-RPC continuam únicos e crescentes por processo porque cada operação reserva atomicamente uma janela de 4 ids e semeia com ela o contador do dispatcher do SDK (`_next_id`, atributo privado pinado pela versão e coberto por testes sequencial e concorrente), então o retry nunca repete o id do request inicial, mesmo com Tasks em paralelo. O `tools/call` é enviado por `session.send_request` com o tipo `CallToolResult | InputRequiredResult`, o que evita a validação de `outputSchema` do cliente (ela faria um `tools/list` extra por chamada).

## Construção

```python
# por operação, sobre o pool httpx2 do processo:
Client(
    streamable_http_client(MCP_URL, http_client=pool),   # http://127.0.0.1:7301/mcp
    mode="2026-07-28",                    # adota a revisão direto, sem initialize/discover
    client_info=Implementation(name="agente-central-de-salas", version="1.0.0"),
    elicitation_callback=_nunca_chamado,  # só para o SDK declarar a capability; nunca executa
    read_timeout_seconds=MCP_TIMEOUT,     # padrão 30 s; validado (> 0)
)
```

- `mode="2026-07-28"` faz o SDK carimbar em todo request: `_meta.io.modelcontextprotocol/protocolVersion`, `clientInfo`, `clientCapabilities` e os headers `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name` (em `tools/call` e `resources/read`). Verificado no estudo.
- O SDK declara a capability como `{"elicitation": {"form": {}, "url": {}}}`. O desafio pede "na forma `{"elicitation": {"form": {}}}`"; a forma do SDK contém a exigida e o servidor a aceita. Registrado em [duvidas.md](../duvidas.md) e no README (regra "não force o SDK a imitar o outro").
- O `elicitation_callback` levanta `RuntimeError` se for chamado: no transporte 2026 o servidor não pode iniciar request, e o agente envia o `tools/call` por `session.send_request` (sem o driver automático de MRTR do SDK), então o callback nunca roda. Se rodar, é bug.

## Operações expostas (`HostMCP`)

| Método | Chamada MCP | Observação |
|---|---|---|
| `abrir()` / `fechar()` | — | Cria/fecha o pool HTTP (idempotente); nenhum request. Timeout por request `MCP_TIMEOUT` (padrão 30 s) para que um servidor mudo não prenda o agente nem o lock de descoberta. |
| `preparar(traceparent)` | `tools/list` + `resources/read politica://uso` | Descoberta em runtime, **antes do primeiro `tools/call` do processo**, uma vez só (memoizada sob `asyncio.Lock`): guarda `tools` (lista de nomes) e `versao_politica` (primeira linha `versao: X`). Se `reservar_sala` não estiver na lista, levanta erro claro. `tools/list` vai com `cache_mode="bypass"` para garantir que chega ao servidor. |
| `reservar(args, traceparent, input_responses=None, request_state=None)` | `tools/call reservar_sala` via `client.session.send_request(CallToolRequest, TypeAdapter(CallToolResult \| InputRequiredResult))` | Chama `preparar` antes. Devolve `CallToolResult` **ou** `InputRequiredResult` sem interpretar. `MCPError` propaga; erros de transporte saem desembrulhados do `ExceptionGroup` do SDK. |

## `_meta` e traceparent

- Toda chamada recebe `meta={"traceparent": <valor>}` quando a Task tem trace. O SDK preserva chaves não reservadas do `_meta` (verificado: aparece no stderr do servidor).
- O `traceparent` propagado mantém o **trace-id** do header A2A; o span-id é novo por request MCP (`00-<trace-id>-<16 hex aleatórios>-<flags originais>`). Se o header A2A não vier ou for malformado (formato W3C, versão `ff`, ids zerados), nenhum `traceparent` é enviado e a reserva segue normalmente; a validação fica dentro do `HostMCP`, não depende do chamador.
- Ids JSON-RPC são inteiros únicos e crescentes por processo (janela de ids reservada por operação); o retry tem id diferente do inicial.

## Erros de execução

`CallToolResult.is_error == True` → a ponte termina a Task em `TASK_STATE_FAILED` com `content[0].text` (que contém a mensagem exata da tool, prefixada por `Error executing tool reservar_sala: `) no histórico. `MCPError` de protocolo (ex.: `-32602` de `requestState` expirado) → também `FAILED`, com `code` e `message` no texto.

## Script de demonstração (`agente/demo_host.py`)

Passo 6 da ordem sugerida do desafio: um script que descobre as tools, lê o resource, chama `reservar_sala` numa sala ocupada, imprime o `input_required`, responde a elicitation na mão (primeira alternativa) e imprime a reserva. Serve de teste manual e de documentação viva; não faz parte do caminho de produção.

## Testes (`agente/tests/test_host_mcp.py`)

Sobe o `MCPServer` da spec 02 in-process (importando `servidor-mcp/servidor.py` só nos testes, o que não viola a regra de dois processos na entrega) e verifica: descoberta antes da primeira chamada, versão da política, `InputRequiredResult` cru, `traceparent` recebido pelo middleware do servidor com o mesmo trace-id e span-id diferente.

## Critérios de aceite cobertos

Bloco "Agente como host MCP".
