# T07 — README e validação final

Spec: [06-entrega-readme](../../specs/06-entrega-readme.md)

## Entregas

- [x] `README.md` substituído, com as 8 seções da spec (incluindo a descrição do projeto no início e "Sobre este repositório" no fim, pedidas no task.md).
- [x] Saída completa do validador (36 PASS) colada no README, gerada com os dois processos recém-subidos.
- [x] Passos 7–13 do fluxo do avaliador executados à mão (curl) e os comandos registrados no README; passo 12 (restart do MCP entre pausa e retry) registrado.
- [x] Clone limpo em diretório temporário seguindo só o README: `make install`, subir os dois processos, `make validar`.
- [x] `git status` limpo em `dados/`, `validador/`, `exemplos/`, `docs/challenge.md`.
- [x] `docs/INDEX.md` atualizado; `docs/duvidas.md` revisado.

## Critério de pronto

Checklist de entrega da spec 06 totalmente marcado.

## Registro da conclusão

- Validador 36/36 com processos recém-subidos (saída colada no README); clone limpo em pasta temporária seguindo só o README → `make install`, `make mcp`, `make agente`, `make validar` (36/36) e `make test` (96 passed).
- Passos 3 e 7–13 do fluxo do avaliador executados; o bloco bash do README foi extraído e executado literalmente com `set -u`.
- `dados/`, `validador/`, `exemplos/` e `docs/challenge.md` sem alteração desde o starter.
- Painel de QA: 3 rodadas, todas sobre a copiabilidade do fluxo manual (variáveis extraídas automaticamente, reinício antes do passo 7, `tee` em "Como rodar").
