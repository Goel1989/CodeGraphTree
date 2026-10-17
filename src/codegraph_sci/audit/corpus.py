"""Real-code corpora (§5.4): manifest + expectations, checked against an analysis.

The sources of a corpus are never stored in the repository: the manifest says where they are
locally and at which exact revision. Each expectation ends ``PASS``, ``FAIL`` or ``SKIP``: a required
expectation (the default) that cannot be evaluated is a ``FAIL`` with its reason, only an optional one
(``required: false``) may be skipped. The orchestration (audit profile, scan) is ``codegraph_sci.corpus_audit``.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.audit.common import connect, rows

SUPPORTED_LATER = {"catalog_links": 14}
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
KINDS = {"node", "no_call_to", "callers_count", "edge", "out_of_scope_allowed", "hidden", "writes", "path",
         "dispatches", "tests_for"}


class ExpectationError(ValueError):
    """Malformed manifest or expectations file (a configuration error, never a test result)."""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ExpectationError(f"{path}: cannot read the manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ExpectationError(f"{path}: the manifest must be a mapping")
    for key in ("corpus", "source", "scope"):
        if key not in data:
            raise ExpectationError(f"{path}: key '{key}' is required")
    if not isinstance(data["source"], dict) or not data["source"].get("path"):
        raise ExpectationError(f"{path}: source.path is required")
    if not isinstance(data["scope"], list) or not isinstance(data.get("packs", []), list):
        raise ExpectationError(f"{path}: scope and packs must be lists")
    return data


def parse_items(expectations: dict[str, Any]) -> list[tuple[str, Any, bool]]:
    """``expect`` entries as (kind, spec, required); an entry is ``{kind: spec}`` plus an optional ``required``."""
    items = []
    for n, entry in enumerate(expectations.get("expect") or [], start=1):
        if not isinstance(entry, dict):
            raise ExpectationError(f"expectation {n}: a mapping of one kind to its spec is expected")
        required = entry.get("required", True)
        kinds = [k for k in entry if k != "required"]
        if len(kinds) != 1 or not isinstance(required, bool):
            raise ExpectationError(f"expectation {n}: exactly one kind and an optional boolean 'required' "
                                   f"are expected, got {sorted(entry)}")
        items.append((kinds[0], entry[kinds[0]], required))
    return items


def _result(label: str, ok: bool, required: bool = True, **extra: Any) -> dict[str, Any]:
    return {"item": label, "status": PASS if ok else FAIL, "required": required, **extra}


def _query_expectation(db: Path, kind: str, spec: Any, label: str) -> dict[str, Any]:
    from codegraph_sci.core.model import CALL_PATH, FILE_DEPENDENCY
    from codegraph_sci.query.api import GraphQuery, QueryError

    with GraphQuery(db) as q:
        try:
            if kind == "hidden":
                node = q.node(str(spec))
                return _result(label, node.is_noise, value=node.noise_reason)
            if kind == "writes":
                accesses = q.data_accesses(str(spec["routine"]))
                want_kind = spec.get("key_kind")
                hits = [a for a in accesses if a.mode == "writes" and (
                    a.data == spec["data"] or a.family == spec["data"]) and (want_kind is None or (
                        a.key_kind == want_kind or (want_kind == "family" and a.family == spec["data"])))]
                return _result(label, bool(hits), value=len(hits))
            if kind == "path":
                kinds = FILE_DEPENDENCY if spec.get("edge_kinds") == "file_dependency" else CALL_PATH
                report = q.paths(str(spec["from"]), str(spec["to"]), edge_kinds=kinds, k=1,
                                 max_len=int(spec.get("max_len", 15)))
                return _result(label, bool(report.paths),
                               value=[s.uid for s in report.paths[0].steps] if report.paths else None)
            if kind == "dispatches":
                page = q.children(str(spec["src"]), direction=_callees(), edge_kinds={"dispatches"}, limit=1)
                return _result(label, page.total >= int(spec.get("min_targets", 1)), value=page.total)
            if kind == "tests_for":
                impact = q.impact(str(spec["routine"]), edge_kinds=CALL_PATH | {"exercises"}, limit=100_000)
                tests = [s.uid for _d, s in impact.items if s.kind == "test_case"]
                return _result(label, len(tests) >= int(spec.get("min_cases", 1)), value=len(tests))
        except QueryError as exc:
            return _result(label, False, reason=str(exc))
    raise ExpectationError(f"{label}: unknown expectation kind")


def _callees() -> Any:
    from codegraph_sci.query.types import Direction

    return Direction.CALLEES


def check_expectations(db: Path, expectations: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate each expectation: one result per item, with ``status`` PASS / FAIL / SKIP and ``required``."""
    items = parse_items(expectations)
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
        results.append(_result(f"inventory.{lang}", n >= int(spec.get("min_files", 0)), value=n))
    if "max_unknown_rate" in inv:
        rate = unknown / total_files if total_files else 0.0
        results.append(_result("inventory.max_unknown_rate", rate <= float(inv["max_unknown_rate"]), value=rate))
    for kind, spec, required in items:
        label = f"{kind}: {spec}"
        if kind not in KINDS:
            lot = SUPPORTED_LATER.get(kind)
            reason = f"not supported yet (lot {lot})" if lot else "unknown expectation kind"
            results.append({"item": label, "status": FAIL if required else SKIP, "required": required,
                            "reason": reason})
        elif kind == "node":
            results.append(_result(label, spec in uids, required))
        elif kind == "no_call_to":
            present = sorted(u for u in spec if u in uids and callers.get(u, 0) > 0)
            results.append(_result(label, not present, required, value=present))
        elif kind == "callers_count":
            n = callers.get(spec["node"])
            ok = n is not None and int(spec.get("min", 0)) <= n <= int(spec.get("max", 10**9))
            results.append(_result(label, ok, required, value=n))
        elif kind == "edge":
            results.append(_result(label, (spec["src"], spec["dst"], spec["kind"]) in edges, required))
        elif kind == "out_of_scope_allowed":  # informational: lists matching nodes, nothing can fail
            matching = [u for u in sorted(uids) if any(fnmatch.fnmatchcase(u, p) for p in spec)][:5]
            results.append(_result(label, True, required, value=matching))
        else:
            result = _query_expectation(db, kind, spec, label)
            result["required"] = required
            results.append(result)
    return results
