"""Archive tools — 4 MCP tool ids.

archive.search   semantic search across all ingested sources
archive.get      fetch full record by canonical id
archive.tag      attach / remove tags on a record
archive.ingest   trigger ingestion of a new URL or file

Wave-1 worker B owns the implementations. This scaffold only declares ids.
"""

from __future__ import annotations

TOOLS: list[str] = [
    "archive.search",
    "archive.get",
    "archive.tag",
    "archive.ingest",
]


def register(mcp) -> None:  # pragma: no cover — wave-1 hook
    """Bind archive.* handlers to the FastMCP instance.

    Wave-1 worker B will populate this. Wave-0 is a placeholder so the server
    can call `tools.archive.register(mcp)` unconditionally once FastMCP wiring
    lands without re-touching server.py.
    """
    raise NotImplementedError("archive tools register() — wave-1 worker B")
