"""``GraphQuery``: the contract between the engine, the command line and the desktop app (§3.10).

Basic queries are indexed SQL on precomputed tables; nothing loads the whole graph. ``paths`` and
``impact`` walk the graph breadth-first with explicit bounds and say when they stop at a bound.
Every list is sorted in a stable way and paginated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from codegraph_sci.core.model import CALL_PATH
from codegraph_sci.core.plugins import decode_bytes
from codegraph_sci.query.types import (
    CallerReport,
    CallSite,
    DataAccessView,
    Direction,
    FileLink,
    GraphPath,
    ImpactReport,
    InventoryReport,
    LanguageLine,
    Level,
    LinkItem,
    NodeDetail,
    NodeSummary,
    Page,
    PathReport,
    PathStep,
    ScanHealth,
    SiteGroup,
    SourceExcerpt,
    TreeItem,
)
from codegraph_sci.store.db import open_db

CALL_REFS = ("call", "maybe_call", "dynamic_call")
_SUMMARY = ("SELECT n.id, n.uid, n.display_name, n.kind, n.subtype, n.lang, f.path, n.line_start, "
            "COALESCE(s.fan_in, 0), COALESCE(s.fan_out, 0), COALESCE(s.is_noise, 0) FROM nodes n "
            "LEFT JOIN files f ON f.id = n.file_id LEFT JOIN node_stats s ON s.node_id = n.id ")


def site_pattern(target: str) -> str:
    """Pattern of an unresolved target, used to group sites (prefix such as ``FCALL_*``, receiver ``x.*``)."""
    m = re.match(r"^([A-Za-z]+_)", target)
    if m and len(m.group(1)) <= 12:
        return m.group(1) + "*"
    if "%" in target or "." in target or "::" in target or "->" in target:
        return re.sub(r"\w+$", "*", target.replace("->", "."))
    return target.lower()


class QueryError(LookupError):
    pass


class GraphQuery:
    def __init__(self, db_path: Path | str, *, read_only: bool = True) -> None:
        self.db_path = Path(db_path)
        self.con: sqlite3.Connection = open_db(self.db_path, read_only=read_only)
        self._root: Path | None = None

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> GraphQuery:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ helpers
    def _summary(self, row: tuple[Any, ...]) -> NodeSummary:
        return NodeSummary(row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], bool(row[10]))

    def _id(self, uid: str) -> int:
        row = self.con.execute("SELECT id FROM nodes WHERE uid = ?", (uid,)).fetchone()
        if row is None:
            raise QueryError(f"unknown symbol: {uid}")
        return int(row[0])

    def _summary_by_id(self, node_id: int) -> NodeSummary:
        row = self.con.execute(_SUMMARY + "WHERE n.id = ?", (node_id,)).fetchone()
        return self._summary(row)

    def _site(self, row: tuple[Any, ...]) -> CallSite:
        return CallSite(file=row[0], line=row[1], col=row[2], target_text=row[3], ref_kind=row[4], condition=row[5],
                        origin=row[6], confidence=row[7], resolution=row[8], src=row[9], dst=row[10])

    @property
    def root(self) -> Path | None:
        if self._root is None:
            row = self.con.execute("SELECT root FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
            self._root = Path(row[0]) if row else None
        return self._root

    # ---------------------------------------------------------- inventory
    def inventory(self) -> InventoryReport:
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        lines: dict[str, int] = defaultdict(int)
        adapters: dict[str, str | None] = {}
        for lang, status, adapter, n, nlines in self.con.execute(
                "SELECT f.lang, f.parse_status, f.adapter, count(*), sum(COALESCE(n.line_end, 0)) FROM files f "
                "LEFT JOIN nodes n ON n.file_id = f.id AND n.kind = 'file' WHERE f.lang IS NOT NULL "
                "GROUP BY f.lang, f.parse_status, f.adapter"):
            counts[lang][status] += n
            lines[lang] += nlines or 0
            adapters.setdefault(lang, adapter)
        langs = [LanguageLine(lang, sum(st.values()), lines[lang], adapters.get(lang), dict(sorted(st.items())))
                 for lang, st in sorted(counts.items())]
        unknown: dict[str, int] = defaultdict(int)
        for (path,) in self.con.execute("SELECT f.path FROM inventory i JOIN files f ON f.id = i.file_id "
                                        "WHERE i.lang IS NULL"):
            name = path.rsplit("/", 1)[-1]
            unknown[name[name.rfind("."):].lower() if "." in name[1:] else "(none)"] += 1
        total = self.con.execute("SELECT count(*) FROM files").fetchone()[0]
        return InventoryReport(langs, dict(sorted(unknown.items())), total)

    # ------------------------------------------------------------- search
    def find(self, text: str, kinds: set[str] | None = None, limit: int = 50) -> list[NodeSummary]:
        """Fuzzy search on names, qualified names and paths: exact, then prefix, then contains."""
        text = text.strip()
        if not text:
            return []
        low = text.lower()
        kinds_sql = ""
        params: list[Any] = []
        if kinds:
            kinds_sql = f" AND n.kind IN ({','.join('?' * len(kinds))})"
            params = sorted(kinds)
        tokens = [t for t in re.split(r"[^\w]+", low) if t]
        ids: dict[int, int] = {}
        if tokens:
            fts = " ".join(f'"{t}"*' for t in tokens)
            try:
                for (node_id,) in self.con.execute(
                        "SELECT node_id FROM search_fts WHERE search_fts MATCH ? ORDER BY rank LIMIT ?",
                        (fts, limit * 20)):
                    ids.setdefault(int(node_id), 2)
            except sqlite3.OperationalError:
                pass
        for (node_id,) in self.con.execute("SELECT id FROM nodes WHERE lower(display_name) LIKE ? OR uid LIKE ? "
                                           "LIMIT ?", (f"%{low}%", f"%{low}%", limit * 20)):
            ids.setdefault(int(node_id), 3)
        if not ids:
            return []
        rows = self.con.execute(_SUMMARY + f"WHERE n.id IN ({','.join(map(str, ids))}){kinds_sql}", params).fetchall()

        def rank(row: tuple[Any, ...]) -> tuple[int, int, int, str]:
            name = str(row[2]).lower()
            uid = str(row[1]).lower()
            score = 0 if name == low or uid == low else (1 if name.startswith(low) else ids.get(row[0], 3))
            kind_order = 0 if row[3] == "routine" else (1 if row[3] in ("type", "module", "interface") else 2)
            return (score, kind_order, -int(row[8]), uid)

        return [self._summary(r) for r in sorted(rows, key=rank)[:limit]]

    def resolve(self, name_or_uid: str) -> list[NodeSummary]:
        """Symbols matching exactly a uid or a name (case-insensitive)."""
        row = self.con.execute(_SUMMARY + "WHERE n.uid = ?", (name_or_uid,)).fetchone()
        if row is not None:
            return [self._summary(row)]
        low = name_or_uid.lower()
        rows = self.con.execute(_SUMMARY + "WHERE lower(n.display_name) = ? AND n.kind != 'file' ORDER BY n.uid",
                                (low,)).fetchall()
        if not rows:
            rows = self.con.execute(_SUMMARY + "WHERE (n.uid LIKE ? OR n.uid LIKE ?) AND n.kind != 'file' "
                                    "ORDER BY n.uid", (f"%:{low}", f"%::{low}(%")).fetchall()
        return [self._summary(r) for r in rows]

    def node(self, uid: str) -> NodeDetail:
        row = self.con.execute(
            "SELECT n.id, n.uid, n.display_name, n.kind, n.subtype, n.lang, f.path, n.line_start, "
            "COALESCE(s.fan_in, 0), COALESCE(s.fan_out, 0), COALESCE(s.is_noise, 0), n.line_end, n.in_scope, "
            "n.attrs, COALESCE(s.impact_size, 0), COALESCE(s.fan_in_filtered, 0), COALESCE(s.fan_out_filtered, 0), "
            "s.noise_reason FROM nodes n LEFT JOIN files f ON f.id = n.file_id LEFT JOIN node_stats s "
            "ON s.node_id = n.id WHERE n.uid = ?", (uid,)).fetchone()
        if row is None:
            raise QueryError(f"unknown symbol: {uid}")
        return NodeDetail(row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], bool(row[10]),
                          line_end=row[11], in_scope=bool(row[12]), attrs=json.loads(row[13] or "{}"),
                          impact_size=row[14], fan_in_filtered=row[15], fan_out_filtered=row[16],
                          noise_reason=row[17])

    # ---------------------------------------------------- callers/callees
    _SITE_COLS = ("SELECT f.path, s.line, s.col, s.target_text, s.ref_kind, c.expr, s.origin, s.confidence, "
                  "s.resolution, src.uid, dst.uid, s.id FROM call_sites s JOIN files f ON f.id = s.file_id "
                  "JOIN nodes src ON src.id = s.src_node LEFT JOIN nodes dst ON dst.id = s.dst_node "
                  "LEFT JOIN conditions c ON c.id = s.condition_id ")

    def _links(self, node_id: int, direction: Direction, hide_noise: bool) -> tuple[list[LinkItem], int]:
        kinds = ",".join(f"'{k}'" for k in CALL_REFS)
        if direction is Direction.CALLERS:
            rows = self.con.execute(
                self._SITE_COLS + f"WHERE s.ref_kind IN ({kinds}) AND (s.dst_node = ? OR s.id IN "
                "(SELECT site_id FROM call_site_candidates WHERE dst_node = ?))", (node_id, node_id)).fetchall()
        else:
            rows = self.con.execute(self._SITE_COLS + f"WHERE s.ref_kind IN ({kinds}) AND s.src_node = ?",
                                    (node_id,)).fetchall()
        groups: dict[str, list[CallSite]] = defaultdict(list)
        for r in rows:
            site = self._site(r)
            if direction is Direction.CALLERS:
                groups[site.src].append(site)
            else:
                targets = [site.dst] if site.dst else []
                if not targets:
                    targets = [c[0] for c in self.con.execute(
                        "SELECT n.uid FROM call_site_candidates c JOIN nodes n ON n.id = c.dst_node "
                        "WHERE c.site_id = ? ORDER BY n.uid", (r[11],))]
                for t in targets:
                    groups[t].append(site)
        items: list[LinkItem] = []
        hidden = 0
        for uid in sorted(groups):
            summary = self._summary(self.con.execute(_SUMMARY + "WHERE n.uid = ?", (uid,)).fetchone())
            if hide_noise and summary.is_noise:
                hidden += 1
                continue
            sites = sorted(groups[uid], key=lambda s: (s.file, s.line, s.col))
            items.append(LinkItem(summary, sites))
        items.sort(key=lambda i: (i.node.display_name.lower(), i.node.uid))
        return items, hidden

    def callers(self, uid: str, *, hide_noise: bool = True) -> CallerReport:
        node_id = self._id(uid)
        items, hidden = self._links(node_id, Direction.CALLERS, hide_noise)
        files = {s.file for i in items for s in i.sites}
        return CallerReport(self._summary_by_id(node_id), len(items), len(files),
                            sum(len(i.sites) for i in items), items, hidden)

    def callees(self, uid: str, *, hide_noise: bool = True) -> CallerReport:
        node_id = self._id(uid)
        items, hidden = self._links(node_id, Direction.CALLEES, hide_noise)
        files = {i.node.file for i in items if i.node.file}
        return CallerReport(self._summary_by_id(node_id), len(items), len(files),
                            sum(len(i.sites) for i in items), items, hidden)

    def call_sites(self, src_uid: str, dst_uid: str) -> list[CallSite]:
        src, dst = self._id(src_uid), self._id(dst_uid)
        rows = self.con.execute(self._SITE_COLS + "WHERE s.src_node = ? AND (s.dst_node = ? OR s.id IN "
                                "(SELECT site_id FROM call_site_candidates WHERE dst_node = ?)) "
                                "ORDER BY f.path, s.line, s.col", (src, dst, dst)).fetchall()
        if not rows:  # file-level link: every site from a file to another
            rows = self.con.execute(
                self._SITE_COLS + "WHERE s.file_id = (SELECT file_id FROM nodes WHERE id = ?) AND dst.file_id = "
                "(SELECT file_id FROM nodes WHERE id = ?) ORDER BY f.path, s.line, s.col", (src, dst)).fetchall()
        return [self._site(r) for r in rows]

    # ------------------------------------------------------------ children
    def children(self, uid: str, *, direction: Direction, level: Level = Level.ROUTINE,
                 edge_kinds: set[str] | frozenset[str] = CALL_PATH, offset: int = 0, limit: int = 50,
                 hide_noise: bool = True) -> Page:
        if level is Level.ROUTINE:
            return self._routine_children(uid, direction, edge_kinds, offset, limit, hide_noise)
        if level is Level.FILE:
            return self._file_children(uid, direction, offset, limit)
        return self._dir_children(uid, direction, offset, limit)

    def _routine_children(self, uid: str, direction: Direction, edge_kinds: set[str] | frozenset[str], offset: int,
                          limit: int, hide_noise: bool) -> Page:
        node_id = self._id(uid)
        kinds = sorted(edge_kinds)
        mark = ",".join("?" * len(kinds))
        this, other = ("dst", "src") if direction is Direction.CALLERS else ("src", "dst")
        rows = self.con.execute(
            f"SELECT n.uid, n.display_name, n.kind, n.lang, f.path, e.kind, e.site_count, e.min_confidence, "
            f"COALESCE(s.fan_in, 0), COALESCE(s.fan_out, 0), COALESCE(s.is_noise, 0) FROM edges e "
            f"JOIN nodes n ON n.id = e.{other} LEFT JOIN files f ON f.id = n.file_id "
            f"LEFT JOIN node_stats s ON s.node_id = n.id WHERE e.{this} = ? AND e.kind IN ({mark})",
            (node_id, *kinds)).fetchall()
        merged: dict[str, TreeItem] = {}
        hidden = 0
        for r in rows:
            if hide_noise and r[10]:
                hidden += 1
                continue
            has_children = (r[8] if direction is Direction.CALLERS else r[9]) > 0
            item = merged.get(r[0])
            if item is None:
                merged[r[0]] = TreeItem(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[5] == "dispatches",
                                        has_children, bool(r[10]))
            else:
                item.count += r[6]
                item.possible = item.possible and r[5] == "dispatches"
        items = sorted(merged.values(), key=lambda i: (i.label.lower(), i.uid))
        return Page(items[offset:offset + limit], len(items), offset, limit, hidden)

    def _file_children(self, file_ref: str, direction: Direction, offset: int, limit: int) -> Page:
        path = file_ref[5:] if file_ref.startswith("file:") else file_ref
        this, other = ("dst_file", "src_file") if direction is Direction.CALLERS else ("src_file", "dst_file")
        rows = self.con.execute(
            f"SELECT o.path, o.lang, e.kind, e.count FROM file_edges e JOIN files t ON t.id = e.{this} "
            f"JOIN files o ON o.id = e.{other} WHERE t.path = ?", (path,)).fetchall()
        merged: dict[str, TreeItem] = {}
        for p, lang, kind, count in rows:
            item = merged.get(p)
            if item is None:
                merged[p] = TreeItem(f"file:{p}", p.rsplit("/", 1)[-1], "file", lang, p, kind, count, "exact",
                                     False, True)
            else:
                item.count += count
        items = sorted(merged.values(), key=lambda i: (i.file or "", i.uid))
        return Page(items[offset:offset + limit], len(items), offset, limit)

    def _dir_children(self, directory: str, direction: Direction, offset: int, limit: int) -> Page:
        d = directory[4:] if directory.startswith("dir:") else directory
        this, other = ("dst_dir", "src_dir") if direction is Direction.CALLERS else ("src_dir", "dst_dir")
        rows = self.con.execute(f"SELECT {other}, kind, count FROM dir_edges WHERE {this} = ?", (d,)).fetchall()
        merged: dict[str, TreeItem] = {}
        for other_dir, kind, count in rows:
            item = merged.get(other_dir)
            if item is None:
                merged[other_dir] = TreeItem(f"dir:{other_dir}", other_dir, "directory", None, None, kind, count,
                                             "exact", False, True)
            else:
                item.count += count
        items = sorted(merged.values(), key=lambda i: i.uid)
        return Page(items[offset:offset + limit], len(items), offset, limit)

    def file_links(self, file_uid: str, *, direction: Direction) -> list[FileLink]:
        page = self._file_children(file_uid, direction, 0, 10**9)
        return [FileLink(i.file or "", i.lang, i.edge_kind, i.count) for i in page.items]

    # ---------------------------------------------------- paths and impact
    def _neighbours(self, node_id: int, kinds: list[str], reverse: bool,
                    cache: dict[int, list[tuple[int, str, str]]]) -> list[tuple[int, str, str]]:
        if node_id not in cache:
            this, other = ("dst", "src") if reverse else ("src", "dst")
            mark = ",".join("?" * len(kinds))
            cache[node_id] = sorted(self.con.execute(
                f"SELECT {other}, kind, min_confidence FROM edges WHERE {this} = ? AND kind IN ({mark})",
                (node_id, *kinds)).fetchall())
        return cache[node_id]

    def paths(self, src_uid: str, dst_uid: str, *, edge_kinds: set[str] | frozenset[str] = CALL_PATH, k: int = 5,
              max_len: int = 15, max_nodes: int = 200_000) -> PathReport:
        src, dst = self._id(src_uid), self._id(dst_uid)
        kinds = sorted(edge_kinds)
        rev_cache: dict[int, list[tuple[int, str, str]]] = {}
        fwd_cache: dict[int, list[tuple[int, str, str]]] = {}
        # Distance to the target (reverse BFS, bounded).
        dist = {dst: 0}
        queue = deque([dst])
        truncated = False
        while queue:
            v = queue.popleft()
            if dist[v] >= max_len:
                continue
            for w, _kind, _conf in self._neighbours(v, kinds, True, rev_cache):
                if w not in dist:
                    if len(dist) >= max_nodes:
                        truncated = True
                        queue.clear()
                        break
                    dist[w] = dist[v] + 1
                    queue.append(w)
        if src not in dist:
            return PathReport([], truncated)
        found: list[list[tuple[int, str | None, str | None]]] = []
        frontier: deque[list[tuple[int, str | None, str | None]]] = deque([[(src, None, None)]])
        expansions = 0
        while frontier and len(found) < k:
            path = frontier.popleft()
            v = path[-1][0]
            if v == dst:
                found.append(path)
                continue
            for w, kind, conf in self._neighbours(v, kinds, False, fwd_cache):
                if w not in dist or any(p[0] == w for p in path) or len(path) + dist[w] > max_len + 1:
                    continue
                expansions += 1
                if expansions > max_nodes:
                    truncated = True
                    frontier.clear()
                    break
                frontier.append(path + [(w, kind, conf)])
        uid_of = {}
        for p in found:
            for node_id, _k, _c in p:
                if node_id not in uid_of:
                    uid_of[node_id] = self.con.execute("SELECT uid FROM nodes WHERE id = ?", (node_id,)).fetchone()[0]
        out = [GraphPath([PathStep(uid_of[n], kind, conf, kind == "dispatches") for n, kind, conf in p])
               for p in found]
        return PathReport(out, truncated or (bool(frontier) and len(found) >= k))

    def impact(self, uid: str, *, edge_kinds: set[str] | frozenset[str] = CALL_PATH, max_depth: int | None = None,
               max_nodes: int = 100_000, limit: int = 200) -> ImpactReport:
        """Transitive callers of ``uid`` (who is concerned if it changes)."""
        start = self._id(uid)
        kinds = sorted(edge_kinds)
        cache: dict[int, list[tuple[int, str, str]]] = {}
        depth = {start: 0}
        queue = deque([start])
        truncated = False
        while queue:
            v = queue.popleft()
            if max_depth is not None and depth[v] >= max_depth:
                if self._neighbours(v, kinds, True, cache):
                    truncated = True
                continue
            for w, _kind, _conf in self._neighbours(v, kinds, True, cache):
                if w not in depth:
                    if len(depth) > max_nodes:
                        truncated = True
                        queue.clear()
                        break
                    depth[w] = depth[v] + 1
                    queue.append(w)
        del depth[start]
        by_depth: dict[int, int] = defaultdict(int)
        for d in depth.values():
            by_depth[d] += 1
        ordered = sorted(depth.items(), key=lambda kv: (kv[1], kv[0]))
        items = [(d, self._summary_by_id(n)) for n, d in ordered[:limit]]
        items.sort(key=lambda x: (x[0], x[1].display_name.lower(), x[1].uid))
        entry = sorted(s.uid for _d, s in items if s.fan_in == 0 and s.kind == "routine")
        return ImpactReport(uid, len(depth), dict(sorted(by_depth.items())), items, entry, truncated)

    # --------------------------------------------------------------- data
    def data_accesses(self, uid: str) -> list[DataAccessView]:
        node_id = self._id(uid)
        rows = self.con.execute(
            "SELECT src.uid, d.uid, fam.uid, a.mode, a.key_kind, f.path, a.line, a.origin FROM data_accesses a "
            "JOIN nodes src ON src.id = a.src_node JOIN nodes d ON d.id = a.data_node "
            "LEFT JOIN nodes fam ON fam.id = a.family_node JOIN files f ON f.id = a.file_id "
            "WHERE a.src_node = ? OR a.data_node = ? OR a.family_node = ? ORDER BY f.path, a.line, d.uid, a.mode",
            (node_id, node_id, node_id)).fetchall()
        return [DataAccessView(*r) for r in rows]

    # -------------------------------------------------------- diagnostics
    def unresolved(self, *, group_by: str = "pattern", include_ambiguous: bool = False,
                   limit: int = 50) -> list[SiteGroup]:
        states = ("unresolved", "ambiguous") if include_ambiguous else ("unresolved",)
        rows = self.con.execute(
            "SELECT s.target_text, s.resolution, f.path, s.line, f.lang FROM call_sites s JOIN files f "
            f"ON f.id = s.file_id WHERE s.resolution IN ({','.join('?' * len(states))}) "
            "ORDER BY f.path, s.line, s.col", states).fetchall()
        groups: dict[tuple[str, str, str], list[tuple[Any, ...]]] = defaultdict(list)
        for target, resolution, path, line, lang in rows:
            key = site_pattern(target) if group_by == "pattern" else target
            groups[(lang or "?", resolution, key)].append((target, path, line))
        out = [SiteGroup(lang, res, pattern, len(items), len({i[1] for i in items}),
                         [{"target": t, "file": p, "line": ln} for t, p, ln in items[:5]])
               for (lang, res, pattern), items in groups.items()]
        out.sort(key=lambda g: (-g.count, g.lang, g.pattern))
        return out[:limit]

    def scan_health(self) -> ScanHealth:
        files = dict(self.con.execute("SELECT parse_status, count(*) FROM files GROUP BY parse_status").fetchall())
        kinds = ",".join(f"'{k}'" for k in CALL_REFS)
        sites = dict(self.con.execute(f"SELECT resolution, count(*) FROM call_sites WHERE ref_kind IN ({kinds}) "
                                      "GROUP BY resolution").fetchall())
        total = sum(sites.values())
        row = self.con.execute("SELECT started_at, finished_at, root, git_rev, profile_version, stats FROM scan_runs "
                               "ORDER BY id DESC LIMIT 1").fetchone()
        last = {} if row is None else {"started_at": row[0], "finished_at": row[1], "root": row[2],
                                       "git_rev": row[3], "profile_version": row[4],
                                       "stats": json.loads(row[5] or "{}")}
        failures = [{"path": p, "status": s, "error": e} for p, s, e in self.con.execute(
            "SELECT path, parse_status, error FROM files WHERE parse_status IN ('failed', 'fallback') "
            "ORDER BY path LIMIT 100")]
        return ScanHealth(dict(sorted(files.items())), dict(sorted(sites.items())),
                          sites.get("unresolved", 0) / total if total else 0.0, sites.get("ambiguous", 0), last,
                          failures)

    # ------------------------------------------------------------- source
    def source(self, file_uid: str, start: int, end: int) -> SourceExcerpt:
        """Lines of a file; ``stale`` if the file changed since the analysis (size/date, then SHA-256)."""
        path = file_uid[5:] if file_uid.startswith("file:") else file_uid
        row = self.con.execute("SELECT sha256, size, mtime_ns, encoding FROM files WHERE path = ?", (path,)).fetchone()
        root = self.root
        if row is None or root is None:
            raise QueryError(f"unknown file: {path}")
        full = root / path
        try:
            st = os.stat(full)
            data = full.read_bytes()
        except OSError:
            return SourceExcerpt(path, start, end, [], True, row[3], missing=True)
        stale = False
        if st.st_size != row[1] or st.st_mtime_ns != row[2]:
            stale = hashlib.sha256(data).hexdigest() != row[0]
        text, enc = decode_bytes(data)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        start = max(1, start)
        end = min(len(lines), max(start, end))
        return SourceExcerpt(path, start, end, lines[start - 1:end], stale, enc)
