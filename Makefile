.PHONY: install mcp agente validar test secret

install:
	uv sync

mcp:
	uv run python servidor-mcp/servidor.py

agente:
	uv run python agente/agente.py

validar:
	python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301

test:
	uv run pytest -q

secret:
	@python3 -c "import secrets; print(secrets.token_hex(32))"
