# Spec 00 — Visão geral e arquitetura

Guia do desafio: [challenge.md](../challenge.md). Esta spec fixa as decisões transversais; as demais detalham cada parte.

## Objetivo

Dois processos independentes que conversam por HTTP:

```
cliente A2A (validador / curl)
        │  JSON-RPC 2.0 sobre HTTP  (porta 7300, /a2a e /.well-known/agent-card.json)
        ▼
┌──────────────────────┐          MCP Streamable HTTP 2026-07-28            ┌──────────────────┐
│ agente/              │ ───────────────────────────────────────────────▶   │ servidor-mcp/    │
│ servidor A2A por fora│   tools/list, resources/read, tools/call           │ 3 tools          │
│ host MCP por dentro  │ ◀───────────────────────────────────────────────   │ 1 resource       │
│ "a ponte"            │   complete | input_required(+requestState)         │ MRTR na reserva  │
└──────────────────────┘                                                    └──────────────────┘
                                                                              porta 7301, /mcp
```

## Stack (decisão fechada)

| Item | Escolha | Motivo |
|---|---|---|
| Linguagem | Python ≥ 3.11 (desenvolvido em 3.13; o validador continua rodando em 3.10) | Node local é 18 (< 20 exigido). Os exemplos de wire do starter foram gerados pelo SDK Python (`__main__:escolha_de_sala`, `title: listar_salasArguments`, prefixo `v1.` no requestState). |
| SDK MCP | `mcp==2.3.0` (spec `2026-07-28`) | Obrigatório. Traz `MCPServer`, `Resolve`/`Elicit` (MRTR), `RequestStateSecurity` (AES-GCM + HMAC via HKDF), transporte moderno sem sessão e cliente com `allow_input_required=True`. |
| HTTP do agente | `starlette` + `uvicorn` (já são dependências do `mcp`) | Sem dependência extra; o binding JSON-RPC do A2A é pequeno e escrito à mão para a ponte ficar visível. |
| Gestão de deps | `uv` + `pyproject.toml` + `uv.lock` | Versões travadas. |
| Testes | `pytest` + `pytest-asyncio` (dev) | Testes de domínio e de fluxo, usando o `Client` do SDK in-process. |
| LLM | nenhum | Proibido pelo desafio. |

## Layout do repositório

```
.
├── README.md                 # substituído na entrega (spec 06)
├── pyproject.toml / uv.lock  # um único projeto uv, dois entrypoints
├── Makefile                  # atalhos: install, mcp, agente, validar, test
├── .env.example              # variáveis documentadas, sem valores reais
├── dados/ validador/ exemplos/   # NÃO ALTERAR
├── servidor-mcp/
│   ├── dominio.py            # salas, reservas, política, regras e mensagens
│   ├── servidor.py           # MCPServer: tools, resource, MRTR, log stderr, main
│   └── tests/
├── agente/
│   ├── host_mcp.py           # cliente MCP (host): descoberta, resource, call_tool cru
│   ├── tarefas.py            # Task A2A: modelo, store em memória, máquina de estados
│   ├── ponte.py              # A PONTE: input_required ⇄ TASK_STATE_INPUT_REQUIRED
│   ├── servidor_a2a.py       # card, JSON-RPC SendMessage/GetTask, erros A2A
│   ├── agente.py             # app Starlette + main
│   └── tests/
└── docs/
```

Os diretórios `servidor-mcp` e `agente` não são pacotes importáveis (hífen e separação de processos). Cada entrypoint roda como script; `pytest` usa `pythonpath` apontando para os dois diretórios. Nomes de módulo não se repetem entre os dois diretórios.

## Variáveis de ambiente

| Variável | Processo | Padrão | Uso |
|---|---|---|---|
| `REQUEST_STATE_SECRET` | servidor-mcp | **obrigatória**, sem padrão | chave de integridade do `requestState` (≥ 32 bytes). O processo recusa subir sem ela. |
| `MCP_HOST` / `MCP_PORT` | servidor-mcp | `127.0.0.1` / `7301` | bind do Streamable HTTP em `/mcp` |
| `REQUEST_STATE_TTL` | servidor-mcp | `600` (s) | validade do `requestState`; aceito só entre 300 e 1800 |
| `AGENTE_HOST` / `AGENTE_PORT` | agente | `127.0.0.1` / `7300` | bind do A2A |
| `MCP_URL` | agente | `http://127.0.0.1:7301/mcp` | endpoint do servidor MCP |
| `AGENTE_URL_PUBLICA` | agente | `http://127.0.0.1:7300/a2a` | URL publicada no card |
| `MCP_TIMEOUT` | agente | `30` (s) | timeout de cada request MCP |

## Princípios que atravessam todas as specs

1. **Sem sessão de protocolo.** Cada request MCP leva `_meta` completo; cada request A2A é autossuficiente. Manter um objeto `Client` vivo é permitido e desejado.
2. **Domínio só no servidor MCP.** O agente não sabe o que é conflito, janela ou alternativa; ele traduz protocolo.
3. **`requestState` é opaco para o agente** e **hostil para o servidor** (assinado, com expiração, vinculado ao request original; o SDK faz isso).
4. **Determinismo.** Mesmo pedido, mesmo resultado. Ids de Task e de mensagem são aleatórios, mas o conteúdo das respostas não depende de relógio nem de LLM.
5. **stderr é o instrumento de depuração.** Todo request MCP é logado com método, id e `traceparent`.

## Mapa spec → critérios de aceite do desafio

| Spec | Bloco de critérios |
|---|---|
| 01 Servidor MCP base | "Servidor MCP" |
| 02 Servidor MCP MRTR | "MRTR" |
| 03 Agente host MCP | "Agente como host MCP" |
| 04 Agente servidor A2A | "Agente como servidor A2A" |
| 05 A ponte | "A ponte" |
| 06 Entrega e README | "Validação e entrega" |
