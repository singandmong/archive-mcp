import asyncio
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_capture_and_search(tmp_path):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(__file__).resolve().parents[1] / "mcp_server.py")],
            env={**os.environ, "ARCHIVE_DATA_DIR": str(tmp_path)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {"save_link", "search_archive", "archive_status"} <= {tool.name for tool in tools.tools}
                first = await session.call_tool("save_link", {"url": "https://example.com/a", "note": "first"})
                second = await session.call_tool("save_link", {"url": "https://example.com/a?utm_source=test", "note": "second"})
                assert not first.isError and not second.isError
                assert len(list((tmp_path / "items").glob("*/*/*.md"))) == 1
                assert len(list((tmp_path / "captures").glob("*.md"))) == 2
                result = await session.call_tool("search_archive", {"query": "example.com"})
                assert not result.isError

    asyncio.run(exercise())
