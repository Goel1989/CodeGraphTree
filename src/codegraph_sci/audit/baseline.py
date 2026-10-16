"""Independent textual reference (§2.1): line-by-line search of definitions and CALL statements.

Deliberately naive and independent from the extractors. Its gaps with the graph are examined,
not taken as the truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph_sci.audit.common import SourceLines, connect, rows, scan_root

_F_DEF = re.compile(r"^\s*(?:[a-z][\w*() ,=]*?\s+)?(subroutine|function|program)\s+([a-z_]\w*)", re.I)
_F_IFACE = re.compile(r"^\s*(abstract\s+)?interface\b", re.I)
_F_END_IFACE = re.compile(r"^\s*end\s*interface\b", re.I)
_F_CALL = re.compile(r"\bcall\s+([a-z_]\w*)", re.I)
_PY_DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")
_C_DEF = re.compile(r"^[A-Za-z_][\w\s\*&:<>,~]*?\b([A-Za-z_~]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:override\s*)?\{?\s*$")
_C_SKIP = {"if", "for", "while", "switch", "return", "sizeof", "catch", "else"}
_STR = re.compile(r"'[^']*'|\"[^\"]*\"")


@dataclass
class Baseline:
    definitions: set[tuple[str, str]] = field(default_factory=set)  # (file, lower name)
    calls: set[tuple[str, int, str]] = field(default_factory=set)  # (file, line, lower name) - Fortran CALL


def _fortran_code(line: str, fixed: bool) -> str | None:
    if line.lstrip().startswith("#"):
        return None
    if fixed:
        if not line.strip() or line[:1] in "cC*!dD":
            return None
        line = line[:72]
    line = _STR.sub("''", line)
    return line.split("!", 1)[0]


def textual_reference(root: Path, files: list[dict[str, Any]]) -> Baseline:
    ref = Baseline()
    src = SourceLines(root)
    for f in files:
        path, lang, variant = f["path"], f["lang"], f["variant"] or ""
        lines = src.lines(path)
        if lang == "fortran":
            depth = 0
            for number, raw in enumerate(lines, start=1):
                code = _fortran_code(raw, variant.startswith("fixed"))
                if not code:
                    continue
                if _F_END_IFACE.match(code):
                    depth = max(0, depth - 1)
                    continue
                if _F_IFACE.match(code):
                    depth += 1
                    continue
                m = _F_DEF.match(code)
                if m and depth == 0 and not re.match(r"^\s*end\b", code, re.I):
                    ref.definitions.add((path, m.group(2).lower()))
                for cm in _F_CALL.finditer(code):
                    ref.calls.add((path, number, cm.group(1).lower()))
        elif lang == "python":
            for raw in lines:
                m = _PY_DEF.match(raw)
                if m:
                    ref.definitions.add((path, m.group(1).lower()))
        elif lang in ("c", "cpp"):
            for raw in lines:
                if raw.startswith((" ", "\t", "#", "/", "*", "}")):
                    continue
                m = _C_DEF.match(raw.split("//", 1)[0])
                if m and m.group(1) not in _C_SKIP and not raw.rstrip().endswith(";"):
                    ref.definitions.add((path, m.group(1).split("::")[-1].lower()))
    return ref


def compare_baseline(db: Path, root: Path | None = None) -> dict[str, Any]:
    con = connect(db)
    try:
        root = root or scan_root(con)
        assert root is not None, "no analysis recorded in this database"
        files = rows(con, "SELECT path, lang, variant FROM files WHERE parse_status IN ('ok', 'fallback') "
                          "ORDER BY path")
        ref = textual_reference(root, files)
        graph_defs = {(r["path"], r["name"].lower()) for r in rows(
            con, "SELECT f.path AS path, n.display_name AS name FROM nodes n JOIN files f ON f.id = n.file_id "
                 "WHERE n.kind IN ('routine', 'type', 'module')")}
        graph_calls = {(r["path"], r["line"], r["target"].lower().split("%")[-1]) for r in rows(
            con, "SELECT f.path AS path, s.line AS line, s.target_text AS target FROM call_sites s "
                 "JOIN files f ON f.id = s.file_id WHERE s.ref_kind IN ('call', 'dynamic_call') AND f.lang = 'fortran'")}
    finally:
        con.close()
    missing_defs = sorted(ref.definitions - graph_defs)
    missing_calls = sorted(ref.calls - graph_calls)
    found_defs = len(ref.definitions) - len(missing_defs)
    found_calls = len(ref.calls) - len(missing_calls)
    return {
        "definitions_reference": len(ref.definitions), "definitions_found": found_defs,
        "definitions_recall": found_defs / len(ref.definitions) if ref.definitions else 1.0,
        "missing_definitions": [{"file": f, "name": n} for f, n in missing_defs],
        "fortran_calls_reference": len(ref.calls), "fortran_calls_found": found_calls,
        "fortran_calls_recall": found_calls / len(ref.calls) if ref.calls else 1.0,
        "missing_calls": [{"file": f, "line": ln, "name": n} for f, ln, n in missing_calls],
    }
