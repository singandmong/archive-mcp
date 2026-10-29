"""Background-job package — RQ + Redis.

`queue.py` exposes the default Queue used by wrapper workers (B/C/D) to enqueue
long-running tasks (crawl, transcribe, ingest). The MCP request handler returns
a job id; clients poll a status endpoint (wave-1) until SUCCESS / FAILED.
"""
