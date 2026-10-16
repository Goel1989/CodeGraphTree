"""Facts cache (§3.6): key = file + every included file + adapter + extraction parameters."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from codegraph_sci.core.facts import FileFacts, canonical_json, decode_facts
from codegraph_sci.store.db import open_db


def cache_key(file_sha256: str, included_sha256: list[str], adapter: str, adapter_version: str,
              params: dict[str, object]) -> str:
    payload = canonical_json({"file": file_sha256, "includes": sorted(included_sha256),
                              "adapter": adapter, "adapter_version": adapter_version, "params": params})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cache(db_path: Path | str) -> dict[str, bytes]:
    """Read every cached facts blob of an existing database (empty if none or unreadable)."""
    try:
        con = open_db(db_path)
    except (FileNotFoundError, sqlite3.DatabaseError, RuntimeError):
        return {}
    try:
        return {key: bytes(blob) for key, blob in con.execute("SELECT cache_key, facts FROM facts_cache")}
    finally:
        con.close()


def get_facts(cache: dict[str, bytes], key: str) -> FileFacts | None:
    blob = cache.get(key)
    if blob is None:
        return None
    try:
        return decode_facts(blob)
    except (ValueError, KeyError, TypeError):
        return None
