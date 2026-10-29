# archive-mcp

Local-first link capture with a stdio MCP and an optional authenticated HTTP
capture API. The MCP offers `save_link`, `search_archive` and `archive_status`.
The HTTP API is intended for one trusted user, not as a multi-tenant service.

## Dev

The legacy HTTP server is separate from the local stdio MCP. It requires an
`ARCHIVE_MCP_HTTP_TOKEN` of at least 32 UTF-8 bytes and a matching `Authorization:
Bearer <token>` header for every endpoint except `GET /health`. Without a
token it returns 503. Create a random token, store it as a secret, and provide
the same value to HTTP clients (including the Raycast configuration file and
Telegram adapter). Do not place credentials in source or issue them over an
untrusted cleartext network. Clients reject token-bearing remote plain HTTP;
remote MacBook capture needs a trusted HTTPS endpoint (including a correctly
configured Tailscale HTTPS endpoint), not a raw `http://` Tailscale address.
Restarting an existing HTTP deployment without
configuring its clients will stop link capture; migrate both sides together.
The stdio MCP does not need this token.
Both transports use `ARCHIVE_DATA_DIR` as their data directory. For an existing
runtime, `QWIKI_VAULT` is accepted when `ARCHIVE_DATA_DIR` is unset; setting
both to different locations is rejected. When neither is set, both use
`~/.local/share/archive-mcp`. Set the same directory on both processes when
using MCP search alongside HTTP capture.
Prototype `/test/*` and Obsidian Web Clipper import endpoints are disabled in
the public HTTP capture service because they expose broad backend or local
document access. HTTP capture responses do not include local filesystem paths.

```bash
pip install -e .[dev]
uvicorn server:app --reload --port 8765
pytest -x
```

## HTTP endpoints

| Method | Path        | Purpose                                      |
| ------ | ----------- | -------------------------------------------- |
| GET    | /health     | Liveness ping (used by Docker HEALTHCHECK)   |
| POST   | /api/v1/captures | Save a link and its capture context |
| POST   | /api/v1/ingest   | Save a URL or text item |
