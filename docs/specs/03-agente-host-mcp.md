# Spec 03 — Agente como host MCP

Cobre o requisito 3 do desafio. Arquivo: `agente/host_mcp.py`.

## Papel

O agente cria **um** cliente MCP (`mcp.Client`) na subida e o mantém vivo durante todo o processo. Cada chamada é um POST independente com `_meta` completo; não há sessão de protocolo. O cliente **nunca** resolve `input_required` sozinho: ele devolve o resultado cru para a ponte (spec 05).

## Construção

```python
Client(
    MCP_URL,                              # http://127.0.0.1:7301/mcp
    mode="2026-07-28",                    # adota a revisão direto, sem initialize/discover
    client_info=Implementation(name="agente-central-de-salas", version="1.0.0"),
    elicitation_callback=_nunca_chamado,  # só para o SDK declarar a capability; nunca executa
)
```

- `mode="2026-07-28"` faz o SDK carimbar em todo request: `_meta.io.modelcontextprotocol/protocolVersion`, `clientInfo`, `clientCapabilities` e os headers `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name` (em `tools/call` e `resources/read`). Verificado no estudo.
- O SDK declara a capability como `{"elicitation": {"form": {}, "url": {}}}`. O desafio pede "na forma `{"elicitation": {"form": {}}}`"; a forma do SDK contém a exigida e o servidor a aceita. Registrado em [duvidas.md](../duvidas.md) e no README (regra "não force o SDK a imitar o outro").
- O `elicitation_callback` levanta `RuntimeError` se for chamado: no transporte 2026 o servidor não pode iniciar request, e o agente usa `allow_input_required=True`, então o callback nunca roda. Se rodar, é bug.

## Operações expostas (`HostMCP`)

| Método | Chamada MCP | Observação |
|---|---|---|
| `descobrir(traceparent)` | `tools/list` | Executado **antes do primeiro `tools/call` do processo**; guarda o conjunto de nomes. Se `reservar_sala` não estiver na lista, falha a Task com erro claro. Nunca há lista fixa no código. Chamado com `cache_mode="bypass"` para garantir que vai ao servidor. |
| `versao_politica(traceparent)` | `resources/read politica://uso` | Extrai a versão da primeira linha (`versao: X`). Lida uma vez por processo (memoizada); a leitura acontece junto da descoberta, no primeiro pedido. |
| `reservar(args, traceparent, input_responses=None, request_state=None)` | `tools/call reservar_sala` via `client.session.call_tool(..., allow_input_required=True)` | Devolve `CallToolResult` **ou** `InputRequiredResult` sem interpretar. `MCPError` propaga. |

## `_meta` e traceparent

- Toda chamada recebe `meta={"traceparent": <valor>}` quando a Task tem trace. O SDK preserva chaves não reservadas do `_meta` (verificado: aparece no stderr do servidor).
- O `traceparent` propagado mantém o **trace-id** do header A2A; o span-id é novo por request MCP (`00-<trace-id>-<16 hex aleatórios>-<flags originais>`). Se o header A2A não vier ou for malformado, nenhum `traceparent` é enviado.
- Ids JSON-RPC são gerados pelo `ClientSession` (inteiro crescente); o retry naturalmente tem id diferente do inicial.

## Erros de execução

`CallToolResult.is_error == True` → a ponte termina a Task em `TASK_STATE_FAILED` com `content[0].text` (que contém a mensagem exata da tool, prefixada por `Error executing tool reservar_sala: `) no histórico. `MCPError` de protocolo (ex.: `-32602` de `requestState` expirado) → também `FAILED`, com `code` e `message` no texto.

## Script de demonstração (`agente/demo_host.py`)

Passo 6 da ordem sugerida do desafio: um script que descobre as tools, lê o resource, chama `reservar_sala` numa sala ocupada, imprime o `input_required`, responde a elicitation na mão (primeira alternativa) e imprime a reserva. Serve de teste manual e de documentação viva; não faz parte do caminho de produção.

## Testes (`agente/tests/test_host_mcp.py`)

Sobe o `MCPServer` da spec 02 in-process (importando `servidor-mcp/servidor.py` só nos testes, o que não viola a regra de dois processos na entrega) e verifica: descoberta antes da primeira chamada, versão da política, `InputRequiredResult` cru, `traceparent` recebido pelo middleware do servidor com o mesmo trace-id e span-id diferente.

## Critérios de aceite cobertos

Bloco "Agente como host MCP".
