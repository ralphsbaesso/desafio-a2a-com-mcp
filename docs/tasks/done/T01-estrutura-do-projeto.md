# T01 — Estrutura do projeto Python

Spec: [00-visao-geral](../../specs/00-visao-geral.md), [06-entrega-readme](../../specs/06-entrega-readme.md)

## Entregas

- [x] `pyproject.toml` na raiz: `requires-python = ">=3.11"` (starlette 1.10 exige 3.11; ver duvidas.md #11), deps `mcp==2.3.0`, `starlette`, `uvicorn` travadas; grupo dev `pytest`, `pytest-asyncio`; config do pytest com `pythonpath = ["servidor-mcp", "agente"]`, `asyncio_mode = "auto"`, `testpaths`.
- [x] `uv.lock` gerado; `.python-version` (3.13).
- [x] `Makefile` com `install`, `mcp`, `agente`, `validar`, `test`, `secret`.
- [x] `.env.example` com todas as variáveis da spec 00.
- [x] `.gitignore` cobrindo `.venv/`, `.env`, `__pycache__/`, `.pytest_cache/`.
- [x] Esqueleto: `servidor-mcp/servidor.py`, `agente/agente.py` (apenas `main` que imprime que vai subir), `tests/test_smoke_<processo>.py` em cada diretório importando o entrypoint (prova o `pythonpath`). Nomes de arquivos de teste são únicos entre os dois diretórios (pytest em modo sem pacote exige).
- [x] Remover os `.gitkeep` de `servidor-mcp/` e `agente/` quando houver arquivos.

## Critério de pronto

`make install && make test` roda (zero testes, sem erro). `uv run python servidor-mcp/servidor.py` e `uv run python agente/agente.py` executam sem traceback.
