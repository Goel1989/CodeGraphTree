"""Helpers to build an :class:`ExtractContext` for a repository."""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from codegraph_sci.core.plugins import IncludedFile, decode_bytes, sha256_bytes


def make_include_resolver(root: Path, include_paths: list[str]) -> Callable[[str, str], IncludedFile | None]:
    """Resolve ``#include``/``INCLUDE`` targets: directory of the including file, then include paths."""
    root = root.resolve()

    @lru_cache(maxsize=4096)
    def load(rel: str) -> IncludedFile | None:
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            return None
        text, _enc = decode_bytes(data)
        return IncludedFile(rel, text, sha256_bytes(data))

    def resolve(target: str, from_path: str) -> IncludedFile | None:
        target = target.strip().replace("\\", "/")
        candidates = [posixpath.normpath(posixpath.join(posixpath.dirname(from_path), target))]
        candidates += [posixpath.normpath(posixpath.join(p, target)) for p in include_paths if p != "."]
        candidates.append(posixpath.normpath(target))
        for rel in candidates:
            if rel.startswith("..") or rel.startswith("/"):
                continue
            if (root / rel).is_file():
                return load(rel)
        return None

    return resolve
