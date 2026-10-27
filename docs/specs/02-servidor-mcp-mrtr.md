# Spec 02 — Servidor MCP: `reservar_sala` e o ciclo MRTR

Cobre o requisito 2 do desafio. Arquivo: `servidor-mcp/servidor.py` (usa `dominio.py` da spec 01).

## Como o SDK expressa MRTR

Não existe canal de volta no transporte 2026-07-28. O SDK Python modela a pergunta ao cliente como **resolver**: um parâmetro da tool anotado `Annotated[T, Resolve(fn)]` é preenchido rodando `fn` antes do corpo da tool. Se `fn` devolve `Elicit(mensagem, Schema)`, o framework:

1. verifica a capability do cliente (`_meta.clientCapabilities.elicitation.form`); se faltar, responde `-32021` com `data.requiredCapabilities = {"elicitation": {"form": {}}}` (HTTP 400);
2. responde `resultType: "input_required"`, `inputRequests: {"<modulo>:<fn>": {method: "elicitation/create", params: {mode: "form", message, requestedSchema}}}` e um `requestState` selado;
3. no retry, lê `params.inputResponses[<mesma chave>]` e `params.requestState`, **re-executa o resolver** e, se a pergunta renderizada for idêntica à que foi feita, injeta a resposta; o corpo da tool então roda.

O corpo da tool nunca "espera": ou recebe o valor resolvido, ou nem é chamado.

## Desenho

```python
def escolha_de_sala(sala: str, inicio: str, fim: str) -> Elicit | None:
    validar_pedido(sala, inicio, fim)            # erros de execução (spec 01)
    if not conflitos(sala, inicio, fim):
        return None                               # sem pergunta: segue para o corpo
    alts = alternativas(sala, inicio, fim)
    if not alts:
        raise ToolError("Sem alternativas disponiveis no intervalo")
    Escolha = create_model("Escolha", sala=(Literal[*alts], ...))   # schema plano, enum na ordem
    return Elicit("A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.", Escolha)

@mcp.tool()
def reservar_sala(sala, inicio, fim, responsavel,
                  escolha: Annotated[ElicitationResult[Any], Resolve(escolha_de_sala)]) -> ReservaOut:
    if not isinstance(escolha, AcceptedElicitation):   # decline / cancel
        return ReservaOut(reservado=False, motivo="recusado")
    destino = sala if escolha.data is None else escolha.data.sala
    ...cria a reserva em destino e devolve ReservaOut completo...
```

- A chave de `inputRequests` é gerada pelo SDK a partir de `módulo:qualname` do resolver (ex.: `__main__:escolha_de_sala`). O cliente ecoa a mesma chave; não fixamos o texto.
- Com duas ou mais alternativas, `Literal[...]` rende `enum`; com uma só, o pydantic rende `const` — ambos aceitos pelo desafio e pelo validador.
- O parâmetro `escolha` **não** aparece no `inputSchema` (o SDK remove parâmetros resolvidos). O `inputSchema` fica com `sala, inicio, fim, responsavel`, como no exemplo de wire 01.

## Resultado `ReservaOut`

```
reserva: str|None, reservado: bool=True, sala, inicio, fim, responsavel, politica, motivo: str|None
```
- Sucesso: `reserva="res-000N"`, `reservado=true`, `sala=<destino>`, `inicio`, `fim`, `responsavel`, `politica=POLITICA_VERSAO`, `motivo=null`.
- Recusa (`decline`/`cancel`): `reservado=false`, `motivo="recusado"`, demais `null`, `isError` falso, `resultType: complete`.

## Caminho feliz (sem conflito)

Resolver devolve `None` → corpo recebe `AcceptedElicitation(data=None)` → reserva na sala pedida. Resposta `complete` com `structuredContent` e texto, como no wire 02.

## Caminho com conflito (input_required)

Exatamente como wire 03. Alternativas = regra fechada da spec 01 (`alternativas`).

## Retry

- O corpo revalida `destino` e checa conflito de novo antes de gravar: se a alternativa foi ocupada entre a pausa e o retry, levanta `Sem alternativas disponiveis no intervalo` (defensivo; o SDK já re-pergunta nesse caso, ver abaixo).
- **Pergunta mudou entre a pausa e o retry** (ex.: a alternativa escolhida foi reservada por outro): o resolver re-renderiza um `enum` diferente, o SDK descarta a resposta antiga e devolve um **novo** `input_required`. O agente precisa tratar esse caso (spec 05).

## `requestState` — integridade, expiração, vinculação

Tudo é feito pelo `RequestStateBoundary` do SDK, configurado em:

```python
MCPServer(..., request_state_security=RequestStateSecurity(keys=[REQUEST_STATE_SECRET], ttl=REQUEST_STATE_TTL))
```

- Codec padrão: **AES-256-GCM** (AEAD: cifra + autentica) sob chave derivada por HKDF-SHA256 do segredo; token `v1.<base64url(kid+nonce+ciphertext+tag)>`. Adulteração de um caractere → `InvalidTag` → `-32602` "Invalid or expired requestState" (o motivo real vai só para o log).
- Envelope com `iat`, `exp` (TTL), `m` (método), `t` (nome da tool), `a` (digest dos `arguments`), `aud` (nome do servidor), mais o estado do resolver (`s`).
- **Argumentos adulterados no retry**: o digest `a` não bate → `-32602` "request binding". Caminho "rejeita o estado", aceito pelo desafio.
- **Reinício do processo**: nada fica em memória entre a pausa e o retry; a chave vem do ambiente, então o token continua válido após restart (desde que `REQUEST_STATE_SECRET` seja a mesma).
- `REQUEST_STATE_SECRET`: obrigatória, ≥ 32 bytes; o `AESGCMRequestStateCodec` já recusa chaves curtas. Sem valor padrão no código. README ensina a gerar com `python3 -c "import secrets; print(secrets.token_hex(32))"`.
- `REQUEST_STATE_TTL` padrão 600 s (10 min), validado para ficar entre 300 e 1800 (exigência de 5 a 30 min).

## Capability ausente

`_require_capability` do SDK dispara só quando a pergunta precisa ser feita (há conflito com alternativas) e o cliente não declarou `elicitation.form` (um `elicitation: {}` vazio conta como form; `url` sozinho não). Resposta: `-32021`, `data.requiredCapabilities`, HTTP 400 (wire 06).

## Log

O middleware da spec 01 já cobre: o avaliador vê o `tools/call` inicial e o retry com ids diferentes e `retry=sim`.

## Testes (`servidor-mcp/tests/test_mrtr.py`)

Com `Client(mcp_server, mode="2026-07-28", elicitation_callback=<nunca>)` e `client.session.call_tool(..., allow_input_required=True)`:
- conflito → `InputRequiredResult` com uma entrada, `mode=form`, `enum` na ordem esperada, `request_state` presente;
- retry `accept` → `complete`, `structuredContent.sala` = escolhida, reserva visível em `consultar_disponibilidade`;
- retry `decline` → `reservado=false`, sem `isError`;
- sem alternativa → `isError` com a mensagem exata;
- `request_state` adulterado → `MCPError` `-32602`;
- retry com `arguments` diferentes → `MCPError` `-32602`;
- sem capability (`Client` sem `elicitation_callback`) → `MCPError` `-32021` com `requiredCapabilities`;
- dois `input_required` abertos ao mesmo tempo → cada retry conclui a sua.

## Critérios de aceite cobertos

Todos do bloco "MRTR". O item "retry válido após reinício" é verificado manualmente no fluxo do avaliador (passo 12) e documentado no README.
