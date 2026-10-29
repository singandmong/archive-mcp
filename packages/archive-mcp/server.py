"""archive-mcp — FastAPI/FastMCP server skeleton.

Phase 2 worker A scaffold. Exposes:
  - GET  /health           liveness probe used by Dockerfile HEALTHCHECK
  - GET  /tools            list of registered tool ids
  - POST /test/crawl       prototype invocation of Crawl4AIWrapper
  - POST /test/cognee      prototype invocation of CogneeWrapper
  - POST /test/docling     prototype invocation of DoclingWrapper

Wrapper imports are wrapped in try/except so the server can boot even when a
wrapper backend is missing — wave-1 workers (B/C/D) fill in real implementations
incrementally without breaking startup.

The /tools registry pulls from tools.archive + tools.rag + tools.digest, which
declare 9 MCP-tool ids total (search/get/tag/ingest + build/query/list_collections
+ today/week). Wave-1 workers extend these modules with `register(mcp)` bindings
once `fastmcp` integration lands.
"""

from __future__ import annotations

import logging
import os
import hmac
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jobs.qwiki_path_policy import LegacyQwikiPathError, validate_qwiki_path
from jobs.capture import CaptureRequest, capture_link, save_source_content
from jobs.archive_paths import archive_root
from jobs.link_extract import fetch_public_content
from jobs.wiqi_item_writer import WiqiItemRequest, WiqiItemWriter
from tools import archive as archive_tools
from tools import digest as digest_tools
from tools import rag as rag_tools

logger = logging.getLogger("archive-mcp")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

QWIKI_VAULT = archive_root()
QWIKI_ITEMS = validate_qwiki_path(QWIKI_VAULT / "items", allow_container=True, label="QWIKI_ITEMS")

app = FastAPI(
    title="archive-mcp",
    version="0.1.0",
    description="archive-pipeline Phase 2 MCP server — wrapper surface for "
    "cognee, notebooklm, crawl4ai, docling, whisper, opencli.",
)


@app.middleware("http")
async def require_http_token(request: Request, call_next):
    """Protect all HTTP operations; stdio MCP does not use this server."""
    if request.url.path == "/health" and request.method == "GET":
        return await call_next(request)
    expected = os.environ.get("ARCHIVE_MCP_HTTP_TOKEN", "")
    if len(expected.encode("utf-8")) < 32:
        return JSONResponse({"detail": "HTTP authentication is not configured"}, status_code=503)
    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    ):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    # Prototype backends include unrestricted local-file and network access.
    # They are not part of the public HTTP capture interface.
    if request.url.path.startswith("/test/") or request.url.path == "/api/v1/ingest/obsidian-web-clipper":
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)


# --- Wrapper boot ----------------------------------------------------------
# Each wrapper is optional at boot. A wrapper backend that fails to import
# (missing OS library, deferred dep) leaves a `None` entry in the registry;
# the corresponding /test endpoint returns HTTP 503 until the wrapper lands.
WRAPPER_REGISTRY: dict[str, Any] = {}

for _name in ("cognee", "notebooklm", "crawl4ai", "docling", "whisper", "opencli"):
    try:
        module = __import__(f"wrappers.{_name}", fromlist=["*"])
        cls_name = "".join(p.capitalize() for p in _name.split("_")) + "Wrapper"
        # Special-case capitalization for known wrappers.
        cls_name_overrides = {
            "cognee": "CogneeWrapper",
            "notebooklm": "NotebookLMWrapper",
            "crawl4ai": "Crawl4AIWrapper",
            "docling": "DoclingWrapper",
            "whisper": "WhisperWrapper",
            "opencli": "OpenCLIWrapper",
        }
        cls = getattr(module, cls_name_overrides.get(_name, cls_name), None)
        WRAPPER_REGISTRY[_name] = cls() if cls is not None else None
    except Exception as exc:  # noqa: BLE001 — boot must not fail on wrapper errors
        logger.warning("wrapper %s unavailable at boot: %s", _name, exc)
        WRAPPER_REGISTRY[_name] = None


# --- Health & introspection ------------------------------------------------
@app.get("/health")
def health() -> dict[str, str]:
    """Liveness ping consumed by Docker HEALTHCHECK and Traefik probes."""
    return {"status": "ok"}


@app.get("/tools")
def list_tools() -> dict[str, list[str]]:
    """Return the MCP tool ids exposed by this server.

    The list is the union of archive/rag/digest tool registries. Order is
    stable (insertion order in each module's TOOLS list).
    """
    return {
        "tools": [
            *archive_tools.TOOLS,
            *rag_tools.TOOLS,
            *digest_tools.TOOLS,
        ]
    }


@app.get("/wrappers")
def wrapper_status() -> dict[str, dict[str, bool]]:
    """Report which wrapper backends initialized successfully at boot."""
    return {
        "wrappers": {name: (w is not None) for name, w in WRAPPER_REGISTRY.items()}
    }


# --- Test endpoints (wave-0 prototypes) -----------------------------------
class CrawlRequest(BaseModel):
    url: str = Field(..., description="URL to crawl via Crawl4AI")


class CogneeRequest(BaseModel):
    text: str = Field(..., description="Text to remember/store in Cognee (matches spec /goal #5 key 'text')")


class DoclingRequest(BaseModel):
    file: str = Field(..., description="Local file path for Docling (matches spec /goal #6 key 'file')")


class NotebookLMQuizRequest(BaseModel):
    notebook_id: str | None = Field(default=None, description="NotebookLM notebook id; required when sample=False")
    sample: bool = Field(default=False, description="If true, return deterministic stub flashcards (Phase 4 /goal #6 path)")


class IngestRequest(BaseModel):
    source: str = Field(..., min_length=1, description="Input surface, e.g. raycast, telegram, karakeep")
    source_device: str = Field(..., min_length=1, description="Origin device or client")
    kind: str = Field(..., description="Currently supported: url or text")
    url: str | None = Field(default=None, description="Original URL for URL captures")
    text: str | None = Field(default=None, description="Captured text for text captures")
    title: str | None = Field(default=None, description="Optional display title")
    tags: list[str] = Field(default_factory=list, description="User or client supplied tags")
    keep_original: bool = Field(default=False, description="Whether downstream jobs should preserve originals")
    captured_at: datetime | None = Field(default=None, description="Capture timestamp; defaults to now")
    client_request_id: str = Field(..., min_length=1, description="Idempotency key from the client")
    dry_run: bool = Field(default=False, description="Validate and preview the ingest without writing Q-WIKI")


class LinkCaptureRequest(BaseModel):
    url: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    source_device: str = Field(..., min_length=1)
    note: str = ""
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    keep_original: bool = False
    client_request_id: str = Field(..., min_length=1)
    dry_run: bool = False


class CaptureContentRequest(BaseModel):
    client_request_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=2000000)


class FileIngestRequest(BaseModel):
    source: str = Field(..., min_length=1, description="Input surface, e.g. telegram")
    source_device: str = Field(..., min_length=1, description="Origin device or client")
    filename: str = Field(..., min_length=1, description="Original or sanitized file name")
    title: str | None = Field(default=None, description="Optional display title")
    asset_path: str = Field(..., min_length=1, description="Relative WIQI asset path already written by the caller")
    mime_type: str | None = Field(default=None, description="MIME type reported by the caller")
    telegram_file_unique_id: str | None = Field(default=None, description="Telegram stable file id when applicable")
    text: str | None = Field(default=None, description="Optional caption or body text")
    tags: list[str] = Field(default_factory=list, description="User or client supplied tags")
    captured_at: datetime | None = Field(default=None, description="Capture timestamp; defaults to now")
    client_request_id: str = Field(..., min_length=1, description="Idempotency key from the client")
    dry_run: bool = Field(default=False, description="Validate and preview without writing WIQI")


class ObsidianWebClipperIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(default=False, description="Preview Web Clipper imports without writing Q-WIKI")


def _require_wrapper(name: str) -> Any:
    wrapper = WRAPPER_REGISTRY.get(name)
    if wrapper is None:
        raise HTTPException(
            status_code=503,
            detail=f"wrapper '{name}' not implemented yet (wave-1 worker pending)",
        )
    return wrapper


def _write_ingest(req: IngestRequest) -> dict[str, Any]:
    writer = WiqiItemWriter(QWIKI_ITEMS)
    try:
        return writer.write(
            WiqiItemRequest(
                source=req.source,
                source_device=req.source_device,
                kind=req.kind,
                url=req.url,
                text=req.text,
                title=req.title,
                tags=req.tags,
                keep_original=req.keep_original,
                captured_at=req.captured_at,
                client_request_id=req.client_request_id,
                dry_run=req.dry_run,
            )
        )
    except LegacyQwikiPathError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid capture request") from exc


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return only capture metadata, never server-side filesystem paths."""
    allowed = {"ok", "dry_run", "deduped", "item_id", "source_url", "request_id",
               "related_item_ids", "unreadable_items"}
    return {key: value for key, value in result.items() if key in allowed}


@app.post("/api/v1/ingest")
def ingest(req: IngestRequest) -> dict[str, Any]:
    """Write a URL/text capture into the canonical Q-WIKI vault."""
    try:
        return _public_result(_write_ingest(req))
    except LegacyQwikiPathError as exc:
        raise HTTPException(status_code=503, detail="Archive storage configuration error") from exc


@app.post("/api/v1/captures")
def capture(req: LinkCaptureRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        result = capture_link(QWIKI_ITEMS, CaptureRequest(
            url=req.url, source=req.source, source_device=req.source_device,
            note=req.note, title=req.title, request_id=req.client_request_id,
            dry_run=req.dry_run, tags=req.tags, keep_original=req.keep_original,
        ))
        if not req.dry_run and req.source != "telegram":
            background_tasks.add_task(_extract_capture_content, QWIKI_ITEMS, req.client_request_id, req.url)
        return _public_result(result)
    except LegacyQwikiPathError as exc:
        raise HTTPException(status_code=503, detail="Archive storage configuration error") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid capture request") from exc


def _extract_capture_content(items_root: Path, request_id: str, url: str) -> None:
    try:
        content = fetch_public_content(url)
        if content:
            save_source_content(items_root, request_id, content)
    except Exception as exc:  # noqa: BLE001 - enrichment must not block preservation
        logger.info("capture source content unavailable: %s", exc.__class__.__name__)


@app.post("/api/v1/captures/content")
def capture_content(req: CaptureContentRequest) -> dict[str, Any]:
    try:
        save_source_content(QWIKI_ITEMS, req.client_request_id, req.content)
        return {"ok": True}
    except LegacyQwikiPathError as exc:
        raise HTTPException(status_code=503, detail="Archive storage configuration error") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid capture request") from exc


@app.post("/api/v1/ingest/file")
def ingest_file(req: FileIngestRequest) -> dict[str, Any]:
    writer = WiqiItemWriter(QWIKI_ITEMS)
    try:
        return _public_result(writer.write(
            WiqiItemRequest(
                source=req.source,
                source_device=req.source_device,
                kind="file",
                text=req.text,
                title=req.title,
                tags=req.tags,
                captured_at=req.captured_at,
                client_request_id=req.client_request_id,
                dry_run=req.dry_run,
                filename=req.filename,
                asset_path=req.asset_path,
                mime_type=req.mime_type,
                telegram_file_unique_id=req.telegram_file_unique_id,
            )
        ))
    except LegacyQwikiPathError as exc:
        raise HTTPException(status_code=503, detail="Archive storage configuration error") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid capture request") from exc


def _sync_quick_capture_paths() -> Any:
    from jobs import quick_capture

    vault_root = validate_qwiki_path(QWIKI_VAULT, allow_container=True, label="QWIKI_VAULT")
    quick_capture.VAULT_ROOT = vault_root
    quick_capture.ITEMS_ROOT = validate_qwiki_path(
        QWIKI_ITEMS,
        allow_container=True,
        label="QWIKI_ITEMS",
    )
    quick_capture.IMPORT_STATE_PATH = validate_qwiki_path(
        vault_root / "_meta" / "quick_capture_imports.json",
        allow_container=True,
        label="ARCHIVE_QUICK_CAPTURE_STATE",
    )
    return quick_capture


@app.post("/api/v1/ingest/obsidian-web-clipper")
def ingest_obsidian_web_clipper(req: ObsidianWebClipperIngestRequest) -> dict[str, Any]:
    quick_capture = _sync_quick_capture_paths()
    result = quick_capture.scan_clippings(dry_run=req.dry_run)
    return {
        **result,
        "imported_count": len(result.get("imported", [])),
        "skipped_count": len(result.get("skipped", [])),
        "failed_count": len(result.get("failed", [])),
    }


@app.post("/test/crawl")
def test_crawl(req: CrawlRequest) -> dict[str, Any]:
    """Spec /goal #3: response root must carry 'markdown' so jq '.markdown | length' works."""
    wrapper = _require_wrapper("crawl4ai")
    try:
        result = wrapper.crawl(req.url)
        if isinstance(result, dict):
            return result
        return {"markdown": str(result)}
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - crawler backend outage should be visible
        raise HTTPException(
            status_code=503,
            detail=f"crawl4ai backend unavailable: {exc}",
        ) from exc


@app.post("/test/cognee")
def test_cognee(req: CogneeRequest) -> dict[str, Any]:
    """Spec /goal #5: response must include 'stored': true after storing input text."""
    wrapper = _require_wrapper("cognee")
    try:
        result = wrapper.remember(req.text)
        if isinstance(result, dict):
            return {"stored": True, **result}
        return {"stored": True, "result": result}
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/test/docling")
def test_docling(req: DoclingRequest) -> dict[str, Any]:
    """Spec /goal #6: response root must carry 'markdown' so jq '.markdown | length' works."""
    wrapper = _require_wrapper("docling")
    try:
        result = wrapper.convert(req.file)
        if isinstance(result, dict):
            return result
        return {"markdown": str(result)}
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@app.post("/test/notebooklm/quiz")
def test_notebooklm_quiz(req: NotebookLMQuizRequest) -> dict[str, Any]:
    """Phase 4 /goal #6: response must include 'flashcards' (>= 1 when sample=true)."""
    wrapper = _require_wrapper("notebooklm")
    try:
        result = wrapper.quiz(notebook_id=req.notebook_id, sample=req.sample)
        if not isinstance(result, dict):
            result = {"flashcards": [], "result": result}
        if "flashcards" not in result:
            result = {"flashcards": [], **result}
        return result
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
