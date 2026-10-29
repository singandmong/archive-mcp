"""RAG tools — 3 MCP tool ids.

rag.build              build/update a vector collection from an ingest set
rag.query              query an existing collection with semantic search
rag.list_collections   enumerate available collections

Wave-1 worker C owns the implementations.
"""

from __future__ import annotations

TOOLS: list[str] = [
    "rag.build",
    "rag.query",
    "rag.list_collections",
]


def register(mcp) -> None:  # pragma: no cover — wave-1 hook
    raise NotImplementedError("rag tools register() — wave-1 worker C")
