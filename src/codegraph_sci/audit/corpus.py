"""Real-code corpora (§5.4): manifest + expectations, checked against an analysis.

The sources of a corpus are never stored in the repository: the manifest says where they are
locally and at which exact revision.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.audit.common import connect, rows

SUPPORTED_LATER = {"hidden": 12, "writes": 12, "path": 9, "dispatches": 14, "catalog_links": 14, "tests_for": 14}


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("corpus", "source", "scope"):
        if key not in data:
            raise ValueError(f"{path}: key '{key}' is required")
    return data


def check_expectations(db: Path, expectations: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate each expectation; returns one result per item (ok / failed / not_supported)."""
    con = connect(db)
    try:
        uids = {r["uid"] for r in rows(con, "SELECT uid FROM nodes")}
        langs = {r["lang"]: r["n"] for r in rows(con, "SELECT lang, count(*) AS n FROM files "
                                                      "WHERE parse_status != 'not_analyzed' GROUP BY lang")}
        edges = {(r["src"], r["dst"], r["kind"]) for r in rows(
            con, "SELECT s.uid AS src, d.uid AS dst, e.kind AS kind FROM edges e JOIN nodes s ON s.id = e.src "
                 "JOIN nodes d ON d.id = e.dst")}
        callers: dict[str, int] = {r["uid"]: r["fan_in"] for r in rows(
            con, "SELECT n.uid AS uid, s.fan_in AS fan_in FROM node_stats s JOIN nodes n ON n.id = s.node_id")}
        unknown = con.execute("SELECT count(*) FROM inventory WHERE lang IS NULL").fetchone()[0]
        total_files = con.execute("SELECT count(*) FROM inventory").fetchone()[0]
    finally:
        con.close()
    results: list[dict[str, Any]] = []
    inv = expectations.get("inventory") or {}
    for lang, spec in (inv.get("languages") or {}).items():
        n = langs.get(lang, 0)
        results.append({"item": f"inventory.{lang}", "ok": n >= int(spec.get("min_files", 0)), "value": n})
    if "max_unknown_rate" in inv:
        rate = unknown / total_files if total_files else 0.0
        results.append({"item": "inventory.max_unknown_rate", "ok": rate <= float(inv["max_unknown_rate"]),
                        "value": rate})
    for item in expectations.get("expect") or []:
        (kind, spec), = item.items()
        label = f"{kind}: {spec}"
        if kind == "node":
            results.append({"item": label, "ok": spec in uids})
        elif kind == "no_call_to":
            present = sorted(u for u in spec if u in uids and callers.get(u, 0) > 0)
            results.append({"item": label, "ok": not present, "value": present})
        elif kind == "callers_count":
            n = callers.get(spec["node"])
            ok = n is not None and int(spec.get("min", 0)) <= n <= int(spec.get("max", 10**9))
            results.append({"item": label, "ok": ok, "value": n})
        elif kind == "edge":
            results.append({"item": label, "ok": (spec["src"], spec["dst"], spec["kind"]) in edges})
        elif kind == "out_of_scope_allowed":
            results.append({"item": label, "ok": True, "value": [u for u in sorted(uids)
                                                                if any(fnmatch.fnmatchcase(u, p) for p in spec)][:5]})
        else:
            lot = SUPPORTED_LATER.get(kind)
            results.append({"item": label, "ok": None, "status": f"not supported yet (lot {lot})" if lot
                            else "unknown expectation"})
    return results
