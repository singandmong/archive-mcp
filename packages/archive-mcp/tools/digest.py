"""Digest tools — 2 MCP tool ids.

digest.today   today's intake / activity summary
digest.week    rolling 7-day summary

Wave-1 worker C owns the implementations (shares scheduler with rag.*).
"""

from __future__ import annotations

TOOLS: list[str] = [
    "digest.today",
    "digest.week",
]


def register(mcp) -> None:  # pragma: no cover — wave-1 hook
    raise NotImplementedError("digest tools register() — wave-1 worker C")
