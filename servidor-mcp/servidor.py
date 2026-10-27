"""Servidor MCP da Central de Salas (esqueleto; tools chegam nas tasks T02 e T03)."""

from __future__ import annotations

import os
import sys


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "7301"))
    print(f"[mcp] servidor MCP subiria em http://{host}:{port}/mcp (ainda sem tools)", file=sys.stderr)


if __name__ == "__main__":
    main()
