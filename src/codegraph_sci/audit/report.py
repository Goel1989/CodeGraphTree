"""``cgs audit report``: metrics of §2.1 with confidence bounds, compared to the thresholds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph_sci.audit.baseline import compare_baseline
from codegraph_sci.audit.common import DEFAULT_THRESHOLDS, connect, rows
from codegraph_sci.audit.invariants import invariants
from codegraph_sci.audit.sample import load_sheet, sheet_metrics


def inventory_coherence(db: Path) -> dict[str, Any]:
    """File attribution and context checks (``.h`` included by C++ must be C++, ``.inc`` by Fortran...)."""
    con = connect(db)
    try:
        inv = rows(con, "SELECT f.path AS path, i.lang AS lang, i.decided_by AS decided_by FROM inventory i "
                        "JOIN files f ON f.id = i.file_id ORDER BY f.path")
        includes = rows(con, "SELECT sf.lang AS includer_lang, sf.path AS includer, df.path AS included, "
                             "df.lang AS included_lang FROM call_sites s JOIN files sf ON sf.id = s.file_id "
                             "JOIN nodes dn ON dn.id = s.dst_node JOIN files df ON df.id = dn.file_id "
                             "WHERE s.ref_kind = 'include' AND dn.kind = 'file'")
    finally:
        con.close()
    issues = []
    for r in includes:
        inc, inc_lang, by = r["included"], r["included_lang"], r["includer_lang"]
        if inc.endswith(".h") and by == "cpp" and inc_lang == "c":
            issues.append(f"{inc}: C header included by C++ file {r['includer']}")
        if inc.lower().endswith((".inc", ".fi", ".fh")) and by == "fortran" and inc_lang != "fortran":
            issues.append(f"{inc}: included by Fortran file {r['includer']} but classified {inc_lang}")
    return {"files": len(inv), "attributed": sum(1 for r in inv if r["lang"]), "issues": sorted(set(issues))}


def audit_report(db: Path, precision_sheet: Path | None = None, recall_sheet: Path | None = None,
                 thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    inv = invariants(db)
    base = compare_baseline(db)
    statuses = inv["files_by_status"]
    analysed = sum(v for k, v in statuses.items() if k in ("ok", "fallback", "failed"))
    failure_rate = statuses.get("failed", 0) / analysed if analysed else 0.0
    metrics: list[dict[str, Any]] = [
        {"metric": "parse_failure_rate", "value": failure_rate, "threshold": th["max_parse_failure_rate"],
         "ok": failure_rate <= th["max_parse_failure_rate"]},
        {"metric": "definitions_recall", "value": base["definitions_recall"], "threshold": th["min_recall_definitions"],
         "ok": base["definitions_recall"] >= th["min_recall_definitions"]},
        {"metric": "unresolved_rate", "value": inv["unresolved_rate"], "threshold": th["max_unresolved_rate"],
         "ok": inv["unresolved_rate"] <= th["max_unresolved_rate"]},
        {"metric": "ambiguous_sites", "value": inv["ambiguous_sites"], "threshold": None, "ok": True},
    ]
    if precision_sheet is not None:
        for group, m in sheet_metrics(load_sheet(precision_sheet)).items():
            bridges = group == "bridges"
            need = th["min_precision_bridges" if bridges else "min_precision_resolved"]
            need_low = th["min_precision_bridges_lower_bound" if bridges else "min_precision_lower_bound"]
            ok = m["rate"] is not None and m["rate"] >= need and (m["lower_bound"] or 0) >= need_low
            metrics.append({"metric": f"precision[{group}]", "value": m["rate"], "lower_bound": m["lower_bound"],
                            "n": m["n"], "threshold": need, "ok": ok})
    if recall_sheet is not None:
        for group, m in sheet_metrics(load_sheet(recall_sheet)).items():
            ok = m["rate"] is not None and m["rate"] >= th["min_recall_call_sites"] and (
                m["lower_bound"] or 0) >= th["min_recall_lower_bound"]
            metrics.append({"metric": f"recall_call_sites[{group}]", "value": m["rate"],
                            "lower_bound": m["lower_bound"], "n": m["n"], "threshold": th["min_recall_call_sites"],
                            "ok": ok})
    return {"metrics": metrics, "all_ok": all(m["ok"] for m in metrics), "invariants": inv,
            "baseline": {k: v for k, v in base.items() if not k.startswith("missing")},
            "missing_definitions": base["missing_definitions"][:50], "missing_calls": base["missing_calls"][:50]}
