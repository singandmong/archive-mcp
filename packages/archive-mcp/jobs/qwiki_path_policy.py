from __future__ import annotations

import os
from pathlib import Path

CANONICAL_HOST_VAULT = Path.home() / "Documents" / "WIQI" / "WIQI"
LEGACY_HOST_VAULT = Path.home() / "Documents" / "Obsidian" / "Q-WIKI"
CONTAINER_VAULT = Path("/qwiki")
LEGACY_ERROR = "legacy Q-WIKI path forbidden"


class LegacyQwikiPathError(ValueError):
    pass


def _expand_raw_path(value: str | os.PathLike[str]) -> Path:
    raw = os.path.expandvars(os.path.expanduser(str(value)))
    return Path(raw)


def _is_same_or_descendant(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def validate_qwiki_path(
    value: str | os.PathLike[str],
    *,
    allow_container: bool = False,
    label: str = "Q-WIKI path",
) -> Path:
    path = _expand_raw_path(value)
    if _is_same_or_descendant(path, LEGACY_HOST_VAULT):
        raise LegacyQwikiPathError(
            f"{LEGACY_ERROR}: {label}={path}; use {CANONICAL_HOST_VAULT}"
        )
    if _is_same_or_descendant(path, CONTAINER_VAULT) and not allow_container:
        raise ValueError(
            f"container Q-WIKI path not allowed for host context: {label}={path}"
        )
    return path


def qwiki_path_from_env(
    env_name: str,
    default: str | os.PathLike[str],
    *,
    allow_container: bool = False,
) -> Path:
    value = os.environ.get(env_name, str(default))
    return validate_qwiki_path(value, allow_container=allow_container, label=env_name)
