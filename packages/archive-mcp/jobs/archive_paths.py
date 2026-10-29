"""Shared archive location for stdio and HTTP capture."""
from __future__ import annotations

import os
from pathlib import Path

from jobs.qwiki_path_policy import validate_qwiki_path


def archive_root() -> Path:
    archive = os.environ.get("ARCHIVE_DATA_DIR", "")
    legacy_name = os.environ.get("QWIKI_VAULT", "")
    if archive and legacy_name:
        first = Path(os.path.expandvars(os.path.expanduser(archive))).resolve()
        second = Path(os.path.expandvars(os.path.expanduser(legacy_name))).resolve()
        if first != second:
            raise RuntimeError("ARCHIVE_DATA_DIR and QWIKI_VAULT must refer to the same directory")
    return validate_qwiki_path(
        archive or legacy_name or "~/.local/share/archive-mcp",
        allow_container=True,
        label="archive root",
    )
