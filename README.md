# A Ponte: um agente A2A com um servidor MCP por dentro

Central de Salas da Hill Valley Tech: dois processos Python que se falam por HTTP.

- **`servidor-mcp/`** é um servidor **MCP** (Streamable HTTP, revisão `2026-07-28`, SDK `mcp` 2.3.0) que expõe as capacidades do domínio: as tools `listar_salas`, `consultar_disponibilidade` e `reservar_sala`, e o resource `politica://uso`. Quando a sala pedida está ocupada, `reservar_sala` não falha nem decide sozinha: devolve `input_required` com uma elicitation em form mode (as salas alternativas) e um `requestState` selado. O ciclo completo de MRTR (multi-round-trip request) é fechado no retry, com `inputResponses` e o `requestState` de volta.
- **`agente/`** é um agente sem LLM que é **host MCP por dentro** (descobre as tools em runtime, lê o resource, chama `reservar_sala`) e **servidor A2A v1.0 por fora** (Agent Card no well-known URI, `SendMessage` e `GetTask` em JSON-RPC 2.0). Ele interpreta um pedido em formato fixo e decide por regra.
- **A ponte** entre os dois mecanismos de estado está em `agente/ponte.py`: o `input_required` do MCP vira `TASK_STATE_INPUT_REQUIRED` na Task A2A, o `requestState` fica guardado ligado àquela Task (opaco, nunca aberto nem exposto), e a resposta do cliente (`escolha=<sala>`) vira o retry do `tools/call` original com id novo.

```
cliente A2A (validador / curl / outro agente)
        │  JSON-RPC 2.0 sobre HTTP  (porta 7300: /a2a e /.well-known/agent-card.json)
        ▼
┌──────────────────────┐          MCP Streamable HTTP 2026-07-28            ┌──────────────────┐
│ agente/              │ ───────────────────────────────────────────────▶   │ servidor-mcp/    │
│ servidor A2A por fora│   tools/list, resources/read, tools/call           │ 3 tools          │
│ host MCP por dentro  │ ◀───────────────────────────────────────────────   │ 1 resource       │
│ ponte.py             │   complete | input_required (+ requestState)       │ MRTR na reserva  │
└──────────────────────┘                                                    └──────────────────┘
                                                                              porta 7301, /mcp
```

Stack: Python ≥ 3.11, `mcp==2.3.0`, `starlette`, `uvicorn`, gerenciados com `uv` (versões travadas em `pyproject.toml` e `uv.lock`). Nenhum SDK de LLM. O domínio (salas, reservas, política) vive só no servidor MCP; o agente traduz protocolo.

## Como rodar

Pré-requisitos: [`uv`](https://docs.astral.sh/uv/) (ele baixa o Python 3.13 se não houver um ≥ 3.11), `python3` ≥ 3.10 para o validador (stdlib apenas), `make` opcional.

```bash
git clone https://github.com/ralphsbaesso/desafio-a2a-com-mcp.git
cd desafio-a2a-com-mcp
make install                      # uv sync: cria .venv com as versões do uv.lock
```

Terminal 1, o servidor MCP (deixe o stderr visível). Só ele usa a chave de integridade do `requestState`: gere uma com pelo menos 32 bytes, nunca a commite, e use o **mesmo** valor se reiniciar o servidor (um `requestState` emitido antes do reinício só continua válido com a mesma chave):

```bash
export REQUEST_STATE_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
make mcp 2>&1 | tee -a /tmp/mcp.log   # = uv run python servidor-mcp/servidor.py; o tee guarda o stderr para os passos 5 e 6 do avaliador
```

Para reiniciar o servidor (passo 12 do avaliador), use Ctrl-C e `make mcp` de novo **neste mesmo terminal**, onde o `export` continua valendo; num terminal novo, reexporte o mesmo valor.

Terminal 2, o agente:

```bash
make agente                       # = uv run python agente/agente.py
```

Terminal 3, o validador do starter (sempre com os dois processos recém-subidos, porque as reservas ficam em memória):

```bash
make validar                      # = python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

Sem `make`: os comandos equivalentes estão à direita de cada alvo. Variáveis de ambiente opcionais (padrões entre parênteses): `MCP_HOST` (`127.0.0.1`), `MCP_PORT` (`7301`), `REQUEST_STATE_TTL` (`600`, aceito entre 300 e 1800), `AGENTE_HOST` (`127.0.0.1`), `AGENTE_PORT` (`7300`), `MCP_URL` (`http://127.0.0.1:7301/mcp`), `AGENTE_URL_PUBLICA` (`http://127.0.0.1:7300/a2a`, a URL publicada no card), `MCP_TIMEOUT` (`30` s por request MCP). Veja `.env.example`.

## Onde a ponte acontece

A ponte está inteira em [`agente/ponte.py`](agente/ponte.py), em duas funções:

- **`pausar()`** recebe o `InputRequiredResult` cru que o host MCP devolveu (o agente chama `tools/call` por `session.send_request`, sem callback de elicitation, justamente para enxergar o `input_required` sem o SDK responder sozinho). Ela valida que veio exatamente uma elicitation em form mode com `properties.sala.enum` (ou `const`), guarda numa `Pendencia` da Task a chave do `inputRequests`, o `requestState` e as alternativas, responde a linha `alternativas: <ids separados por virgula e espaco>` e coloca a Task em `TASK_STATE_INPUT_REQUIRED`. A `Pendencia` fica em `Tarefa.pendencia` ([`agente/tarefas.py`](agente/tarefas.py)) e nunca é serializada: `GetTask`, `SendMessage` e o card não a mostram.
- **`retomar()`** é chamada quando chega um `SendMessage` com `taskId` de uma Task pausada. Ela traduz `escolha=<id>` em `inputResponses = {<mesma chave>: {"action": "accept", "content": {"sala": <id>}}}` e `escolha=recusar` em `{"action": "decline"}`, e chama `host.reservar(tarefa.pedido, ..., input_responses=..., request_state=pendencia.request_state)`: é aqui que o `requestState` volta para o servidor, ecoado byte a byte, junto com os **mesmos argumentos** do pedido original. O id JSON-RPC do retry é novo (o `HostMCP`, em [`agente/host_mcp.py`](agente/host_mcp.py), reserva uma janela de ids por operação), e no stderr do servidor MCP o retry aparece com `retry=sim`. Uma escolha fora do `enum` mantém a Task pausada e repete a lista; um novo `input_required` no retry (a alternativa foi ocupada nesse meio-tempo) volta a pausar com a lista nova.

O resultado do retry passa pela mesma tabela de tradução de qualquer `tools/call` (`tratar_resultado`): reserva → `COMPLETED` com o artifact `reserva`; `reservado: false` (decline) → `CANCELED`; `isError` → `FAILED` com o texto exato da tool no histórico.

## Decisões técnicas

- **Proteção do `requestState`.** O servidor usa o `RequestStateSecurity` do SDK (`servidor-mcp/servidor.py`): o estado do resolver é cifrado e autenticado com **AES-256-GCM**, sob uma chave derivada por HKDF-SHA256 da variável `REQUEST_STATE_SECRET` (obrigatória, ≥ 32 bytes, nunca no código; o processo recusa subir sem ela). O envelope selado carrega emissão, expiração, método, nome da tool, o digest dos `arguments` e a audiência. Um caractere trocado dá `-32602` ("Invalid or expired requestState"); argumentos diferentes no retry também (`request binding`). Nada fica em memória entre a pausa e o retry, então o retry funciona depois de reiniciar o servidor, desde que o segredo seja o mesmo.
- **Validade.** `REQUEST_STATE_TTL`, padrão **600 s** (10 min), aceito entre 300 e 1800 s.
- **Estado das Tasks.** Em memória no agente (`agente/tarefas.py`), um dicionário por processo com um `asyncio.Lock` por Task; não sobrevive a restart (permitido). A pendência do MRTR é por Task, então duas Tasks pausadas ao mesmo tempo concluem cada uma com o seu `requestState`. Limites: Task pausada sem resposta expira em 30 min (`FAILED`), no máximo 10 escolhas inválidas e 5 pausas por Task, teto de 10 000 Tasks (as terminais mais antigas são expurgadas; se só houver Tasks vivas o agente recusa com erro), corpo do POST até 64 KB.
- **MRTR no servidor.** `reservar_sala` tem um parâmetro resolvido (`Annotated[ElicitationResult, Resolve(escolha_de_sala)]`): o resolver valida o pedido, e com conflito devolve `Elicit` com um schema plano cujo `sala` é `Literal[alternativas]` (duas ou mais viram `enum`; uma só vira `const`). O SDK batalha o resto: `-32021` quando o cliente não declarou `elicitation.form`, o `input_required`, o selo, o retry. A checagem de conflito e a gravação da reserva são atômicas (lock no domínio), porque o SDK executa tools síncronas em thread.
- **Host MCP no agente.** Um pool HTTP por processo e um `mcp.Client` leve por operação (modo `2026-07-28`, sem handshake). Motivo: no SDK 2.3.0 o `Client` de longa duração fica inutilizável depois de uma falha de conexão; com um cliente por operação, uma queda do servidor MCP afeta só aquele pedido. Os ids JSON-RPC continuam únicos e crescentes por processo (o `HostMCP` semeia o contador do dispatcher do SDK, atributo privado, pinado na versão e coberto por teste). A descoberta (`tools/list` + `resources/read politica://uso`) acontece uma vez por processo, antes do primeiro `tools/call`.
- **Capability de elicitation.** O SDK Python declara `{"elicitation": {"form": {}, "url": {}}}`; o enunciado escreve `{"elicitation": {"form": {}}}`. A forma do SDK contém a exigida e o servidor a aceita; não forçamos o SDK a imitar outra grafia.
- **`traceparent`.** O header do `SendMessage` é validado (formato W3C, sem versão `ff` nem ids zerados) e propagado em `_meta.traceparent` de todos os requests MCP da Task, com o mesmo trace-id e um span-id novo por request. Header ausente ou inválido: sem `traceparent`, e a reserva segue.
- **Log.** O servidor MCP registra no stderr cada request que chega ao dispatcher (`[mcp] method=... id=... traceparent=... name=... [retry=sim]`); requests barrados antes dele (sem `_meta` obrigatório) aparecem só na linha de acesso do uvicorn com HTTP 400. O agente registra cada transição terminal (`[agente] task=... estado=... traceparent=... motivo=...`). Valores vindos do cliente entram escapados e truncados.
- **Mensagens de erro.** Erros de execução da tool chegam ao cliente A2A com o texto exato da tool (prefixado por `Error executing tool reservar_sala: `, prefixo aceito pelo enunciado). Erros de transporte e de protocolo viram mensagens genéricas; o detalhe vai só ao stderr.
- **Limitações conhecidas.** Sem idempotência por `messageId` (um retry de rede abre outra Task); um erro de transporte durante o retry termina a Task em `FAILED`; a janela de uso é avaliada no fuso `-03:00` (datas em outro offset são convertidas; sem offset assume `-03:00`); a política é lida uma vez por processo. Todas as decisões tomadas sem consulta, com a alternativa descartada, estão em [`docs/duvidas.md`](docs/duvidas.md).

## Saída do validador

Última execução, com os dois processos recém-subidos (código de saída 0):

```
trace-id desta execucao: 27f988771333d190366f9b036200e43c
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```

## Fluxo manual do avaliador

Comandos prontos para os passos 3 e 7 a 13 do enunciado, em `bash`, a partir da raiz do repositório e **todos no mesmo shell** (o Terminal 3): os passos seguintes reaproveitam as funções e variáveis dos anteriores. Os corpos vêm de `exemplos/wire/`. **Antes do passo 7, pare (Ctrl-C) e suba de novo os terminais 1 e 2**, com o mesmo `REQUEST_STATE_SECRET`: as reservas ficam em memória e o validador acabou de ocupar as mesmas salas. Os resultados da tabela valem para processos recém-subidos e para os passos executados nesta ordem (o passo 8 reserva a `sala-mirante`, por isso no passo 9 a lista já tem só a `sala-fusca`).

```bash
A=http://localhost:7300/a2a; M=http://localhost:7301/mcp
JSON=(-H 'Content-Type: application/json')
id_da_task() { python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["task"]["id"])'; }
continuar() { curl -s "${JSON[@]}" -d "{\"jsonrpc\":\"2.0\",\"id\":9,\"method\":\"SendMessage\",\"params\":{\"message\":{\"messageId\":\"msg-$RANDOM\",\"role\":\"ROLE_USER\",\"parts\":[{\"text\":\"$2\"}],\"taskId\":\"$1\"}}}" $A; }

# 3. Agent Card
curl -s http://localhost:7300/.well-known/agent-card.json

# 7. SendMessage de sala ocupada (corpo do wire 08): TASK_STATE_INPUT_REQUIRED com "alternativas: sala-fusca, sala-mirante"
BODY=$(python3 -c "import json; print(json.dumps(json.load(open('exemplos/wire/08-a2a-send-message.json'))['request']['body']))")
R=$(curl -s "${JSON[@]}" -H 'traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01' -d "$BODY" $A); echo "$R"
TID=$(echo "$R" | id_da_task)

# 8. Continuação e GetTask: COMPLETED com o artifact "reserva" apontando para sala-mirante e com "politica"
continuar "$TID" escolha=sala-mirante
curl -s "${JSON[@]}" -d "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"GetTask\",\"params\":{\"id\":\"$TID\"}}" $A

# 9. De novo o passo 7 (a lista agora é "alternativas: sala-fusca"), depois recusar: TASK_STATE_CANCELED
TID2=$(curl -s "${JSON[@]}" -d "$BODY" $A | id_da_task)
continuar "$TID2" escolha=recusar

# 10. Sala inexistente: TASK_STATE_FAILED com "Sala inexistente: sala-inexistente" no histórico
curl -s "${JSON[@]}" -d '{"jsonrpc":"2.0","id":6,"method":"SendMessage","params":{"message":{"messageId":"msg-4","role":"ROLE_USER","parts":[{"text":"reservar sala=sala-inexistente inicio=2026-11-03T09:00:00-03:00 fim=2026-11-03T10:00:00-03:00 responsavel=Doc"}]}}}' $A

# 11. Direto no MCP: conflito (wire 03) devolve o requestState; o retry (wire 04) com um caractere trocado recebe HTTP 400 e -32602
H=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: tools/call' -H 'Mcp-Name: reservar_sala')
B3=$(python3 -c "import json; print(json.dumps(json.load(open('exemplos/wire/03-tools-call-conflito-input-required.json'))['request']['body']))")
R=$(curl -s "${H[@]}" -d "$B3" $M); echo "$R"
RS=$(echo "$R" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["requestState"])')
KEY=$(echo "$R" | python3 -c 'import sys,json; print(list(json.load(sys.stdin)["result"]["inputRequests"])[0])')
retry() { python3 -c "import json; b=json.load(open('exemplos/wire/04-tools-call-retry.json'))['request']['body']; b['params']['requestState']='$1'; b['params']['inputResponses']={'$KEY': {'action': 'accept', 'content': {'sala': 'sala-fusca'}}}; print(json.dumps(b))"; }
curl -s -w "\nHTTP %{http_code}\n" "${H[@]}" -d "$(retry "${RS:0:-6}AAAAAA")" $M

# 12. Reinicie o servidor MCP (Ctrl-C e `make mcp` de novo, com o mesmo REQUEST_STATE_SECRET) e envie o retry intacto UMA vez: HTTP 200, resultType complete, res-0003 em sala-fusca
curl -s -w "\nHTTP %{http_code}\n" "${H[@]}" -d "$(retry "$RS")" $M

# 13. Corpo do wire 06 (sem a capability de elicitation): HTTP 400, -32021 com data.requiredCapabilities
B6=$(python3 -c "import json; print(json.dumps(json.load(open('exemplos/wire/06-erro-32021-sem-elicitation.json'))['request']['body']))")
curl -s -w "\nHTTP %{http_code}\n" "${H[@]}" -d "$B6" $M
```

Resultados obtidos nesta entrega (processos recém-subidos antes do passo 7):

| Passo | Resultado |
|---|---|
| 3 | `supportedInterfaces[0] = {url: http://127.0.0.1:7300/a2a, protocolBinding: JSONRPC, protocolVersion: 1.0}`, skill `reservar-sala` |
| 7 | `TASK_STATE_INPUT_REQUIRED`, mensagem `alternativas: sala-fusca, sala-mirante` |
| 8 | `TASK_STATE_COMPLETED`; `GetTask` traz o artifact `reserva` = `{"reserva": "res-0003", "sala": "sala-mirante", ..., "politica": "2026-11-01"}` |
| 9 | pausa com `alternativas: sala-fusca`; `escolha=recusar` → `TASK_STATE_CANCELED` |
| 10 | `TASK_STATE_FAILED`, mensagem `Error executing tool reservar_sala: Sala inexistente: sala-inexistente` |
| 11 | `input_required`, chave `__main__:escolha_de_sala`; adulterado → HTTP 400, `{"code": -32602, "message": "Invalid or expired requestState"}` |
| 12 | após reiniciar o servidor MCP: HTTP 200, `{"reserva": "res-0003", "reservado": true, "sala": "sala-fusca", ..., "politica": "2026-11-01"}` |
| 13 | HTTP 400, `-32021`, `data.requiredCapabilities = {"elicitation": {"form": {}}}` |

Passos 5 e 6 (stderr do servidor MCP durante o validador): com o servidor subido via `tee` como em "Como rodar", rode `grep -E "tools/list|retry=sim|<trace-id impresso pelo validador>" /tmp/mcp.log` depois do validador. O `tools/list` do agente (id 1) antecede o primeiro `tools/call`; todas as linhas do agente levam o trace-id do validador com um span-id novo em cada uma; o par de uma reserva pausada aparece como `tools/call id=<n> ... name=reservar_sala` seguido de `tools/call id=<m> ... name=reservar_sala retry=sim`, com `m ≠ n` (nesta entrega, ids 9 e 13).

Para ver o ciclo MRTR sem o A2A, com o servidor MCP no ar: `uv run python agente/demo_host.py` (descobre as tools, lê a política, pausa numa sala ocupada e responde a elicitation na mão). Se algum `id_da_task` falhar com `KeyError`, a resposta não trouxe uma Task: confira se os dois processos estão no ar e recém-subidos.

## Testes

```bash
make test        # = uv run pytest -q
```

A suíte cobre domínio e política, o servidor MCP e o ciclo MRTR (in-process, com o `Client` do SDK), o host MCP (descoberta, `traceparent`, ids, resiliência a servidor fora), o servidor A2A e a ponte (com um dublê do host). Os testes dos dois diretórios rodam juntos a partir da raiz.

## Documentação

- [`docs/INDEX.md`](docs/INDEX.md): índice das especificações (`docs/specs/`), das atividades (`docs/tasks/`) e das decisões em aberto (`docs/duvidas.md`).
- [`docs/challenge.md`](docs/challenge.md): o enunciado do desafio, intocado.

## Sobre este repositório

Este projeto é a entrega de um **desafio de curso**: o desafio inicial "A Ponte: um agente A2A com MCP por dentro", do curso de MCP e A2A do MBA em Engenharia de Software com IA (Full Cycle). O repositório é um fork do starter em https://github.com/devfullcycle/desafio-a2a-com-mcp; `dados/`, `validador/` e `exemplos/` pertencem ao starter e não foram alterados. O objetivo é didático: exercitar, de ponta a ponta, como dois protocolos sem sessão (MCP com `requestState` e A2A com Task) costuram estado explicitamente dentro de um agente.
