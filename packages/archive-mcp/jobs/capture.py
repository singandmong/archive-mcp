"""Preserve link captures and their individual context without rewriting older items."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

import yaml

from jobs.qwiki_path_policy import validate_qwiki_path
from jobs.wiqi_item_writer import WiqiItemRequest, WiqiItemWriter, parse_markdown


@dataclass(frozen=True)
class CaptureRequest:
    url: str
    source_device: str
    source: str
    note: str
    request_id: str
    title: str | None = None
    dry_run: bool = False
    tags: list[str] = field(default_factory=list)
    keep_original: bool = False


def link_identity(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
        raise ValueError('an http(s) link is required')
    tracking = {'fbclid', 'gclid', 'dclid', 'msclkid'}
    query = '&'.join(part for part in parts.query.split('&') if part and not (
        unquote_plus(part.partition('=')[0]).lower().startswith('utm_') or
        unquote_plus(part.partition('=')[0]).lower() in tracking
    ))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, parts.fragment))


def _matches(items_root: Path, identity: str) -> tuple[list[Path], int]:
    matches = []
    unreadable = 0
    for path in sorted(items_root.glob('*/*/*.md')):
        text = path.read_text(encoding='utf-8', errors='replace')
        try:
            frontmatter, _ = parse_markdown(text)
            original = frontmatter.get('source_url')
        except yaml.YAMLError:
            header = text.split('\n---\n', 1)[0] if text.startswith('---\n') else ''
            candidates = re.findall(r'^source_url:[ \t]*(.+)$', header, flags=re.MULTILINE)
            original = None
            if len(candidates) == 1:
                try:
                    original = yaml.safe_load(candidates[0])
                except yaml.YAMLError:
                    original = None
                if not isinstance(original, str):
                    # A plain URL ending in ':' is invalid YAML, but its exact
                    # one-token value is still unambiguous. Never guess a URL
                    # from quoted, multiline, commented, or whitespace text.
                    raw = candidates[0].strip()
                    if re.fullmatch(r'https?://[^\s\"\'<>]+', raw, flags=re.IGNORECASE):
                        original = raw
            if not isinstance(original, str):
                unreadable += 1
        try:
            if isinstance(original, str) and link_identity(original) == identity:
                matches.append(path)
        except ValueError:
            continue
    return matches, unreadable


def _write_capture_note(items_root: Path, record: dict) -> Path:
    """Create a readable, linked capture record without altering existing notes."""
    note_root = items_root.parent / 'captures'
    note_root.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(record['request_id'].encode()).hexdigest() + '.md'
    note_path = note_root / name
    metadata = {
        'capture_request_id': record['request_id'], 'item_id': record['item_id'],
        'source_url': record['url'], 'site': record['site'], 'source': record['source'],
        'source_device': record['source_device'], 'date_captured': record['captured_at'],
        'tags': record['tags'],
    }
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
    title = str(record['title'] or record['site'] or 'Capture').replace('\n', ' ')
    related = '\n'.join(f'- [[{item_id}]]' for item_id in record['related_item_ids'])
    text = f'---\n{header}---\n\n# {title}\n\n{related}\n\n{record["note"]}\n'
    fd, temp_name = tempfile.mkstemp(prefix='.capture-note-', dir=note_root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_name, note_path)
        except FileExistsError:
            if note_path.read_text(encoding='utf-8') != text:
                raise ValueError('capture note already exists with different content')
    finally:
        os.unlink(temp_name)
    return note_path


def capture_link(items_root: Path, req: CaptureRequest) -> dict:
    items_root = validate_qwiki_path(items_root, allow_container=True, label='QWIKI_ITEMS')
    identity = link_identity(req.url)
    if not req.source.strip() or not req.source_device.strip() or not req.request_id.strip():
        raise ValueError('source, device and request ID are required')
    records = items_root.parent / '_meta' / 'capture-records'
    record_path = records / (hashlib.sha256(req.request_id.encode()).hexdigest() + '.json')
    if req.dry_run:
        matches, unreadable = _matches(items_root, identity)
        result = WiqiItemWriter(items_root).write(WiqiItemRequest(
            source=req.source, source_device=req.source_device, kind='url', url=req.url,
            title=req.title, text=req.note or None, client_request_id=req.request_id, dry_run=True,
            tags=req.tags, keep_original=req.keep_original))
        return {**result, 'item_id': matches[0].stem if matches else result['item_id'],
                'qwiki_path': str(matches[0]) if matches else result['qwiki_path'],
                'related_item_ids': [p.stem for p in matches], 'unreadable_items': unreadable}
    records.mkdir(parents=True, exist_ok=True)
    with (records / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding='utf-8'))
            if (record['request_id'] != req.request_id or record['url'] != req.url or
                    record['note'] != req.note or record['source'] != req.source or
                    record['source_device'] != req.source_device or record['title'] != req.title or
                    record['tags'] != req.tags or record['keep_original'] != req.keep_original):
                raise ValueError('request ID was already used for a different capture')
            note_path = _write_capture_note(items_root, record)
            return {'ok': True, 'dry_run': False, 'deduped': True, 'item_id': record['item_id'],
                    'request_id': req.request_id,
                    'qwiki_path': record['qwiki_path'], 'related_item_ids': record['related_item_ids'],
                    'capture_path': str(note_path)}
        matches, unreadable = _matches(items_root, identity)
        if matches:
            target = matches[0]
            result = {'ok': True, 'dry_run': False, 'deduped': False,
                      'item_id': target.stem, 'qwiki_path': str(target), 'source_url': req.url}
        else:
            result = WiqiItemWriter(items_root).write(WiqiItemRequest(
                source=req.source, source_device=req.source_device, kind='url', url=req.url,
                title=req.title, text=req.note or None, client_request_id=req.request_id,
                tags=req.tags, keep_original=req.keep_original))
        record = {'request_id': req.request_id, 'identity': identity, 'url': req.url,
                  'source': req.source, 'source_device': req.source_device, 'note': req.note,
                  'title': req.title, 'site': urlsplit(req.url).hostname,
                  'tags': req.tags, 'keep_original': req.keep_original,
                  'captured_at': datetime.now(timezone.utc).isoformat(),
                  'item_id': result['item_id'], 'qwiki_path': result['qwiki_path'],
                  'unreadable_items': unreadable,
                  'related_item_ids': [p.stem for p in matches] or [result['item_id']]}
        fd, temp_name = tempfile.mkstemp(prefix='.capture-', dir=records)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(record, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, record_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        note_path = _write_capture_note(items_root, record)
        return {**result, 'request_id': req.request_id,
                'related_item_ids': record['related_item_ids'], 'capture_path': str(note_path),
                'unreadable_items': unreadable}


def save_source_content(items_root: Path, request_id: str, content: str) -> Path:
    """Preserve extracted text separately; never overwrite an earlier extraction."""
    items_root = validate_qwiki_path(items_root, allow_container=True, label='QWIKI_ITEMS')
    if not request_id.strip() or not content.strip():
        raise ValueError('request ID and content are required')
    record_id = hashlib.sha256(request_id.encode()).hexdigest()
    record_path = items_root.parent / '_meta' / 'capture-records' / f'{record_id}.json'
    if not record_path.is_file():
        raise ValueError('capture record not found')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    content_id = hashlib.sha256(content.encode()).hexdigest()[:16]
    content_root = items_root.parent / 'captures' / 'source-content'
    content_root.mkdir(parents=True, exist_ok=True)
    path = content_root / f'{record_id}-{content_id}.md'
    text = f'# 원문 추출\n\n- 자료: [[{record["item_id"]}]]\n- 저장 기록: [[{record_id}]]\n\n{content}\n'
    fd, name = tempfile.mkstemp(prefix='.source-', dir=content_root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if path.read_text(encoding='utf-8') != text:
                raise ValueError('source content path conflict')
    finally:
        os.unlink(name)
    return path
