"""Shared helpers of the audit commands: database access, statistics, source lines."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

from codegraph_sci.core.plugins import decode_bytes
from codegraph_sci.store.db import open_db

# Thresholds of §2.1 (overridable by a corpus expectations file).
DEFAULT_THRESHOLDS = {
    "min_attribution": 0.99,
    "max_parse_failure_rate": 0.02,
    "min_recall_definitions": 0.99,
    "min_recall_call_sites": 0.97,
    "min_recall_lower_bound": 0.93,
    "min_precision_resolved": 0.98,
    "min_precision_lower_bound": 0.95,
    "min_precision_bridges": 0.95,
    "min_precision_bridges_lower_bound": 0.90,
    "max_unresolved_rate": 0.02,
}


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval (95 % by default)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def connect(db: Path) -> sqlite3.Connection:
    return open_db(db)


def scan_root(con: sqlite3.Connection) -> Path | None:
    row = con.execute("SELECT root FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
    return Path(row[0]) if row else None


class SourceLines:
    """Cached access to the lines of the analysed files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, list[str]] = {}

    def lines(self, path: str) -> list[str]:
        if path not in self._cache:
            try:
                text, _enc = decode_bytes((self.root / path).read_bytes())
            except OSError:
                text = ""
            self._cache[path] = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return self._cache[path]

    def line(self, path: str, number: int) -> str:
        lines = self.lines(path)
        return lines[number - 1] if 0 < number <= len(lines) else ""
