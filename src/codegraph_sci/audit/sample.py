"""Verified samples (§2.1): stratified precision sample, recall sample, one-key review, replay.

Sheets are YAML files. Verified entries are kept (``reference_sample.yaml``) and replayed
automatically: the manual effort is done once per corpus.
"""

from __future__ import annotations

import os
import random
import re
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.audit.common import SourceLines, connect, rows, scan_root, wilson_interval

SHEET_VERSION = 1
# Windows refuses to replace a file another process holds open for a moment (antivirus, search indexer): the
# replacement is retried a few times there. Elsewhere such a refusal is not transient and is raised at once.
RETRY_REPLACE = os.name == "nt"
REPLACE_ATTEMPTS = 5
REPLACE_DELAY_S = 0.1
_CALLISH = {
    "fortran": re.compile(r"\b[a-z_]\w*\s*\(", re.I),
    "python": re.compile(r"\b[A-Za-z_][\w.]*\s*\("),
    "c": re.compile(r"\b[A-Za-z_]\w*\s*\("),
    "cpp": re.compile(r"\b[A-Za-z_][\w:.>-]*\s*\("),
}
_COMMENT = {"fortran": re.compile(r"^\s*[!cC*]|^[cC*]"), "python": re.compile(r"^\s*#"),
            "c": re.compile(r"^\s*(//|/\*|\*)"), "cpp": re.compile(r"^\s*(//|/\*|\*)")}


def load_sheet(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or data.get("sheet_version") != SHEET_VERSION:
        raise ValueError(f"{path}: not a sample sheet (sheet_version {SHEET_VERSION})")
    return data


def save_sheet(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if not RETRY_REPLACE or attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_DELAY_S * attempt)


def precision_sample(db: Path, per_group: int = 150, seed: int = 42, revision: str | None = None) -> dict[str, Any]:
    """Stratified sample of resolved links: one group per language, plus a "bridges" group."""
    con = connect(db)
    try:
        root = scan_root(con)
        data = rows(con, "SELECT s.id AS id, src.uid AS src, dst.uid AS dst, f.path AS file, s.line AS line, "
                         "s.col AS col, s.target_text AS target, s.origin AS origin, s.confidence AS confidence, "
                         "f.lang AS lang, df.path AS dst_file, dst.line_start AS dst_line FROM call_sites s "
                         "JOIN nodes src ON src.id = s.src_node JOIN nodes dst ON dst.id = s.dst_node "
                         "JOIN files f ON f.id = s.file_id LEFT JOIN files df ON df.id = dst.file_id "
                         "WHERE s.resolution = 'resolved' AND s.ref_kind IN ('call', 'maybe_call', 'dynamic_call') "
                         "ORDER BY f.path, s.line, s.col, src.uid")
    finally:
        con.close()
    src_lines = SourceLines(root) if root else None
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in data:
        groups["bridges" if r["origin"].startswith("bridge:") else (r["lang"] or "other")].append(r)
    rng = random.Random(seed)
    entries = []
    for group in sorted(groups):
        items = groups[group]
        chosen = sorted(rng.sample(range(len(items)), min(per_group, len(items))))
        for i in chosen:
            r = items[i]
            entries.append({
                "id": f"p-{group}-{i}", "group": group, "src": r["src"], "dst": r["dst"], "file": r["file"],
                "line": r["line"], "col": r["col"], "target": r["target"], "confidence": r["confidence"],
                "code": src_lines.line(r["file"], r["line"]).strip() if src_lines else "",
                "dst_location": f"{r['dst_file']}:{r['dst_line']}" if r["dst_file"] else None, "verdict": None})
    return {"sheet_version": SHEET_VERSION, "kind": "precision", "seed": seed, "revision": revision,
            "entries": entries}


def recall_sample(db: Path, per_lang: int = 150, seed: int = 42, revision: str | None = None) -> dict[str, Any]:
    """Random code locations likely to contain a call; the reviewer lists the calls really present."""
    con = connect(db)
    try:
        root = scan_root(con)
        assert root is not None
        files = rows(con, "SELECT id, path, lang FROM files WHERE parse_status IN ('ok', 'fallback') "
                          "AND lang IN ('fortran', 'python', 'c', 'cpp') ORDER BY path")
        extracted: dict[tuple[str, int], list[str]] = defaultdict(list)
        for r in rows(con, "SELECT f.path AS file, s.line AS line, s.target_text AS target FROM call_sites s "
                           "JOIN files f ON f.id = s.file_id WHERE s.ref_kind IN ('call', 'maybe_call', "
                           "'dynamic_call') ORDER BY s.col"):
            extracted[(r["file"], r["line"])].append(r["target"])
    finally:
        con.close()
    src = SourceLines(root)
    candidates: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for f in files:
        rx, comment = _CALLISH[f["lang"]], _COMMENT[f["lang"]]
        for number, line in enumerate(src.lines(f["path"]), start=1):
            if line.strip() and not comment.match(line) and rx.search(line):
                candidates[f["lang"]].append((f["path"], number))
    rng = random.Random(seed)
    entries = []
    for lang in sorted(candidates):
        items = candidates[lang]
        for i in sorted(rng.sample(range(len(items)), min(per_lang, len(items)))):
            path, number = items[i]
            entries.append({"id": f"r-{lang}-{i}", "group": lang, "file": path, "line": number,
                            "code": src.line(path, number).strip(), "extracted": extracted.get((path, number), []),
                            "actual": None})
    return {"sheet_version": SHEET_VERSION, "kind": "recall", "seed": seed, "revision": revision,
            "entries": entries}


def review(sheet_path: Path, ask: Callable[[str], str] = input, show: Callable[[str], None] = print) -> int:
    """Interactive review, one key per entry. Saves after every answer. Returns entries left."""
    data = load_sheet(sheet_path)
    precision = data["kind"] == "precision"
    todo = [e for e in data["entries"] if (e["verdict"] if precision else e["actual"]) is None]
    for n, e in enumerate(todo, start=1):
        show(f"\n[{n}/{len(todo)}] {e['file']}:{e['line']}   {e['code']}")
        if precision:
            show(f"   {e['src']}  -->  {e['dst']}   ({e['dst_location']}, {e['confidence']})")
            key = ask("   correct? [y]es / [n]o / [s]kip / [q]uit: ").strip().lower()[:1]
            if key == "q":
                break
            if key in ("y", "n"):
                e["verdict"] = key == "y"
        else:
            show(f"   extracted: {', '.join(e['extracted']) or '(none)'}")
            key = ask("   [y] exactly these calls / [e] enter the real calls / [s]kip / [q]uit: ").strip().lower()[:1]
            if key == "q":
                break
            if key == "y":
                e["actual"] = list(e["extracted"])
            elif key == "e":
                names = ask("   real calls (comma separated, empty = none): ")
                e["actual"] = [x.strip() for x in names.split(",") if x.strip()]
        save_sheet(sheet_path, data)
    return sum(1 for e in data["entries"] if (e["verdict"] if precision else e["actual"]) is None)


def _norm(name: str) -> str:
    return re.split(r"[.%:>-]", name.lower())[-1]


def sheet_metrics(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per group: verified count, rate and Wilson lower bound."""
    out: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in data["entries"]:
        groups[e["group"]].append(e)
    for group, items in sorted(groups.items()):
        if data["kind"] == "precision":
            done = [e for e in items if e["verdict"] is not None]
            ok, n = sum(1 for e in done if e["verdict"]), len(done)
        else:
            done = [e for e in items if e["actual"] is not None]
            n = sum(len(e["actual"]) for e in done)
            ok = sum(len({_norm(a) for a in e["actual"]} & {_norm(x) for x in e["extracted"]}) for e in done)
        low, high = wilson_interval(ok, n)
        out[group] = {"verified": len(done), "total": len(items), "n": n, "ok": ok,
                      "rate": ok / n if n else None, "lower_bound": low if n else None}
    return out


def replay(sheet: dict[str, Any], db: Path) -> list[str]:
    """Re-check verified entries against the current database. Returns regressions."""
    con = connect(db)
    try:
        links = {(r["src"], r["dst"], r["file"], r["line"]) for r in rows(
            con, "SELECT src.uid AS src, dst.uid AS dst, f.path AS file, s.line AS line FROM call_sites s "
                 "JOIN nodes src ON src.id = s.src_node JOIN nodes dst ON dst.id = s.dst_node "
                 "JOIN files f ON f.id = s.file_id")}
        at_line: dict[tuple[str, int], set[str]] = defaultdict(set)
        for r in rows(con, "SELECT f.path AS file, s.line AS line, s.target_text AS target FROM call_sites s "
                           "JOIN files f ON f.id = s.file_id WHERE s.ref_kind IN ('call', 'maybe_call', 'dynamic_call')"):
            at_line[(r["file"], r["line"])].add(_norm(r["target"]))
    finally:
        con.close()
    problems = []
    for e in sheet["entries"]:
        if sheet["kind"] == "precision" and e["verdict"] is not None:
            present = (e["src"], e["dst"], e["file"], e["line"]) in links
            if e["verdict"] and not present:
                problems.append(f"{e['id']}: verified link disappeared ({e['src']} -> {e['dst']})")
            if not e["verdict"] and present:
                problems.append(f"{e['id']}: link verified as wrong is still produced ({e['src']} -> {e['dst']})")
        elif sheet["kind"] == "recall" and e["actual"] is not None:
            missing = {_norm(a) for a in e["actual"]} - at_line.get((e["file"], e["line"]), set())
            if missing:
                problems.append(f"{e['id']}: calls no longer extracted at {e['file']}:{e['line']}: "
                                f"{', '.join(sorted(missing))}")
    return problems


def merge_into_reference(sheet: dict[str, Any], reference_path: Path) -> int:
    """Append verified entries of a sheet to ``reference_sample.yaml``. Returns entries added."""
    ref: dict[str, Any] = {"sheet_version": SHEET_VERSION, "precision": [], "recall": []}
    if reference_path.is_file():
        loaded = yaml.safe_load(reference_path.read_text(encoding="utf-8")) or {}
        ref.update({k: loaded.get(k, []) for k in ("precision", "recall")})
    key = "precision" if sheet["kind"] == "precision" else "recall"
    known = {e["id"] for e in ref[key]}
    added = 0
    for e in sheet["entries"]:
        verified = e["verdict"] is not None if key == "precision" else e["actual"] is not None
        if verified and e["id"] not in known:
            ref[key].append({**e, "revision": sheet.get("revision")})
            added += 1
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    save_sheet(reference_path, {"sheet_version": SHEET_VERSION, **ref})
    return added


def replay_reference(reference_path: Path, db: Path) -> list[str]:
    ref = yaml.safe_load(reference_path.read_text(encoding="utf-8")) or {}
    problems = replay({"kind": "precision", "entries": ref.get("precision", [])}, db)
    problems += replay({"kind": "recall", "entries": ref.get("recall", [])}, db)
    return problems
