"""``GraphQuery``: the contract between the engine, the command line and the desktop app (§3.10).

Basic queries are indexed SQL on precomputed tables; nothing loads the whole graph. ``paths`` and
``impact`` walk the graph breadth-first with explicit bounds and say when they stop at a bound.
Every list is sorted in a stable way and paginated.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import posixpath
import re
import sqlite3
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codegraph_sci.core.bridge_catalog import MECHANISMS, NATIVE_BRIDGES
from codegraph_sci.core.graph import InventoryIssue, InventoryItem
from codegraph_sci.core.model import CALL_PATH
from codegraph_sci.core.plugins import decode_bytes
from codegraph_sci.query.types import (
    DEPENDENCY_LEVELS,
    DEPENDENCY_SORTS,
    REFERENCE_CATEGORIES,
    RELATIONSHIPS,
    CallerReport,
    CallSite,
    DataAccessView,
    DefaultRoots,
    DependencyEvidence,
    DependencyFilter,
    DependencyGroup,
    DependencyPage,
    DependencyRow,
    Direction,
    FileLink,
    Graph3D,
    Graph3DLink,
    Graph3DNode,
    GraphPath,
    GroupsReport,
    GroupSummary,
    ImpactReport,
    InventoryAccounting,
    InventoryReport,
    LanguageLine,
    Level,
    LinkItem,
    MainPathReport,
    NeighborsReport,
    NodeDetail,
    NodeSummary,
    NonCodeFile,
    NonCodeReport,
    Page,
    PathReport,
    PathStep,
    ReferenceCategories,
    ScanHealth,
    SiteGroup,
    SourceExcerpt,
    SubgraphEdge,
    SubgraphReport,
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
        evidence = site_evidence(stored=row[12], adapter=row[13], adapter_version=row[14], origin=row[6],
                                 resolution=row[8], confidence=row[7], candidates=int(row[15] or 0))
        return CallSite(file=row[0], line=row[1], col=row[2], target_text=row[3], ref_kind=row[4], condition=row[5],
                        origin=row[6], confidence=row[7], resolution=row[8], src=row[9], dst=row[10],
                        evidence=evidence)

    # ------------------------------------------------- dependency tables
    def _dependency_where(self, f: DependencyFilter) -> tuple[str, list[Any]]:
        where: list[str] = []
        args: list[Any] = []
        if f.text:
            like = "%" + f.text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(lower(caller) LIKE ? ESCAPE '\\' OR lower(target_text) LIKE ? ESCAPE '\\' "
                         "OR lower(coalesce(target, '')) LIKE ? ESCAPE '\\' OR lower(caller_file) LIKE ? ESCAPE '\\')")
            args += [like] * 4
        for column, values in (("relationship", f.relationships), ("resolution", f.statuses)):
            if values:
                unknown = sorted(set(values) - set(RELATIONSHIPS if column == "relationship" else RESOLUTION_NAMES))
                if unknown:
                    raise QueryError(f"unknown {column}: {', '.join(unknown)}")
                where.append(f"{column} IN ({','.join('?' * len(values))})")
                args += list(values)
        for column, value in (("caller_lang", f.language), ("caller", f.caller), ("target", f.target),
                              ("caller_file", f.caller_file), ("target_file", f.target_file)):
            if value is not None:
                where.append(f"{column} = ?")
                args.append(value)
        for column, value in (("caller_file", f.path), ("rule", f.rule)):
            if value:
                where.append(f"substr({column}, 1, ?) = ?")
                args += [len(value), value]
        for column, value in (("caller_file", f.caller_dir), ("target_file", f.target_dir)):
            if value is not None:
                where.append(f"{_DIR.format(column)} = ?")
                args.append(value)
        return (" WHERE " + " AND ".join(where)) if where else "", args

    def dependencies(self, filters: DependencyFilter | None = None, *, sort: str = "path", descending: bool = False,
                     limit: int = 200, offset: int = 0) -> DependencyPage:
        """One row per relationship occurrence (call sites and binding declarations), filtered, sorted and paged
        by SQLite."""
        if sort not in _DEPENDENCY_ORDER:
            raise QueryError(f"unknown sort key {sort!r} (expected one of {', '.join(DEPENDENCY_SORTS)})")
        where, args = self._dependency_where(filters or DependencyFilter())
        direction = " DESC" if descending else ""
        order = ", ".join(f"{c}{direction}" for c in _DEPENDENCY_ORDER[sort])
        total = self.con.execute(f"{_DEPENDENCIES} SELECT count(*) FROM deps{where}", args).fetchone()[0]
        rows = self.con.execute(f"{_DEPENDENCIES} SELECT {_DEP_COLUMNS} FROM deps{where} ORDER BY {order} "
                                "LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        ids = [r[0] for r in rows if r[0] is not None]
        candidates: dict[int, list[str]] = defaultdict(list)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for site_id, uid in self.con.execute(
                    "SELECT c.site_id, n.uid FROM call_site_candidates c JOIN nodes n ON n.id = c.dst_node "
                    f"WHERE c.site_id IN ({','.join('?' * len(chunk))}) ORDER BY n.uid", chunk):
                candidates[site_id].append(uid)
        out = [DependencyRow(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], candidates.get(r[0], []) if r[0] else [],
                             r[8], r[9], r[10], r[11], r[12], r[13], r[14], r[15], r[16]) for r in rows]
        return DependencyPage(total, offset, out)

    def dependency_groups(self, level: str, filters: DependencyFilter | None = None, *, sort: str = "source",
                          descending: bool = False, limit: int = 200, offset: int = 0) -> DependencyPage:
        """Rows aggregated per (source, target, relationship) at the ``entity``, ``file`` or ``directory`` level,
        each with its count, its statuses and the filter that lists its occurrences."""
        if level not in DEPENDENCY_LEVELS:
            raise QueryError(f"unknown level {level!r} (expected one of {', '.join(DEPENDENCY_LEVELS)})")
        if sort not in ("source", "target", "relationship", "count"):
            raise QueryError(f"unknown sort key {sort!r} (expected source, target, relationship or count)")
        src, dst = {"entity": ("caller", "target"), "file": ("caller_file", "target_file"),
                    "directory": (_DIR.format("caller_file"), f"CASE WHEN target_file IS NULL THEN NULL ELSE "
                                                             f"{_DIR.format('target_file')} END")}[level]
        where, args = self._dependency_where(filters or DependencyFilter())
        statuses = ", ".join(f"sum(resolution = '{r}')" for r in RESOLUTION_NAMES)
        grouped = (f"{_DEPENDENCIES} SELECT {src} AS g_src, {dst} AS g_dst, relationship, count(*) AS n, {statuses} "
                   f"FROM deps{where} GROUP BY g_src, g_dst, relationship")
        total = self.con.execute(f"SELECT count(*) FROM ({grouped})", args).fetchone()[0]
        direction = " DESC" if descending else ""
        order = {"source": "g_src", "target": "g_dst", "relationship": "relationship", "count": "n"}[sort]
        rows = self.con.execute(f"{grouped} ORDER BY {order}{direction}, g_src, g_dst, relationship LIMIT ? OFFSET ?",
                                (*args, limit, offset)).fetchall()
        base = filters or DependencyFilter()
        out = []
        for g_src, g_dst, relationship, n, *counts in rows:
            keys: dict[str, Any] = {"relationships": (relationship,)}
            if level == "entity":
                keys.update(caller=g_src, target=g_dst)
            elif level == "file":
                keys.update(caller_file=g_src, target_file=g_dst)
            else:
                keys.update(caller_dir=g_src, target_dir=g_dst)
            occurrences = dataclasses.replace(base, **keys)
            if g_dst is None:  # no resolved target: an exact NULL cannot be filtered, list them by status instead
                occurrences = dataclasses.replace(occurrences, target=None, target_file=None, target_dir=None,
                                                  statuses=tuple(r for r in RESOLUTION_NAMES if r != "resolved"
                                                                 and r != "out_of_scope"))
            out.append(DependencyGroup(level, g_src, g_dst, relationship, n,
                                       {r: int(c or 0) for r, c in zip(RESOLUTION_NAMES, counts, strict=True) if c},
                                       occurrences))
        return DependencyPage(total, offset, out)

    def dependency_evidence(self, row: DependencyRow, context: int = 3) -> DependencyEvidence:
        """The source lines around a row and its evidence (extraction rule, resolution rule, reason…)."""
        if row.site_id is not None:
            site = self.con.execute(self._SITE_COLS + "WHERE s.id = ?", (row.site_id,)).fetchone()
            evidence = self._site(site).evidence if site is not None else {}
        else:
            adapter = self.con.execute("SELECT adapter, adapter_version FROM files WHERE path = ?",
                                       (row.caller_file,)).fetchone()
            evidence = {"extraction": (f"{adapter[0] if ':' in (adapter[0] or ':') else 'native:' + adapter[0]}"
                                       f"@{adapter[1]}") if adapter and adapter[0] else None,
                        "resolution_rule": row.rule, "candidate_selection": "single target",
                        "reason": "binding declaration matched by a declaration pattern of a bridge rule"}
        start = max(1, row.line - context)
        excerpt = self.source(f"file:{row.caller_file}", start, row.line + context)
        return DependencyEvidence(row, evidence, excerpt)

    def bridges(self) -> list[dict[str, Any]]:
        """Bridges used by the last analysis: native ones with their declaration (``core.bridge_catalog``), and
        rule bridges with their identifier and version."""
        out: list[dict[str, Any]] = []
        for name, kind, version in self.con.execute(
                "SELECT name, type, version FROM plugins WHERE type IN ('bridge', 'bridge_rule') ORDER BY type, name"):
            spec = next((b for b in NATIVE_BRIDGES if b.id == name), None) if kind == "bridge" else None
            entry: dict[str, Any] = {"id": name, "type": kind, "version": version}
            if spec is not None:
                entry.update(source_languages=list(spec.source_languages), target_languages=list(spec.target_languages),
                             mechanisms={m: MECHANISMS[m].evidence for m in spec.mechanisms},
                             matching=spec.matching, transform=spec.transform, constraints=spec.constraints,
                             candidates=spec.candidates, description=spec.description)
            out.append(entry)
        return out

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
        for (ext,) in self.con.execute("SELECT extension FROM inventory_entries WHERE kind = 'file' "
                                       "AND reason = 'unknown language'"):
            unknown[(ext or "").lower() or "(none)"] += 1
        total = self.con.execute("SELECT count(*) FROM files").fetchone()[0]
        return InventoryReport(langs, dict(sorted(unknown.items())), total)

    def inventory_entries(self, parent: str | None = None, *, eligibility: str | None = None,
                          kind: str | None = None, limit: int = 1000, offset: int = 0) -> list[InventoryItem]:
        """Discovered entries sorted by path, optionally those directly in ``parent`` ("." for the root)."""
        where, args = [], []
        for column, value in (("parent", parent), ("eligibility", eligibility), ("kind", kind)):
            if value is not None:
                where.append(f"{column} = ?")
                args.append(value)
        sql = ("SELECT path, parent, kind, extension, size, files, lang, variant, confidence, evidence, eligibility, "
               "status, reason, link_target FROM inventory_entries"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY path LIMIT ? OFFSET ?")
        return [InventoryItem(*row) for row in self.con.execute(sql, (*args, limit, offset))]

    def inventory_issues(self) -> list[InventoryIssue]:
        """Discovery problems of the last analysis: unreadable entries, link loops, broken or external links."""
        return [InventoryIssue(*row) for row in self.con.execute(
            "SELECT path, kind, message FROM inventory_issues ORDER BY path, kind, message")]

    def inventory_accounting(self) -> InventoryAccounting:
        """How every discovered entry was handled: counts by kind, eligibility, status and reason."""
        def counts(column: str) -> dict[str, int]:
            return {str(k): int(n) for k, n in self.con.execute(
                f"SELECT {column}, count(*) FROM inventory_entries WHERE {column} IS NOT NULL "  # noqa: S608
                f"GROUP BY {column} ORDER BY {column}")}

        row = self.con.execute("SELECT stats FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        policy = str((json.loads(row[0] or "{}") if row else {}).get("inventory_policy", "analysis"))
        total = self.con.execute("SELECT count(*) FROM inventory_entries").fetchone()[0]
        issues = self.con.execute("SELECT count(*) FROM inventory_issues").fetchone()[0]
        return InventoryAccounting(policy, total, counts("kind"), counts("eligibility"), counts("status"),
                                   counts("reason"), issues)

    def files(self) -> list[dict[str, Any]]:
        """Every file with its language, status, number of routines and of linked files (explorer)."""
        routines = dict(self.con.execute(
            "SELECT file_id, count(*) FROM nodes WHERE kind = 'routine' GROUP BY file_id").fetchall())
        links: dict[int, int] = defaultdict(int)
        for a, b, _n in self.con.execute("SELECT src_file, dst_file, count FROM file_edges"):
            links[a] += 1
            links[b] += 1
        return [{"path": p, "lang": lang, "status": status, "routines": routines.get(fid, 0),
                 "links": links.get(fid, 0)}
                for fid, p, lang, status in self.con.execute(
                    "SELECT id, path, lang, parse_status FROM files ORDER BY path")]

    def file_symbols(self, path: str) -> list[NodeSummary]:
        rows = self.con.execute(_SUMMARY + "WHERE f.path = ? AND n.kind NOT IN ('file') ORDER BY n.line_start, n.uid",
                                (path,)).fetchall()
        return [self._summary(r) for r in rows]

    def sites_in_file(self, path: str) -> list[CallSite]:
        rows = self.con.execute(self._SITE_COLS + "WHERE f.path = ? ORDER BY s.line, s.col", (path,)).fetchall()
        return [self._site(r) for r in rows]

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
                  "s.resolution, src.uid, dst.uid, s.id, s.evidence, f.adapter, f.adapter_version, "
                  "(SELECT count(*) FROM call_site_candidates k WHERE k.site_id = s.id) "
                  "FROM call_sites s JOIN files f ON f.id = s.file_id "
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
        ambiguous = self.con.execute(
            "SELECT count(DISTINCT s.id) FROM call_site_candidates c JOIN call_sites s ON s.id = c.site_id "
            "WHERE c.dst_node = ? AND s.resolution = 'ambiguous'", (node_id,)).fetchone()[0]
        return CallerReport(self._summary_by_id(node_id), len(items), len(files),
                            sum(len(i.sites) for i in items), items, hidden, 0, int(ambiguous))

    def callees(self, uid: str, *, hide_noise: bool = True) -> CallerReport:
        node_id = self._id(uid)
        items, hidden = self._links(node_id, Direction.CALLEES, hide_noise)
        files = {i.node.file for i in items if i.node.file}
        open_sites = dict(self.con.execute(
            "SELECT resolution, count(*) FROM call_sites WHERE src_node = ? AND resolution IN "
            "('unresolved', 'ambiguous') GROUP BY resolution", (node_id,)).fetchall())
        return CallerReport(self._summary_by_id(node_id), len(items), len(files),
                            sum(len(i.sites) for i in items), items, hidden,
                            int(open_sites.get("unresolved", 0)), int(open_sites.get("ambiguous", 0)))

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

    def reference_categories(self) -> ReferenceCategories:
        """Non-resolved reference sites by category (corrective audit §10), first matching rule wins:

        ``external_known`` resolved to a recognised external symbol (C library, MPI, BLAS/LAPACK, HDF5, intrinsics,
        C++ standard library, Python standard library); ``out_of_scope`` defined outside the analysis scope;
        ``ambiguous`` several candidates; ``dynamic`` dynamic call (procedure pointer, dummy procedure) or Python
        attribute call whose target is only known at run time; ``parser_limitation`` site of a file analysed by the
        fallback extractor, or C/C++ member call whose receiver type the analysis does not infer; ``unknown``
        everything else, including imports and includes not found and Python modules
        outside the standard library (assumed third-party, not verified). No site is left out; the resolution stored
        for each site is unchanged.
        """
        import sys

        stdlib = set(sys.stdlib_module_names)
        rows = self.con.execute(
            "SELECT s.resolution, s.ref_kind, s.target_text, f.path, f.lang, f.parse_status, s.line, d.uid "
            "FROM call_sites s LEFT JOIN files f ON f.id = s.file_id LEFT JOIN nodes d ON d.id = s.dst_node "
            "WHERE s.resolution != 'resolved'").fetchall()
        counts = dict.fromkeys(REFERENCE_CATEGORIES, 0)
        by_kind: dict[str, dict[str, int]] = {c: {} for c in REFERENCE_CATEGORIES}
        examples: dict[str, list[str]] = {c: [] for c in REFERENCE_CATEGORIES}
        for resolution, kind, target, path, lang, status, line, dst in rows:
            python_attribute = lang == "python" and kind == "call" and "." in str(target)
            member_call = lang in ("c", "cpp") and ("." in str(target) or "->" in str(target))
            if resolution == "external" and dst is None:
                cat = "dynamic" if python_attribute else "parser_limitation" if member_call else "unknown"
            elif resolution == "external" and str(dst).startswith("ext:python:"):
                root_module = str(dst)[len("ext:python:"):].split(".", 1)[0]
                cat = "external_known" if root_module in stdlib else "unknown"
            elif resolution == "external":
                cat = "external_known"
            elif resolution == "out_of_scope":
                cat = "out_of_scope"
            elif resolution == "ambiguous":
                cat = "ambiguous"
            elif kind == "dynamic_call" or python_attribute:
                cat = "dynamic"
            elif status in ("fallback", "failed"):
                cat = "parser_limitation"
            else:
                cat = "unknown"
            counts[cat] += 1
            by_kind[cat][kind] = by_kind[cat].get(kind, 0) + 1
            examples[cat].append(f"{path}:{line} {target}")
        kinds = ",".join(f"'{k}'" for k in CALL_REFS)
        calls = self.con.execute(f"SELECT count(*) FROM call_sites WHERE ref_kind IN ({kinds})").fetchone()[0]
        refs = self.con.execute("SELECT count(*) FROM call_sites").fetchone()[0]
        return ReferenceCategories(counts, {c: dict(sorted(k.items())) for c, k in by_kind.items()},
                                   {c: sorted(e)[:5] for c, e in examples.items()}, int(calls), int(refs))

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

    # ---------------------------------------------------- treegraph helpers
    def default_roots(self, *, hide_noise: bool = True) -> DefaultRoots:
        """Detect the main starting routine and main starting file of the project deterministically."""
        rows = self.con.execute(
            "SELECT n.id, n.uid, n.display_name, n.kind, n.subtype, n.lang, f.path, n.line_start, "
            "COALESCE(s.fan_in, 0), COALESCE(s.fan_out, 0), COALESCE(s.is_noise, 0), "
            "COALESCE(s.fan_out_filtered, 0), COALESCE(s.impact_size, 0), COALESCE(n.in_scope, 1) "
            "FROM nodes n LEFT JOIN files f ON f.id = n.file_id LEFT JOIN node_stats s ON s.node_id = n.id "
            "WHERE n.kind IN ('routine', 'entry_point')"
        ).fetchall()

        def rank(row: tuple[Any, ...]) -> tuple[int, int, int, int, int, int, int, str]:
            uid = str(row[1])
            name = str(row[2]).lower()
            kind = str(row[3])
            subtype = row[4]
            path = str(row[6] or "")
            fan_in = int(row[8])
            fan_out = int(row[9])
            is_noise = bool(row[10])
            fan_out_f = int(row[11])
            impact = int(row[12])
            in_scope = bool(row[13])
            base = path.rsplit("/", 1)[-1].lower() if path else ""
            stem = base.split(".", 1)[0]
            is_main_sym = (
                subtype == "f_program"
                or kind == "entry_point"
                or name in ("main", "__main__")
                or uid.lower().endswith((":main", ".main", "::main"))
            )
            is_main_file = stem in ("main", "run", "driver", "app", "start", "cli", "init") or base.startswith(
                ("main_", "run_", "driver_")
            )
            if is_main_sym and fan_out > 0:
                tier = 0
            elif is_main_sym:
                tier = 1
            elif is_main_file and fan_in == 0 and fan_out > 0:
                tier = 2
            elif fan_in == 0 and fan_out > 0:
                tier = 3
            elif is_main_file and fan_out > 0:
                tier = 4
            elif fan_out > 0:
                tier = 5
            else:
                tier = 6
            return (
                0 if in_scope else 1,
                1 if (hide_noise and is_noise) else 0,
                tier,
                -fan_out_f,
                -fan_out,
                fan_in,
                -impact,
                uid,
            )

        ordered = sorted(rows, key=rank)
        candidates = [self._summary(r[:11]) for r in ordered[:10]]
        main_routine = candidates[0] if candidates else None
        main_file: NodeSummary | None = None
        if main_routine is not None and main_routine.file:
            f_uid = f"file:{main_routine.file}"
            f_row = self.con.execute(_SUMMARY + "WHERE n.uid = ?", (f_uid,)).fetchone()
            if f_row is not None:
                main_file = self._summary(f_row)
            else:
                main_file = NodeSummary(
                    f_uid, main_routine.file.rsplit("/", 1)[-1], "file", None,
                    main_routine.lang, main_routine.file, 1,
                )
        if main_file is None:
            f_rows = self.con.execute(
                "SELECT f.path, f.lang, COALESCE(sum(e.count), 0) AS out_cnt "
                "FROM files f LEFT JOIN file_edges e ON e.src_file = f.id "
                "GROUP BY f.id ORDER BY out_cnt DESC, f.path ASC LIMIT 1"
            ).fetchone()
            if f_rows is not None:
                p, lang, out_cnt = str(f_rows[0]), f_rows[1], int(f_rows[2])
                main_file = NodeSummary(f"file:{p}", p.rsplit("/", 1)[-1], "file", None, lang, p, 1, 0, out_cnt)
        return DefaultRoots(main_routine=main_routine, main_file=main_file, routine_candidates=candidates)

    def _tree_item_for(self, uid: str, level: Level) -> TreeItem:
        if level is Level.DIRECTORY or uid.startswith("dir:"):
            d = uid[4:] if uid.startswith("dir:") else uid
            has_c = (
                self.con.execute("SELECT 1 FROM dir_edges WHERE src_dir = ? OR dst_dir = ? LIMIT 1", (d, d)).fetchone()
                is not None
            )
            norm = f"dir:{d}" if d != "." and not uid.startswith("dir:") else uid
            return TreeItem(norm, d, "directory", None, None, "root", 0, "exact", False, has_c)
        if level is Level.FILE or uid.startswith("file:"):
            path = uid[5:] if uid.startswith("file:") else uid
            row = self.con.execute("SELECT id, lang FROM files WHERE path = ?", (path,)).fetchone()
            if row is None:
                raise QueryError(f"unknown file: {path}")
            fid, lang = int(row[0]), row[1]
            has_c = (
                self.con.execute(
                    "SELECT 1 FROM file_edges WHERE src_file = ? OR dst_file = ? LIMIT 1", (fid, fid)
                ).fetchone()
                is not None
            )
            return TreeItem(f"file:{path}", path.rsplit("/", 1)[-1], "file", lang, path, "root", 0, "exact",
                            False, has_c)
        row = self.con.execute(_SUMMARY + "WHERE n.uid = ?", (uid,)).fetchone()
        if row is None:
            raise QueryError(f"unknown symbol: {uid}")
        s = self._summary(row)
        return TreeItem(
            s.uid, s.display_name, s.kind, s.lang, s.file, "root", 0, "exact",
            False, (s.fan_in + s.fan_out) > 0, s.is_noise,
        )

    def initial_subgraph(
        self,
        root_uid: str | None = None,
        *,
        level: Level = Level.ROUTINE,
        max_nodes: int = 25,
        hide_noise: bool = True,
    ) -> SubgraphReport:
        """Breadth-first subgraph of the first ``max_nodes`` nodes starting from ``root_uid`` (or ``main``)."""
        if root_uid is None:
            roots = self.default_roots(hide_noise=hide_noise)
            if level is Level.ROUTINE:
                if roots.main_routine is None:
                    raise QueryError("no routine in database")
                root_uid = roots.main_routine.uid
            elif level is Level.FILE:
                if roots.main_file is None:
                    raise QueryError("no file in database")
                root_uid = roots.main_file.uid
            else:
                path = roots.main_file.file if roots.main_file and roots.main_file.file else "."
                root_uid = path.rsplit("/", 1)[0] if "/" in path else "."
        root_item = self._tree_item_for(root_uid, level)
        nodes: dict[str, TreeItem] = {root_item.uid: root_item}
        edges: list[SubgraphEdge] = []
        seen_edges: set[tuple[str, str]] = set()
        queue: deque[str] = deque([root_item.uid])
        truncated = False
        hidden_total = 0
        max_n = max(1, max_nodes)
        while queue:
            curr = queue.popleft()
            page = self.children(
                curr, direction=Direction.CALLEES, level=level, offset=0, limit=max(50, max_n * 2), hide_noise=hide_noise
            )
            hidden_total += page.hidden
            for child in page.items:
                if child.uid not in nodes:
                    if len(nodes) >= max_n:
                        truncated = True
                        continue
                    nodes[child.uid] = child
                    queue.append(child.uid)
                if (curr, child.uid) not in seen_edges:
                    seen_edges.add((curr, child.uid))
                    edges.append(SubgraphEdge(curr, child.uid, child))
        return SubgraphReport(
            root=root_item, nodes=nodes, edges=edges, truncated=truncated, hidden_noise=hidden_total
        )

    def connected_neighbors(
        self, uid: str, *, level: Level = Level.ROUTINE, limit: int = 50, hide_noise: bool = True
    ) -> NeighborsReport:
        """All direct callers and callees of ``uid`` (routine, file, or directory)."""
        center = self._tree_item_for(uid, level)
        callers = self.children(
            center.uid, direction=Direction.CALLERS, level=level, offset=0, limit=limit, hide_noise=hide_noise
        )
        callees = self.children(
            center.uid, direction=Direction.CALLEES, level=level, offset=0, limit=limit, hide_noise=hide_noise
        )
        return NeighborsReport(
            center=center,
            callers=callers.items,
            callees=callees.items,
            hidden_noise=callers.hidden + callees.hidden,
        )

    def _file_paths(self, src_uid: str, dst_uid: str, *, k: int = 5, max_len: int = 15) -> PathReport:
        src_path = src_uid[5:] if src_uid.startswith("file:") else src_uid
        dst_path = dst_uid[5:] if dst_uid.startswith("file:") else dst_uid
        s_row = self.con.execute("SELECT id FROM files WHERE path = ?", (src_path,)).fetchone()
        d_row = self.con.execute("SELECT id FROM files WHERE path = ?", (dst_path,)).fetchone()
        if s_row is None or d_row is None:
            raise QueryError(f"unknown file: {src_uid if s_row is None else dst_uid}")
        src, dst = int(s_row[0]), int(d_row[0])
        rev_adj: dict[int, list[tuple[int, str]]] = defaultdict(list)
        fwd_adj: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for sf, df, kind in self.con.execute("SELECT src_file, dst_file, kind FROM file_edges ORDER BY src_file, dst_file"):
            fwd_adj[int(sf)].append((int(df), str(kind)))
            rev_adj[int(df)].append((int(sf), str(kind)))
        dist = {dst: 0}
        queue = deque([dst])
        while queue:
            v = queue.popleft()
            if dist[v] >= max_len:
                continue
            for w, _kind in rev_adj.get(v, []):
                if w not in dist:
                    dist[w] = dist[v] + 1
                    queue.append(w)
        if src not in dist:
            return PathReport([], False)
        found: list[list[tuple[int, str | None]]] = []
        frontier: deque[list[tuple[int, str | None]]] = deque([[(src, None)]])
        while frontier and len(found) < k:
            path = frontier.popleft()
            v = path[-1][0]
            if v == dst:
                found.append(path)
                continue
            for w, kind in fwd_adj.get(v, []):
                if w not in dist or any(p[0] == w for p in path) or len(path) + dist[w] > max_len + 1:
                    continue
                frontier.append(path + [(w, kind)])
        path_of = dict(self.con.execute("SELECT id, path FROM files").fetchall())
        out = [
            GraphPath([PathStep(f"file:{path_of[fid]}", kind, "exact" if kind else None, False) for fid, kind in p])
            for p in found
        ]
        return PathReport(out, bool(frontier) and len(found) >= k)

    def paths_from_main(
        self,
        target_uid: str,
        *,
        root_uid: str | None = None,
        level: Level = Level.ROUTINE,
        max_paths: int = 4,
        max_len: int = 15,
    ) -> MainPathReport:
        """Paths from ``main`` to ``target_uid``; if more than ``max_paths`` exist, returns the shortest path."""
        is_file = level is Level.FILE or target_uid.startswith("file:")
        if root_uid is None:
            roots = self.default_roots()
            if is_file:
                root_uid = roots.main_file.uid if roots.main_file else target_uid
            else:
                root_uid = roots.main_routine.uid if roots.main_routine else target_uid
        if is_file and not target_uid.startswith("file:"):
            target_uid = f"file:{target_uid}"
        if is_file and not root_uid.startswith("file:"):
            root_uid = f"file:{root_uid}"
        if target_uid == root_uid:
            return MainPathReport(
                root_uid=root_uid,
                target_uid=target_uid,
                paths=[GraphPath([PathStep(target_uid, None, None, False)])],
                total_found=1,
                multiple_possible=False,
                showing_shortest_only=False,
                truncated=False,
            )
        if is_file:
            rep = self._file_paths(root_uid, target_uid, k=max_paths + 1, max_len=max_len)
        else:
            rep = self.paths(root_uid, target_uid, k=max_paths + 1, max_len=max_len)
            if not rep.paths:
                imp = self.impact(target_uid, max_depth=max_len)
                for ep in imp.entry_points:
                    cand = self.paths(ep, target_uid, k=max_paths + 1, max_len=max_len)
                    if cand.paths:
                        root_uid = ep
                        rep = cand
                        break
        total = len(rep.paths)
        multiple = total > 1 or rep.truncated
        shortest_only = total > max_paths or (rep.truncated and total > 1)
        chosen = rep.paths[:1] if shortest_only else rep.paths[:max_paths]
        return MainPathReport(
            root_uid=root_uid,
            target_uid=target_uid,
            paths=chosen,
            total_found=total,
            multiple_possible=multiple,
            showing_shortest_only=shortest_only,
            truncated=rep.truncated,
        )


    # ------------------------------------------------------------- 3D view
    def graph3d(self, root_uid: str, *, mode: str = "functions", depth: int = 2, max_nodes: int = 400,
                hide_noise: bool = True) -> Graph3D:
        """Bounded neighbourhood of ``root_uid`` for the 3D view, callers and callees alike.

        ``mode``: ``functions`` (call graph), ``files`` (file links) or ``both`` (functions, the files that
        define them, and the links between those files). Breadth-first, ``depth`` levels, at most
        ``max_nodes`` nodes; deterministic (sorted nodes and links).
        """
        if mode not in ("functions", "files", "both"):
            raise QueryError(f"unknown 3D mode: {mode}")
        level = Level.FILE if mode == "files" else Level.ROUTINE
        if root_uid.startswith("file:"):
            if level is Level.ROUTINE:
                raise QueryError("a file root needs the 'files' mode")
            start = root_uid
        else:
            detail = self.node(root_uid)
            if level is Level.FILE:
                if not detail.file:
                    raise QueryError(f"{root_uid} has no file")
                start = f"file:{detail.file}"
            else:
                start = detail.uid
        nodes: dict[str, Graph3DNode] = {}
        links: dict[tuple[str, str, str], Graph3DLink] = {}
        truncated = False
        hidden = 0

        def add_node(uid: str) -> bool:
            nonlocal truncated
            if uid in nodes:
                return True
            if len(nodes) >= max(1, max_nodes):
                truncated = True
                return False
            nodes[uid] = self._node3d(uid, uid == start)
            return True

        add_node(start)
        frontier = [start]
        for _ in range(max(0, depth)):
            next_frontier: list[str] = []
            for uid in frontier:
                for direction in (Direction.CALLERS, Direction.CALLEES):
                    page = self.children(uid, direction=direction, level=level, limit=max(50, max_nodes),
                                         hide_noise=hide_noise)
                    hidden += page.hidden
                    for item in page.items:
                        is_new = item.uid not in nodes
                        if not add_node(item.uid):
                            continue
                        if is_new:
                            next_frontier.append(item.uid)
                        src, dst = (item.uid, uid) if direction is Direction.CALLERS else (uid, item.uid)
                        key = (src, dst, item.edge_kind)
                        if key not in links:
                            links[key] = Graph3DLink(src, dst, item.edge_kind, item.count, item.confidence)
            frontier = sorted(set(next_frontier))
            if not frontier:
                break
        if mode == "both":
            self._files_layer(nodes, links, add_node)
        return self._finish(start, mode, nodes, links, truncated=truncated, hidden_noise=hidden)

    def _files_layer(self, nodes: dict[str, Graph3DNode], links: dict[tuple[str, str, str], Graph3DLink],
                     add_node: Callable[[str], bool]) -> None:
        """Mode ``both``: the files defining the shown routines, and the links between those files."""
        routine_files = sorted({(n.file, n.id) for n in nodes.values() if n.file and n.kind != "file"})
        for path, uid in routine_files:
            fid = f"file:{path}"
            if add_node(fid):
                links[(fid, uid, "defines")] = Graph3DLink(fid, uid, "defines", 1, "exact")
        paths = {n.file for n in nodes.values() if n.kind == "file" and n.file}
        if paths:
            mark = ",".join("?" * len(paths))
            for a, b, kind, count in self.con.execute(
                    f"SELECT fa.path, fb.path, e.kind, e.count FROM file_edges e JOIN files fa ON fa.id = e.src_file "
                    f"JOIN files fb ON fb.id = e.dst_file WHERE fa.path IN ({mark}) AND fb.path IN ({mark})",
                    (*sorted(paths), *sorted(paths))):
                links[(f"file:{a}", f"file:{b}", kind)] = Graph3DLink(f"file:{a}", f"file:{b}", kind, count,
                                                                   "exact")

    def graph3d_main_paths(self, target_uid: str, *, mode: str = "functions", max_paths: int = 3,
                           max_len: int = 15) -> tuple[Graph3D, MainPathReport]:
        """The paths from ``main`` to ``target_uid`` as a 3D graph (shortest path only when there are many)."""
        if mode not in ("functions", "files", "both"):
            raise QueryError(f"unknown 3D mode: {mode}")
        level = Level.FILE if mode == "files" else Level.ROUTINE
        if level is Level.FILE and not target_uid.startswith("file:"):
            detail = self.node(target_uid)
            if not detail.file:
                raise QueryError(f"{target_uid} has no file")
            target_uid = f"file:{detail.file}"
        report = self.paths_from_main(target_uid, level=level, max_paths=max_paths, max_len=max_len)
        root = report.paths[0].steps[0].uid if report.paths else report.target_uid
        nodes: dict[str, Graph3DNode] = {}
        links: dict[tuple[str, str, str], Graph3DLink] = {}

        def add_node(uid: str) -> bool:
            if uid not in nodes:
                nodes[uid] = self._node3d(uid, uid == root)
            return True

        add_node(report.target_uid)
        for path in report.paths:
            for prev, step in zip(path.steps, path.steps[1:], strict=False):
                add_node(prev.uid)
                add_node(step.uid)
                kind = step.edge_kind or "calls"
                links[(prev.uid, step.uid, kind)] = Graph3DLink(prev.uid, step.uid, kind, 1,
                                                                step.confidence or "exact")
            add_node(path.steps[0].uid)
        if mode == "both":
            self._files_layer(nodes, links, add_node)
        graph = self._finish(root, mode, nodes, links, truncated=report.truncated)
        return graph, report

    def _node3d(self, uid: str, is_root: bool) -> Graph3DNode:
        if uid.startswith("file:"):
            path = uid[5:]
            row = self.con.execute("SELECT id, lang FROM files WHERE path = ?", (path,)).fetchone()
            if row is None:
                raise QueryError(f"unknown file: {path}")
            fan_out = self.con.execute("SELECT count(*) FROM file_edges WHERE src_file = ?", (row[0],)).fetchone()[0]
            fan_in = self.con.execute("SELECT count(*) FROM file_edges WHERE dst_file = ?", (row[0],)).fetchone()[0]
            return Graph3DNode(uid, path.rsplit("/", 1)[-1], "file", row[1], path, 1, fan_in, fan_out, is_root)
        row = self.con.execute(_SUMMARY + "WHERE n.uid = ?", (uid,)).fetchone()
        if row is None:
            raise QueryError(f"unknown symbol: {uid}")
        s = self._summary(row)
        return Graph3DNode(s.uid, s.display_name, s.kind, s.lang, s.file, s.line, s.fan_in, s.fan_out, is_root,
                           s.is_noise)

    # ------------------------------------------------------- 3D groups
    def _group_members(self, level: Level, hide_noise: bool) -> tuple[dict[str, tuple[str, str | None, str, int]],
                                                                     list[tuple[str, str]], int]:
        """Members ``uid -> (label, lang, path, degree)`` and undirected links of the grouping graph."""
        members: dict[str, tuple[str, str | None, str, int]] = {}
        pairs: list[tuple[str, str]] = []
        hidden = 0
        if level is Level.FILE:
            degree: dict[int, int] = defaultdict(int)
            raw = self.con.execute("SELECT src_file, dst_file FROM file_edges").fetchall()
            for a, b in raw:
                degree[int(a)] += 1
                degree[int(b)] += 1
            uid_of: dict[int, str] = {}
            for fid, path, lang in self.con.execute("SELECT id, path, lang FROM files"):
                uid_of[int(fid)] = f"file:{path}"
                members[f"file:{path}"] = (str(path).rsplit("/", 1)[-1], lang, str(path), degree.get(int(fid), 0))
            pairs = [(uid_of[int(a)], uid_of[int(b)]) for a, b in raw
                     if int(a) in uid_of and int(b) in uid_of and a != b]
            return members, pairs, 0
        uid_by_id: dict[int, str] = {}
        for nid, uid, name, lang, path, deg, noise in self.con.execute(
                "SELECT n.id, n.uid, n.display_name, n.lang, f.path, COALESCE(s.fan_in, 0) + COALESCE(s.fan_out, 0), "
                "COALESCE(s.is_noise, 0) FROM nodes n JOIN files f ON f.id = n.file_id "
                "LEFT JOIN node_stats s ON s.node_id = n.id WHERE n.kind IN ('routine', 'entry_point', 'binding')"):
            if hide_noise and noise:
                hidden += 1
                continue
            uid_by_id[int(nid)] = str(uid)
            members[str(uid)] = (str(name), lang, str(path), int(deg))
        kinds = sorted(CALL_PATH)
        for a, b in self.con.execute(f"SELECT src, dst FROM edges WHERE kind IN ({','.join('?' * len(kinds))})",
                                     kinds):
            if int(a) in uid_by_id and int(b) in uid_by_id and a != b:
                pairs.append((uid_by_id[int(a)], uid_by_id[int(b)]))
        return members, pairs, hidden

    def groups(self, level: Level = Level.ROUTINE, *, hide_noise: bool = True) -> GroupsReport:
        """Connected groups of routines (call links) or files (file links), whatever their folders.

        Separate groups are separate programs (or parallel ones); members linked to nothing are ``isolated``.
        Utility routines (noise) are left out when ``hide_noise``: they would glue unrelated programs together.
        """
        members, pairs, hidden = self._group_members(level, hide_noise)
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            root = x
            while parent.get(root, root) != root:
                root = parent[root]
            while parent.get(x, x) != root:
                parent[x], x = root, parent[x]
            return root

        for a, b in pairs:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        comps: dict[str, list[str]] = defaultdict(list)
        for uid in members:
            comps[find(uid)].append(uid)
        out: list[GroupSummary] = []
        isolated: list[str] = []
        for uids in comps.values():
            if len(uids) == 1:
                isolated.append(uids[0])
                continue
            uids.sort()
            rep = min(uids, key=lambda u: (-members[u][3], u))
            langs: dict[str, int] = defaultdict(int)
            dirs: dict[str, int] = defaultdict(int)
            for u in uids:
                langs[members[u][1] or "-"] += 1
                path = members[u][2]
                dirs[path.split("/", 1)[0] if "/" in path else "."] += 1
            top = sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))
            out.append(GroupSummary(f"group:{rep}", rep, members[rep][0], len(uids), uids,
                                    dict(sorted(langs.items())), top))
        out.sort(key=lambda g: (-g.size, g.representative))
        return GroupsReport("files" if level is Level.FILE else "functions", out, sorted(isolated), hidden)

    def _sphere(self, g: GroupSummary, unit: str) -> Graph3DNode:
        lang = max(g.langs.items(), key=lambda kv: (kv[1], kv[0]))[0]
        dirs = ", ".join(f"{d}/ {n}" for d, n in g.top_dirs[:4]) + (" …" if len(g.top_dirs) > 4 else "")
        langs = ", ".join(f"{k} {v}" for k, v in sorted(g.langs.items(), key=lambda kv: (-kv[1], kv[0])))
        return Graph3DNode(g.id, f"{g.label} +{g.size - 1}", "group", None if lang == "-" else lang, None, None,
                           0, 0, size=g.size, note=f"{g.size} {unit} · folders: {dirs} · {langs}")

    def _spheres(self, report: GroupsReport, start: int, limit: int, unit: str) -> list[Graph3DNode]:
        """Group spheres from ``start``; a "more" bucket when they do not all fit in ``limit`` nodes."""
        rest = report.groups[start:]
        if len(rest) <= limit:
            return [self._sphere(g, unit) for g in rest]
        shown = rest[:max(1, limit - 1)]
        left = rest[len(shown):]
        more = Graph3DNode(f"more:{report.level}:{start + len(shown)}", f"{len(left)} more groups", "more", None,
                           None, None, 0, 0, size=len(left),
                           note=f"{sum(g.size for g in left)} {unit} in smaller groups · click to show them")
        return [self._sphere(g, unit) for g in shown] + [more]

    def graph3d_overview(self, *, mode: str = "functions", max_nodes: int = 300, hide_noise: bool = True,
                         include_noncode: bool = True) -> Graph3D:
        """Everything at once: every node and link when it fits in ``max_nodes``, else one sphere per group.

        In ``files`` mode the files that are not analyzed code are added apart (``noncode`` nodes, no link).
        """
        if mode not in ("functions", "files", "both"):
            raise QueryError(f"unknown 3D mode: {mode}")
        level = Level.FILE if mode == "files" else Level.ROUTINE
        unit = "files" if level is Level.FILE else "functions"
        report = self.groups(level, hide_noise=hide_noise)
        total = sum(g.size for g in report.groups) + len(report.isolated)
        nodes: dict[str, Graph3DNode] = {}
        links: dict[tuple[str, str, str], Graph3DLink] = {}
        if total <= max_nodes:
            for uid in sorted([u for g in report.groups for u in g.members] + report.isolated):
                nodes[uid] = self._node3d(uid, False)
            self._links_among(level, nodes, links)
            if mode == "both":
                self._files_layer(nodes, links, lambda uid: True if uid in nodes else bool(
                    nodes.setdefault(uid, self._node3d(uid, False))))
        else:
            for n in self._spheres(report, 0, max(1, max_nodes - (1 if report.isolated else 0)), unit):
                nodes[n.id] = n
            if report.isolated:
                iso = f"isolated:{report.level}"
                nodes[iso] = Graph3DNode(iso, f"{len(report.isolated)} isolated", "isolated", None, None, None, 0, 0,
                                         size=len(report.isolated),
                                         note=f"{len(report.isolated)} {unit} linked to nothing · click to show them")
        if include_noncode and level is Level.FILE:
            for n in self._noncode_nodes():
                nodes[n.id] = n
        return self._finish("", mode, nodes, links, hidden_noise=report.hidden_noise)

    def _links_among(self, level: Level, nodes: dict[str, Graph3DNode],
                     links: dict[tuple[str, str, str], Graph3DLink]) -> None:
        """Every link whose two ends are drawn, inside a folder or between folders."""
        if level is Level.FILE:
            rows = self.con.execute("SELECT fa.path, fb.path, e.kind, e.count FROM file_edges e "
                                    "JOIN files fa ON fa.id = e.src_file JOIN files fb ON fb.id = e.dst_file")
            for a, b, kind, count in rows:
                src, dst = f"file:{a}", f"file:{b}"
                if src in nodes and dst in nodes and src != dst:
                    links[(src, dst, kind)] = Graph3DLink(src, dst, kind, int(count), "exact")
            return
        kinds = sorted(CALL_PATH)
        rows = self.con.execute(
            f"SELECT na.uid, nb.uid, e.kind, e.site_count, e.min_confidence FROM edges e JOIN nodes na ON na.id = e.src "
            f"JOIN nodes nb ON nb.id = e.dst WHERE e.kind IN ({','.join('?' * len(kinds))})", kinds)
        for a, b, kind, count, conf in rows:
            if a in nodes and b in nodes and a != b:
                links[(a, b, kind)] = Graph3DLink(a, b, kind, int(count), str(conf))

    def _finish(self, root: str, mode: str, nodes: dict[str, Graph3DNode],
                links: dict[tuple[str, str, str], Graph3DLink], **kwargs: Any) -> Graph3D:
        """``_finish3d`` plus what needs the database: definitions outside the analysis scope."""
        graph = _finish3d(root, mode, nodes, links, **kwargs)
        ids = [n.id for n in graph.nodes if ":" in n.id and not n.id.startswith(("file:", "dir:", "group:", "more:",
                                                                                    "isolated:", "noncode:"))]
        out: set[str] = set()
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            out |= {u for (u,) in self.con.execute(
                f"SELECT uid FROM nodes WHERE in_scope = 0 AND uid IN ({','.join('?' * len(chunk))})", chunk)}
        for node in graph.nodes:
            node.in_scope = node.id not in out
        for link in graph.links:
            if link.target in out and link.status == "resolved":
                link.status = "out_of_scope"
        graph.level = "file" if mode == "files" else "entity"
        return graph

    def graph3d_directories(self, *, max_nodes: int = 300) -> Graph3D:
        """Directory level (D34): one node per folder holding analyzed files, links aggregated between folders."""
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for path, lang in self.con.execute("SELECT path, lang FROM files"):
            counts[posixpath.dirname(path) or "."][lang or "-"] += 1
        ranked = sorted(counts, key=lambda d: (-sum(counts[d].values()), d))
        kept = ranked[:max_nodes]
        nodes: dict[str, Graph3DNode] = {}
        for d in kept:
            langs = counts[d]
            lang = max(sorted(langs), key=lambda k: langs[k])
            size = sum(langs.values())
            nodes[f"dir:{d}"] = Graph3DNode(f"dir:{d}", d.rsplit("/", 1)[-1] if d != "." else ".", "directory",
                                            None if lang == "-" else lang, None, None, 0, 0, size=size,
                                            note=", ".join(f"{k} {v}" for k, v in sorted(langs.items())),
                                            group=posixpath.dirname(d) or "." if d != "." else "")
        links: dict[tuple[str, str, str], Graph3DLink] = {}
        for a, b, kind, count in self.con.execute("SELECT src_dir, dst_dir, kind, count FROM dir_edges"):
            src, dst = f"dir:{a}", f"dir:{b}"
            if src in nodes and dst in nodes and src != dst:
                links[(src, dst, kind)] = Graph3DLink(src, dst, kind, int(count), "exact", cross_dir=True)
                nodes[src].fan_out += 1
                nodes[dst].fan_in += 1
        graph = _finish3d("", "directories", nodes, links, truncated=len(ranked) > max_nodes)
        graph.level = "directory"
        return graph

    @staticmethod
    def link_evidence(source: str, target: str) -> DependencyFilter:
        """Filter of the dependency rows behind a drawn link (D34): the table and the graph open the same evidence."""
        if source.startswith("dir:") and target.startswith("dir:"):
            return DependencyFilter(caller_dir=source[4:], target_dir=target[4:])
        if source.startswith("file:") and target.startswith("file:"):
            return DependencyFilter(caller_file=source[5:], target_file=target[5:])
        return DependencyFilter(caller=source, target=target)

    def graph3d_group(self, group_id: str, *, mode: str = "functions", max_nodes: int = 300,
                      hide_noise: bool = True) -> Graph3D:
        """Content of one overview node: a group (all its links), the isolated members, or the next groups."""
        level = Level.FILE if mode == "files" else Level.ROUTINE
        unit = "files" if level is Level.FILE else "functions"
        if group_id.startswith("group:"):
            return self.graph3d(group_id[6:], mode=mode, depth=10_000, max_nodes=max_nodes, hide_noise=hide_noise)
        if group_id.startswith("isolated:"):
            report = self.groups(level, hide_noise=hide_noise)
            iso_nodes = {u: self._node3d(u, False) for u in report.isolated[:max_nodes]}
            return self._finish(group_id, mode, iso_nodes, {}, truncated=len(report.isolated) > max_nodes,
                             hidden_noise=report.hidden_noise)
        if group_id.startswith("more:"):
            report = self.groups(level, hide_noise=hide_noise)
            start = int(group_id.rsplit(":", 1)[1])
            more_nodes = {n.id: n for n in self._spheres(report, start, max_nodes, unit)}
            return self._finish(group_id, mode, more_nodes, {}, hidden_noise=report.hidden_noise)
        raise QueryError(f"unknown group: {group_id}")

    def non_code_files(self) -> NonCodeReport:
        """Files of the repository that are not analyzed code (recorded by the last analysis)."""
        row = self.con.execute("SELECT stats FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        data = (json.loads(row[0] or "{}") if row else {}).get("non_code") or {}
        files = [NonCodeFile(str(p), str(c)) for p, c in data.get("files", [])]
        return NonCodeReport({str(k): int(v) for k, v in (data.get("counts") or {}).items()}, files,
                             bool(data.get("truncated", False)))

    def _noncode_nodes(self, limit: int = 500) -> list[Graph3DNode]:
        report = self.non_code_files()
        out = [Graph3DNode(f"noncode:{f.path}", f.path.rsplit("/", 1)[-1], "noncode", None, f.path, None, 0, 0,
                           note=f.category) for f in report.files[:limit]]
        hidden = sum(report.counts.values()) - len(out)
        if hidden > 0:
            out.append(Graph3DNode("noncode:…", f"{hidden} more", "noncode", None, None, None, 0, 0, size=hidden,
                                   note=", ".join(f"{k} {v}" for k, v in report.counts.items())))
        return out


RESOLUTION_NAMES = ("resolved", "ambiguous", "external", "out_of_scope", "unresolved")
# Directory of a path column ("." at the root): everything before the last "/".
_DIR = ("CASE WHEN instr({0}, '/') = 0 THEN '.' ELSE "
        "substr({0}, 1, length(rtrim({0}, replace({0}, '/', ''))) - 1) END")
_RELATIONSHIP = ("CASE WHEN s.origin LIKE 'bridge:pybind11%' OR s.origin LIKE 'bridge:python_extension%' "
                 "THEN 'binding' "
                 "WHEN s.origin LIKE 'bridge:%' AND s.ref_kind IN ('call', 'maybe_call', 'dynamic_call') THEN 'bridge' "
                 "WHEN s.ref_kind IN ('call', 'maybe_call') THEN 'call' "
                 "WHEN s.ref_kind = 'dynamic_call' THEN 'dynamic_call' WHEN s.ref_kind = 'use' THEN 'import' "
                 "WHEN s.ref_kind = 'include' THEN 'include' WHEN s.ref_kind = 'inherit' THEN 'inherit' "
                 "WHEN s.ref_kind = 'bind' THEN 'binding' ELSE s.ref_kind END")
# Every relationship occurrence: call sites, and binding declarations (``binds`` edges without call site).
_DEPENDENCIES = (
    "WITH deps AS ("
    "SELECT s.id AS site_id, src.uid AS caller, src.display_name AS caller_name, f.path AS caller_file, "
    "f.lang AS caller_lang, s.target_text AS target_text, dst.uid AS target, dst.display_name AS target_name, "
    f"tf.path AS target_file, tf.lang AS target_lang, {_RELATIONSHIP} AS relationship, s.line AS line, s.col AS col, "
    "s.resolution AS resolution, s.confidence AS confidence, s.origin AS rule, c.expr AS condition, "
    "s.file_id AS file_order "
    "FROM call_sites s JOIN nodes src ON src.id = s.src_node JOIN files f ON f.id = s.file_id "
    "LEFT JOIN nodes dst ON dst.id = s.dst_node LEFT JOIN files tf ON tf.id = dst.file_id "
    "LEFT JOIN conditions c ON c.id = s.condition_id "
    "UNION ALL "
    "SELECT NULL, src.uid, src.display_name, f.path, f.lang, src.display_name, dst.uid, dst.display_name, tf.path, "
    "tf.lang, 'binding_declaration', coalesce(src.line_start, 1), 1, 'resolved', e.min_confidence, "
    "coalesce(json_extract(e.origins, '$[0]'), 'rule'), NULL, f.id "
    "FROM edges e JOIN nodes src ON src.id = e.src JOIN nodes dst ON dst.id = e.dst "
    "JOIN files f ON f.id = src.file_id LEFT JOIN files tf ON tf.id = dst.file_id "
    "WHERE e.kind = 'binds' AND e.site_count = 0 AND src.kind = 'binding')")
_DEP_COLUMNS = ("site_id, caller, caller_name, caller_file, caller_lang, target_text, target, target_name, "
                "target_file, target_lang, relationship, line, col, resolution, confidence, rule, condition")
_DEPENDENCY_ORDER = {
    "path": ("file_order", "line", "col", "caller", "target_text"),
    "line": ("line", "file_order", "col", "caller", "target_text"),
    "caller": ("caller", "file_order", "line", "col", "target_text"),
    "target": ("coalesce(target, target_text)", "file_order", "line", "col", "caller"),
    "relationship": ("relationship", "file_order", "line", "col", "caller"),
    "status": ("resolution", "file_order", "line", "col", "caller"),
    "language": ("caller_lang", "file_order", "line", "col", "caller"),
    "rule": ("rule", "file_order", "line", "col", "caller"),
}

_REASONS = {
    ("resolved", "exact"): "single definition found by the language's name lookup",
    ("resolved", "resolved"): "target selected by a language rule (scope, signature, import or variant)",
    ("resolved", "heuristic"): "heuristic match (dynamic call, keyword language or name only)",
    ("out_of_scope", None): "target found outside the analysis scope",
    ("external", None): "known external library or module",
    ("ambiguous", None): "several possible targets; none was chosen",
    ("unresolved", None): "no target found",
}


def site_evidence(*, stored: str | None, adapter: str | None, adapter_version: str | None, origin: str,
                  resolution: str, confidence: str, candidates: int) -> dict[str, Any]:
    """Evidence of a call site: the extraction rule (adapter and version of the file), the resolution rule
    (origin), how the candidate was selected, the reason, and what a bridge recorded."""
    name = adapter if adapter is None or ":" in adapter else f"native:{adapter}"  # keyword adapters: keywords:<l>
    out: dict[str, Any] = {"extraction": f"{name}@{adapter_version}" if name else None,
                           "resolution_rule": origin,
                           "candidate_selection": (f"{candidates} candidates kept" if candidates
                                                   else "single target" if resolution in ("resolved", "out_of_scope")
                                                   else "none"),
                           "reason": _REASONS.get((resolution, confidence)) or _REASONS.get((resolution, None), "")}
    if stored:
        recorded = json.loads(stored)
        out.update(recorded)
        out["resolution_rule"] = origin
        if candidates and recorded.get("candidate_selection") == "keep_ambiguous":
            out["candidate_selection"] = "keep_ambiguous"
    return out


def _finish3d(root: str, mode: str, nodes: dict[str, Graph3DNode], links: dict[tuple[str, str, str], Graph3DLink],
              *, truncated: bool = False, hidden_noise: int = 0) -> Graph3D:
    """Sorted graph; links between two folders are marked ``cross_dir``; nodes get their folder as ``group``; links
    get a status (external target, ambiguous, or resolved)."""
    for node in nodes.values():
        if node.file and not node.group:
            node.group = posixpath.dirname(node.file) or "."
    for link in links.values():
        a, b = nodes.get(link.source), nodes.get(link.target)
        if a is not None and b is not None and a.file and b.file and link.kind != "defines":
            link.cross_dir = posixpath.dirname(a.file) != posixpath.dirname(b.file)
        if b is not None and b.kind == "external":
            link.status = "external"
        elif link.confidence == "ambiguous":
            link.status = "ambiguous"
    return Graph3D(root=root, mode=mode, nodes=sorted(nodes.values(), key=lambda n: n.id),
                   links=sorted(links.values(), key=lambda lk: (lk.source, lk.target, lk.kind)),
                   truncated=truncated, hidden_noise=hidden_noise)

