from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from jobs.qwiki_path_policy import validate_qwiki_path


class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


@dataclass
class WiqiItemRequest:
    source: str
    source_device: str
    kind: str
    url: str | None = None
    text: str | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    keep_original: bool = False
    captured_at: datetime | None = None
    client_request_id: str | None = None
    dry_run: bool = False
    filename: str | None = None
    asset_path: str | None = None
    mime_type: str | None = None
    karakeep_id: str | None = None
    telegram_file_unique_id: str | None = None


class WiqiItemWriter:
    def __init__(self, items_root: str | Path) -> None:
        self.items_root = Path(items_root)

    def write(self, req: WiqiItemRequest) -> dict[str, Any]:
        self._validate_request(req, req.kind.lower().strip())
        items_root = validate_qwiki_path(self.items_root, allow_container=True, label="QWIKI_ITEMS")

        existing = self._existing_ingest(items_root, req.client_request_id)
        if existing:
            return {"ok": True, "dry_run": req.dry_run, "deduped": True, **existing}

        target, markdown, _frontmatter = self.render(req)
        source_url = req.url or ""
        result = {
            "ok": True,
            "dry_run": req.dry_run,
            "deduped": False,
            "item_id": target.stem,
            "qwiki_path": str(target),
            "source_url": source_url,
        }
        if req.dry_run:
            return result

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        return result

    def render(self, req: WiqiItemRequest) -> tuple[Path, str, dict[str, Any]]:
        kind = req.kind.lower().strip()
        self._validate_request(req, kind)
        items_root = validate_qwiki_path(self.items_root, allow_container=True, label="QWIKI_ITEMS")
        captured_at = _normalize_datetime(req.captured_at)
        title = _clean_scalar(req.title or req.url or req.filename or (req.text or "")[:80] or "Untitled")
        hash_input = req.url or req.text or req.asset_path or req.filename or req.client_request_id or title
        short_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:8]
        item_id = f"{captured_at.strftime('%Y%m%d')}-{_slug(title)}-{short_hash}"
        target = items_root / captured_at.strftime("%Y") / captured_at.strftime("%m") / f"{item_id}.md"
        target = _unique_target(target)

        tags = _dedupe_tags([*req.tags, req.source])
        if req.keep_original and "keep-original" not in tags:
            tags.append("keep-original")

        source_url = req.url or ""
        frontmatter: dict[str, Any] = {
            "id": target.stem,
            "source": _clean_scalar(req.source),
            "source_device": _clean_scalar(req.source_device),
            "source_url": _clean_scalar(source_url),
            "kind": kind,
            "title": title,
            "date_captured": captured_at.isoformat(),
            "keep_original": req.keep_original,
            "tags": tags,
        }
        if req.client_request_id:
            frontmatter["client_request_id"] = _clean_scalar(req.client_request_id)
        if req.karakeep_id:
            frontmatter["karakeep_id"] = _clean_scalar(req.karakeep_id)
        if req.telegram_file_unique_id:
            frontmatter["telegram_file_unique_id"] = _clean_scalar(req.telegram_file_unique_id)
        if kind == "file":
            frontmatter.update(
                {
                    "source_type": "file",
                    "filename": _clean_scalar(req.filename or ""),
                    "asset_path": _clean_scalar(req.asset_path or ""),
                    "mime_type": _clean_scalar(req.mime_type or ""),
                }
            )

        markdown = render_markdown(frontmatter, self._body(req, kind, source_url), title)
        return target, markdown, frontmatter

    def read(self, path: str | Path) -> dict[str, Any]:
        item_path = validate_qwiki_path(path, allow_container=True, label="QWIKI_ITEM")
        markdown = item_path.read_text(encoding="utf-8")
        frontmatter, body = parse_markdown(markdown)
        return {"frontmatter": frontmatter, "body": body, "path": str(item_path)}

    def _existing_ingest(self, items_root: Path, client_request_id: str | None) -> dict[str, str] | None:
        if not client_request_id or not items_root.exists():
            return None
        needle = f"client_request_id: {client_request_id}"
        for path in sorted(items_root.glob("*/*/*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(errors="replace")
            if needle in text:
                return {"item_id": path.stem, "qwiki_path": str(path)}
        return None

    def _body(self, req: WiqiItemRequest, kind: str, source_url: str) -> str:
        parts: list[str] = []
        if source_url:
            parts.append(f"원본 링크: {source_url}")
        if kind == "file":
            if req.asset_path:
                parts.append(f"원본 파일: [[{req.asset_path}]]")
            if req.filename:
                parts.append(f"파일명: `{req.filename}`")
            if req.mime_type:
                parts.append(f"MIME type: `{req.mime_type}`")
            if req.mime_type and req.mime_type.startswith("image/") and req.asset_path:
                parts.append(f"![[{req.asset_path}]]")
        if req.text and req.text.strip():
            parts.append(req.text.strip())
        return "\n\n".join(parts) or f"[no content - captured from {req.source}]"

    def _validate_request(self, req: WiqiItemRequest, kind: str) -> None:
        if kind not in {"url", "text", "file"}:
            raise ValueError("kind must be 'url', 'text', or 'file'")
        if not req.source.strip():
            raise ValueError("source is required")
        if not req.source_device.strip():
            raise ValueError("source_device is required")
        if kind == "url" and not req.url:
            raise ValueError("url is required when kind='url'")
        if kind == "text" and not req.text:
            raise ValueError("text is required when kind='text'")
        if kind == "file":
            if not req.filename:
                raise ValueError("filename is required when kind='file'")
            if not req.asset_path:
                raise ValueError("asset_path is required when kind='file'")
            _validate_relative_asset_path(req.asset_path)


def render_markdown(frontmatter: dict[str, Any], body: str, title: str) -> str:
    fm_text = yaml.dump(
        frontmatter,
        Dumper=_IndentedSafeDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return f"---\n{fm_text}---\n\n# {title}\n\n{body}\n"


def parse_markdown(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown
    raw = markdown[4:end]
    body = markdown[end + 5 :].lstrip("\n")
    data = yaml.safe_load(raw) or {}
    return (data if isinstance(data, dict) else {}), body


def _normalize_datetime(value: datetime | None) -> datetime:
    captured_at = value or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    return captured_at


def _slug(text: str, max_len: int = 48) -> str:
    text = text.lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].strip("-") or "capture")


def _clean_scalar(value: str) -> str:
    return str(value).replace("\n", " ").strip()


def _dedupe_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        for part in re.split(r"[,\s]+", str(value)):
            tag = part.strip().lstrip("#")
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _unique_target(base: Path) -> Path:
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    for i in range(2, 1000):
        candidate = base.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate unique WIQI item path for {base}")


def _validate_relative_asset_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("asset_path must be relative and stay inside the WIQI vault")
