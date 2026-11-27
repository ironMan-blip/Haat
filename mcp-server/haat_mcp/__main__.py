"""Run the server on its own: `python -m haat_mcp`, then point an AI app at http://127.0.0.1:8100/mcp."""
import os

from .server import mcp

mcp.run("streamable-http", host=os.environ.get("MCP_HOST", "127.0.0.1"), port=int(os.environ.get("MCP_PORT", "8100")))
