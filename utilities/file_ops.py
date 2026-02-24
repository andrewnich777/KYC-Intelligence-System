"""
Atomic file write utilities.

Writes to a temporary ``.tmp`` file first, then atomically replaces the
target via ``os.replace()``.  This prevents half-written files if the
process is killed mid-write.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _atomic_write(path: Path, writer_fn: Callable[[Path], None]) -> None:
    """Core atomic write: call *writer_fn* on a temp file, then replace *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        writer_fn(tmp_path)
        os.replace(str(tmp_path), str(path))
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path | str, data: Any, indent: int = 2) -> None:
    """Write *data* as JSON to *path* atomically."""
    path = Path(path)
    _atomic_write(path, lambda tmp: tmp.write_text(
        json.dumps(data, indent=indent, default=str), encoding="utf-8",
    ))


def atomic_write_text(path: Path | str, content: str) -> None:
    """Write *content* to *path* atomically."""
    path = Path(path)
    _atomic_write(path, lambda tmp: tmp.write_text(content, encoding="utf-8"))


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write *data* (bytes) to *path* atomically."""
    path = Path(path)
    _atomic_write(path, lambda tmp: tmp.write_bytes(data))
