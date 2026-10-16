"""Global invariants (§2.1) and grouping of unresolved/ambiguous sites by pattern (diagnostic)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from codegraph_sci.audit.common import connect, rows
from codegraph_sci.query.api import site_pattern

CALL_KINDS = ("call", "maybe_call", "dynamic_call")


def unresolved_groups(db: Path, include_ambiguous: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    con = connect(db)
    try:
        states = ("unresolved", "ambiguous") if include_ambiguous else ("unresolved",)
        data = rows(con, "SELECT s.target_text AS target, s.resolution AS resolution, s.ref_kind AS ref_kind, "
                         "s.line AS line, f.path AS file, f.lang AS lang FROM call_sites s JOIN files f "
                         f"ON f.id = s.file_id WHERE s.resolution IN ({','.join('?' * len(states))}) "
                         "ORDER BY f.path, s.line, s.col", states)
    finally:
        con.close()
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in data:
        groups[(r["lang"] or "?", r["resolution"], site_pattern(r["target"]))].append(r)
    out: list[dict[str, Any]] = []
    for (lang, resolution, pattern), items in groups.items():
        out.append({"lang": lang, "resolution": resolution, "pattern": pattern, "count": len(items),
                    "files": len({i["file"] for i in items}),
                    "examples": [{"file": i["file"], "line": i["line"], "target": i["target"]} for i in items[:5]]})
    out.sort(key=lambda g: (-int(g["count"]), str(g["lang"]), str(g["pattern"])))
    return out[:limit]


def invariants(db: Path) -> dict[str, Any]:
    con = connect(db)
    try:
        files = rows(con, "SELECT parse_status AS status, count(*) AS n FROM files GROUP BY parse_status")
        dup = rows(con, "SELECT uid FROM nodes WHERE uid LIKE '%#%' AND kind = 'routine' ORDER BY uid")
        variants: dict[str, list[str]] = defaultdict(list)
        for r in rows(con, "SELECT n.uid AS uid, f.path AS path FROM nodes n JOIN files f ON f.id = n.file_id "
                           "WHERE n.kind = 'routine' ORDER BY n.uid"):
            variants[r["uid"].split("#")[0]].append(r["path"])
        duplicates = {k: sorted(set(v)) for k, v in variants.items() if len(set(v)) > 1}
        sites = rows(con, "SELECT resolution, count(*) AS n FROM call_sites "
                          f"WHERE ref_kind IN {CALL_KINDS} GROUP BY resolution")
        never_called = rows(con, "SELECT n.uid AS uid FROM nodes n JOIN node_stats s ON s.node_id = n.id "
                                 "WHERE n.kind = 'routine' AND s.fan_in = 0 AND n.in_scope = 1 ORDER BY n.uid")
        failed = rows(con, "SELECT path, parse_status AS status, error FROM files "
                           "WHERE parse_status IN ('failed', 'fallback') ORDER BY path")
    finally:
        con.close()
    by_res = {r["resolution"]: r["n"] for r in sites}
    total_calls = sum(by_res.values())
    return {
        "files_by_status": {r["status"]: r["n"] for r in files},
        "variant_uids": len(dup),
        "duplicate_definitions_across_files": duplicates,
        "call_sites_by_resolution": by_res,
        "unresolved_rate": by_res.get("unresolved", 0) / total_calls if total_calls else 0.0,
        "ambiguous_sites": by_res.get("ambiguous", 0),
        "never_called_routines": len(never_called),
        "never_called_examples": [r["uid"] for r in never_called[:20]],
        "failed_or_fallback_files": failed,
    }
