"""Agente Central de Salas: servidor A2A por fora, host MCP por dentro (esqueleto; T04 a T06)."""

from __future__ import annotations

import os
import sys


def main() -> None:
    host = os.environ.get("AGENTE_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENTE_PORT", "7300"))
    print(f"[agente] agente subiria em http://{host}:{port}/a2a (ainda sem rotas)", file=sys.stderr)


if __name__ == "__main__":
    main()
