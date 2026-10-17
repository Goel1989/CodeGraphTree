"""Writing a :class:`GraphBundle` into the project database (§3.6).

* Full analysis: built in ``<db>.tmp`` with the journal disabled, bulk inserts, indexes created at
  the end, ``ANALYZE``, then an atomic replacement: readers never see a half-written database.
* Incremental re-analysis: WAL mode, everything replaced inside one transaction, so readers keep
  seeing the previous snapshot until the commit.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from itertools import islice
from pathlib import Path
from typing import Any

from codegraph_sci.core.graph import GraphBundle
from codegraph_sci.core.versions import APP_VERSION, DB_SCHEMA_VERSION
from codegraph_sci.store.db import check_version, indexes_sql, schema_sql

BATCH = 50_000

DATA_TABLES = ("files", "inventory", "inventory_entries", "inventory_issues", "nodes", "conditions", "call_sites", "call_site_candidates",
               "data_accesses", "facts_cache", "edges", "node_stats", "file_edges", "dir_edges",
               "search_fts", "plugins", "scan_runs", "meta")


def _batches[T](rows: Iterable[T], size: int = BATCH) -> Iterator[list[T]]:
    it = iter(rows)
    while chunk := list(islice(it, size)):
        yield chunk


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _insert(con: sqlite3.Connection, sql: str, rows: Iterable[tuple[Any, ...]]) -> None:
    for chunk in _batches(rows):
        con.executemany(sql, chunk)


def _fill(con: sqlite3.Connection, bundle: GraphBundle,
          progress: Callable[[str], None] | None = None) -> None:
    bundle.sort()
    say = progress or (lambda _msg: None)

    file_ids = {f.path: i for i, f in enumerate(bundle.files, start=1)}
    node_ids = {n.uid: i for i, n in enumerate(bundle.nodes, start=1)}
    conditions = sorted({s.condition for s in bundle.call_sites if s.condition})
    cond_ids = {c: i for i, c in enumerate(conditions, start=1)}

    def fid(path: str | None) -> int | None:
        if path is None:
            return None
        return file_ids[path]

    def nid(uid: str | None) -> int | None:
        if uid is None:
            return None
        return node_ids[uid]

    con.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                    [("app_version", APP_VERSION), ("schema_version", str(DB_SCHEMA_VERSION))])
    say("files")
    _insert(con, "INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ((file_ids[f.path], f.path, f.lang, f.variant, f.sha256, f.size, f.mtime_ns, f.encoding,
              f.parse_status, f.adapter, f.adapter_version, f.error, f.cache_key) for f in bundle.files))
    _insert(con, "INSERT INTO inventory VALUES (?,?,?,?,?)",
            ((file_ids[i.path], i.lang, i.variant, i.confidence, i.decided_by) for i in bundle.inventory))
    _insert(con, "INSERT INTO inventory_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ((i.path, i.parent, i.kind, i.extension, i.size, i.files, i.lang, i.variant, i.confidence, i.evidence,
              i.eligibility, i.status, i.reason, i.link_target) for i in bundle.inventory_items))
    _insert(con, "INSERT INTO inventory_issues VALUES (?,?,?)",
            ((i.path, i.kind, i.message) for i in bundle.inventory_issues))
    say("nodes")
    _insert(con, "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ((node_ids[n.uid], n.uid, n.display_name, n.kind, n.subtype, n.lang, fid(n.file),
              n.line_start, n.line_end, int(n.in_scope), _json(n.attrs)) for n in bundle.nodes))
    _insert(con, "INSERT INTO conditions VALUES (?,?)", ((i, c) for c, i in cond_ids.items()))
    say("call_sites")
    _insert(con, "INSERT INTO call_sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ((i, node_ids[s.src], file_ids[s.file], s.line, s.col, s.ref_kind, s.target_text, nid(s.dst),
              s.resolution, s.confidence, s.origin, cond_ids.get(s.condition) if s.condition else None,
              _json(s.evidence) if s.evidence else None)
             for i, s in enumerate(bundle.call_sites, start=1)))
    _insert(con, "INSERT INTO call_site_candidates VALUES (?,?)",
            ((i, node_ids[c]) for i, s in enumerate(bundle.call_sites, start=1) for c in s.candidates))
    _insert(con, "INSERT INTO data_accesses VALUES (?,?,?,?,?,?,?,?,?)",
            ((i, node_ids[a.src], node_ids[a.data], nid(a.family), a.mode, a.key_kind, file_ids[a.file],
              a.line, a.origin) for i, a in enumerate(bundle.data_accesses, start=1)))
    say("edges")
    _insert(con, "INSERT INTO edges VALUES (?,?,?,?,?,?,?)",
            ((node_ids[e.src], node_ids[e.dst], e.kind, e.site_count, e.min_confidence, _json(e.origins),
              _json(e.conditions)) for e in bundle.edges))
    _insert(con, "INSERT INTO node_stats VALUES (?,?,?,?,?,?,?,?,?)",
            ((node_ids[s.uid], s.fan_in, s.fan_out, s.fan_in_filtered, s.fan_out_filtered, s.impact_size,
              s.impact_size_filtered, int(s.is_noise), s.noise_reason) for s in bundle.node_stats))
    _insert(con, "INSERT INTO file_edges VALUES (?,?,?,?)",
            ((file_ids[e.src], file_ids[e.dst], e.kind, e.count) for e in bundle.file_edges))
    _insert(con, "INSERT INTO dir_edges VALUES (?,?,?,?)",
            ((e.src, e.dst, e.kind, e.count) for e in bundle.dir_edges))
    say("search")
    _insert(con, "INSERT INTO search_fts(name, display, path, doc, node_id) VALUES (?,?,?,?,?)",
            ((_search_name(n.uid), n.display_name, n.file or "", str(n.attrs.get("doc") or ""),
              node_ids[n.uid]) for n in bundle.nodes))
    _insert(con, "INSERT INTO plugins VALUES (?,?,?)",
            ((p.name, p.type, p.version) for p in bundle.plugins))
    if bundle.scan_run is not None:
        r = bundle.scan_run
        con.execute("INSERT INTO scan_runs(started_at, finished_at, root, git_rev, profile_version, "
                    "profile_sha256, plugins, stats) VALUES (?,?,?,?,?,?,?,?)",
                    (r.started_at, r.finished_at, r.root, r.git_rev, r.profile_version, r.profile_sha256,
                     _json(r.plugins), _json(r.stats)))
    _insert(con, "INSERT INTO facts_cache VALUES (?,?)", sorted(bundle.facts_cache.items()))


def _search_name(uid: str) -> str:
    """Searchable tokens of a uid: ``cpp:ns::Cls::run(int)`` -> ``ns Cls run``."""
    body = uid.split(":", 1)[1] if ":" in uid else uid
    body = body.split("(", 1)[0].split("@", 1)[0].split("#", 1)[0]
    for sep in ("::", ".", "/", ":"):
        body = body.replace(sep, " ")
    return body


def write_full(db_path: Path | str, bundle: GraphBundle,
               progress: Callable[[str], None] | None = None) -> None:
    """Build the database in a temporary file, then atomically replace ``db_path``."""
    db_path = Path(db_path)
    tmp = db_path.with_name(db_path.name + ".tmp")
    for stale in (tmp, Path(str(tmp) + "-journal")):
        if stale.exists():
            stale.unlink()
    con = sqlite3.connect(str(tmp))
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        con.executescript(schema_sql())
        con.execute("BEGIN")
        _fill(con, bundle, progress)
        con.executescript(indexes_sql())
        con.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION}")
        con.commit()
        con.execute("ANALYZE")
        con.commit()
        if progress is not None:
            progress("commit")  # last cancellation checkpoint before publishing the temporary database
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    os.replace(tmp, db_path)


def write_incremental(db_path: Path | str, bundle: GraphBundle,
                      progress: Callable[[str], None] | None = None) -> None:
    """Replace the content of an existing database in one WAL transaction."""
    db_path = Path(db_path)
    if not db_path.exists():
        write_full(db_path, bundle, progress)
        return
    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        check_version(con, db_path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("BEGIN IMMEDIATE")
        try:
            for table in DATA_TABLES:
                con.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
            _fill(con, bundle, progress)
            if progress is not None:
                progress("commit")  # still inside the rollback boundary
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("ANALYZE")
    finally:
        con.close()
