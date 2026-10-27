# T01 — Estrutura do projeto Python

Spec: [00-visao-geral](../../specs/00-visao-geral.md), [06-entrega-readme](../../specs/06-entrega-readme.md)

## Entregas

- [ ] `pyproject.toml` na raiz: `requires-python = ">=3.10"`, deps `mcp==2.3.0`, `starlette`, `uvicorn` travadas; grupo dev `pytest`, `pytest-asyncio`; config do pytest com `pythonpath = ["servidor-mcp", "agente"]`, `asyncio_mode = "auto"`, `testpaths`.
- [ ] `uv.lock` gerado; `.python-version` (3.13).
- [ ] `Makefile` com `install`, `mcp`, `agente`, `validar`, `test`, `secret`.
- [ ] `.env.example` com todas as variáveis da spec 00.
- [ ] `.gitignore` cobrindo `.venv/`, `.env`, `__pycache__/`, `.pytest_cache/`.
- [ ] Esqueleto: `servidor-mcp/servidor.py`, `agente/agente.py` (apenas `main` que imprime que vai subir), `tests/` vazios com `__init__.py`? (não: usar pytest sem pacotes, só `conftest.py` se precisar).
- [ ] Remover os `.gitkeep` de `servidor-mcp/` e `agente/` quando houver arquivos.

## Critério de pronto

`make install && make test` roda (zero testes, sem erro). `uv run python servidor-mcp/servidor.py` e `uv run python agente/agente.py` executam sem traceback.
