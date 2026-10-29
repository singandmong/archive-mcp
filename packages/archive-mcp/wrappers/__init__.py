"""Wrapper stubs — wave-0 scaffolding.

Each wrapper module exposes a single class with the canonical surface its
wave-1 worker will fill in. All methods raise NotImplementedError until the
relevant worker (B = ingestion, C = rag, D = media) lands its commit.

Importing this package gives downstream code (server.py, jobs/queue.py) a
single import path:
    from wrappers import (
        CogneeWrapper, NotebookLMWrapper, Crawl4AIWrapper,
        DoclingWrapper, WhisperWrapper, OpenCLIWrapper,
    )
"""

from __future__ import annotations

from .cognee import CogneeWrapper
from .crawl4ai import Crawl4AIWrapper
from .docling import DoclingWrapper
from .notebooklm import NotebookLMWrapper
from .opencli import OpenCLIWrapper
from .whisper import WhisperWrapper

__all__ = [
    "CogneeWrapper",
    "NotebookLMWrapper",
    "Crawl4AIWrapper",
    "DoclingWrapper",
    "WhisperWrapper",
    "OpenCLIWrapper",
]
