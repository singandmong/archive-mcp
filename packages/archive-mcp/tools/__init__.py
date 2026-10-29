"""MCP tool registries for archive-mcp.

Each submodule exposes:
  TOOLS: list[str]    canonical tool ids
  register(mcp)       (wave-1) binds tool ids to FastMCP handler callables

Wave-0 (this commit) declares only the ids so /tools is queryable.
"""
