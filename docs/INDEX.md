# Índice de `docs/`

Glossário dos documentos deste diretório. Só o que está dentro de `docs/`.

## Guia

- [challenge.md](challenge.md) — enunciado do desafio "A Ponte" (fonte da verdade; **não alterar**).
- [duvidas.md](duvidas.md) — pontos decididos sem consulta durante a implementação, com a alternativa descartada; para revisão do autor ao final.

## Especificações (`specs/`)

| Arquivo | Assunto |
|---|---|
| [00-visao-geral.md](specs/00-visao-geral.md) | Arquitetura, stack (Python + `mcp` 2.3.0), layout, variáveis de ambiente, princípios |
| [01-servidor-mcp-base.md](specs/01-servidor-mcp-base.md) | Transporte Streamable HTTP, `_meta`, `listar_salas`, `consultar_disponibilidade`, regras da política, resource `politica://uso`, log no stderr |
| [02-servidor-mcp-mrtr.md](specs/02-servidor-mcp-mrtr.md) | `reservar_sala`, resolver/elicitation em form mode, `requestState` protegido, `-32021`, retry e recusa |
| [03-agente-host-mcp.md](specs/03-agente-host-mcp.md) | Cliente MCP do agente: descoberta, resource, `_meta`, `traceparent`, `input_required` cru |
| [04-agente-servidor-a2a.md](specs/04-agente-servidor-a2a.md) | Agent Card, JSON-RPC `SendMessage`/`GetTask`, modelo e máquina de estados da Task, erros A2A |
| [05-ponte.md](specs/05-ponte.md) | A ponte: pausa em `INPUT_REQUIRED`, guarda do `requestState` por Task, retomada, recusa |
| [06-entrega-readme.md](specs/06-entrega-readme.md) | Scripts de subida, estrutura do README, checklist de entrega |

## Atividades (`tasks/`)

- `tasks/pedding/` — pendentes, em ordem de execução (T01 → T07).
- `tasks/done/` — concluídas (movidas após QA e commit).

| Task | Título | Spec |
|---|---|---|
| T01 | Estrutura do projeto Python | 00, 06 |
| T02 | Servidor MCP: transporte, tools de consulta, resource e log | 01 |
| T03 | Servidor MCP: `reservar_sala` com MRTR | 02 |
| T04 | Agente como host MCP | 03 |
| T05 | Agente como servidor A2A | 04 |
| T06 | A ponte | 05 |
| T07 | README e validação final | 06 |
