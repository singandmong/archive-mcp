# Archive MCP

**Experimental software.** Keep backups of your archive. The HTTP capture
service is intended for one trusted owner, not a multi-user deployment.

**Do not run `pip install archive-mcp`.** That package name already belongs to
an unrelated project on PyPI. Install this repository using the source
instructions below.

Archive MCP saves links and notes as Markdown, preserves a separate capture
record for each request, and identifies repeated URLs. Optional adapters and
services support additional capture surfaces and extraction.

## Local MCP interface

The MCP stdio entry point is `archive-mcp` (package `packages/archive-mcp`).
Set `ARCHIVE_DATA_DIR` to a directory you control. If unset, data is stored in
`~/.local/share/archive-mcp`. Available tools are `save_link`, `search_archive`,
and `archive_status`. The stdio process is local and is not an authenticated
network service.

## Install from source

Requires Python 3.11 or newer. After cloning this repository:

```sh
python3 -m pip install ./packages/archive-mcp
archive-mcp
```

For an MCP client, configure `archive-mcp` as a stdio server. Set
`ARCHIVE_DATA_DIR` to change the directory where Markdown files are kept.

## HTTP capture for your devices

The optional HTTP API runs separately from stdio and requires an
`ARCHIVE_MCP_HTTP_TOKEN` of at least 32 UTF-8 bytes. Supply a securely generated
random token through your existing secret manager, not a command-line argument.
Set the same `ARCHIVE_DATA_DIR` on both processes. Start the API on loopback:

```sh
uvicorn server:app --host 127.0.0.1 --port 8765
```

For remote use, put it behind a trusted HTTPS proxy accessible only to your
devices. Do not expose the loopback HTTP endpoint directly. `/health` is public;
all other routes require `Authorization: Bearer <token>`. This is a single
shared owner token: anyone who has it can write to the configured archive.

On macOS, `scripts/raycast/archive-public-clipboard.py` reads the first URL in
the clipboard and sends it to `/api/v1/captures`. Provide
`ARCHIVE_MCP_BASE_URL` and `ARCHIVE_MCP_HTTP_TOKEN` in the command's environment.
Remote addresses must use HTTPS; local loopback HTTP is accepted.

On iPhone, a Shortcut can POST JSON to the same HTTPS `/api/v1/captures`
endpoint with the bearer header. Include `url`, `source` (for example `ios`),
`source_device`, and a fresh UUID in `client_request_id`. Share the token only
with your own trusted devices. This integration requires a separately configured
HTTPS endpoint and has not been verified on every iOS version.

## Upstream projects

- [Karakeep](https://github.com/karakeep-app/karakeep) — optional bookmark UI;
  see its AGPL-3.0 license and distribution requirements.
- [Crawl4AI](https://github.com/unclecode/crawl4ai) — optional content extraction.
- [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox) — optional original
  preservation service.
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP specification.

These projects are independent; linking to them does not mean their code or
services are included. Source URLs of captured pages remain with each item.

## Privacy and deployment

Your archive may contain sensitive URLs and notes. Restrict access to its data
directory and to the HTTP token. Source content extraction is optional; it
requests the supplied public URL and can fail while the original link remains
saved.
