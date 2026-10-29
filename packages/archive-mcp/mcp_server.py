"""Local MCP interface to the archive capture engine.

The stdio transport is deliberately local; do not expose it over a network
without adding authentication and an explicit access policy.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from jobs.capture import CaptureRequest, capture_link, save_source_content
from jobs.link_extract import fetch_public_content
from jobs.archive_paths import archive_root

mcp = FastMCP("Archive MCP")


def _items() -> Path:
    return archive_root() / "items"


@mcp.tool()
def save_link(url: str, note: str = "", extract: bool = False) -> dict:
    """Save an HTTP(S) URL and note; retain a separate record for each capture."""
    request_id = f"mcp:{uuid4()}"
    result = capture_link(_items(), CaptureRequest(url, "mcp", "mcp", note, request_id))
    if extract:
        try:
            content = fetch_public_content(url)
            result["source_content_path"] = str(save_source_content(_items(), request_id, content))
            result["extraction"] = "saved"
        except (OSError, ValueError):
            result["extraction"] = "unavailable"
    return result


@mcp.tool()
def search_archive(query: str, limit: int = 20) -> list[dict[str, str]]:
    """Search existing archive items by text without changing them."""
    query = query.strip()
    if not query or not 1 <= limit <= 100:
        raise ValueError("query must be non-empty and limit must be between 1 and 100")
    results = []
    for path in sorted(_items().glob("*/*/*.md"), reverse=True):
        if query.casefold() in path.read_text(encoding="utf-8", errors="replace").casefold():
            results.append({"item_id": path.stem, "path": str(path)})
            if len(results) >= limit:
                break
    return results


@mcp.tool()
def archive_status() -> dict[str, object]:
    """Return the configured storage location and number of saved items."""
    root = _items()
    return {"items_path": str(root), "item_count": sum(1 for _ in root.glob("*/*/*.md"))}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
