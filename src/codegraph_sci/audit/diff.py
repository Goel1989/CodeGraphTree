"""Double extraction (§2.1): each language is read by two different extractors; disagreements are listed.

Fortran: statement parser vs pattern extractor. C/C++: tree-sitter vs pattern extractor.
Python: ``ast`` vs tree-sitter. Compared: definitions (name, line) and CALL-like sites (name, line).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from codegraph_sci.audit.common import connect, rows, scan_root
from codegraph_sci.core.facts import FileFacts, SourceFile
from codegraph_sci.core.plugins import ExtractContext, decode_bytes
from codegraph_sci.extract.cfamily import CFamilyExtractor
from codegraph_sci.extract.context import make_include_resolver
from codegraph_sci.extract.fortran.parser import HardParseError, extract_fortran
from codegraph_sci.extract.fortran.patterns import extract_patterns
from codegraph_sci.extract.python import PythonAdapter
from codegraph_sci.extract.python.fallback import extract_tree_sitter


def _keys(facts: FileFacts, calls_only: bool) -> tuple[set[tuple[str, int]], set[tuple[str, int]]]:
    defs = {(d.name.lower(), d.span[0]) for d in facts.definitions if d.kind == "routine"}
    refs = {(r.target_text.lower().split("%")[-1].split(".")[-1].split("::")[-1], r.line)
            for r in facts.references if r.kind in (("call",) if calls_only else ("call", "maybe_call"))}
    return defs, refs


def _pair(path: str, lang: str, variant: str | None, text: str, ctx: ExtractContext) -> tuple[FileFacts, FileFacts]:
    if lang == "fortran":
        try:
            a = extract_fortran(path, text, "utf-8", variant, ctx)
        except HardParseError:
            a = FileFacts(path=path, lang=lang, encoding="utf-8", adapter="fortran", adapter_version="-")
        return a, extract_patterns(path, text, "utf-8", variant)
    if lang == "python":
        a = PythonAdapter().extract(SourceFile(path, lang, variant, "utf-8", text), ctx)
        return a, extract_tree_sitter(path, text, "utf-8", "m")
    primary = CFamilyExtractor(lang, path, text, "utf-8", ctx, lang, "1.0").run()
    alt = CFamilyExtractor(lang, path, text, "utf-8", ctx, lang, "1.0")
    alt.pattern_extract()
    return primary, FileFacts(path=path, lang=lang, encoding="utf-8", adapter="patterns", adapter_version="1.0",
                              definitions=alt.definitions, references=alt.references)


def double_extraction(db: Path, root: Path | None = None, limit_per_lang: int | None = None) -> dict[str, Any]:
    con = connect(db)
    try:
        root = root or scan_root(con)
        assert root is not None
        files = rows(con, "SELECT path, lang, variant FROM files WHERE parse_status IN ('ok', 'fallback') "
                          "AND lang IN ('fortran', 'python', 'c', 'cpp') ORDER BY path")
    finally:
        con.close()
    include_paths = sorted({str(Path(f["path"]).parent.as_posix()) for f in files})
    ctx = ExtractContext(include_paths=include_paths, resolve_include=make_include_resolver(root, include_paths))
    per_lang: dict[str, dict[str, Any]] = defaultdict(lambda: {"files": 0, "def_only_primary": 0,
                                                               "def_only_secondary": 0, "call_only_primary": 0,
                                                               "call_only_secondary": 0, "examples": []})
    counts: dict[str, int] = defaultdict(int)
    for f in files:
        lang = f["lang"]
        if limit_per_lang is not None and counts[lang] >= limit_per_lang:
            continue
        counts[lang] += 1
        text, _enc = decode_bytes((root / f["path"]).read_bytes())
        a, b = _pair(f["path"], lang, f["variant"], text, ctx)
        calls_only = lang == "fortran"
        da, ra = _keys(a, calls_only)
        db_, rb = _keys(b, calls_only)
        if lang == "python":  # tree-sitter python fallback binds no maybe-call distinction
            ra = {(n, ln) for n, ln in ra}
        entry = per_lang[lang]
        entry["files"] += 1
        for label, only in (("def_only_primary", da - db_), ("def_only_secondary", db_ - da),
                            ("call_only_primary", ra - rb), ("call_only_secondary", rb - ra)):
            entry[label] += len(only)
            for name, line in sorted(only)[:3]:
                if len(entry["examples"]) < 30:
                    entry["examples"].append({"kind": label, "file": f["path"], "line": line, "name": name})
    return dict(sorted(per_lang.items()))
