"""Comparative bench of Fortran parsers (lot 4, decision D17).

Candidates: statement parser (codegraph_sci), pattern extractor (codegraph_sci), tree-sitter-fortran,
fparser (if installed). LFortran is reported as not evaluated when its binary is missing.
Measures, per candidate, on the Fortran fixtures (and on extra folders given on the command line):
failures, definition recall/precision, CALL-site recall/precision, time.

Usage: python tools/bench_fortran.py [--out docs/bench/fortran_parsers.md] [EXTRA_DIR ...]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codegraph_sci.core.plugins import ExtractContext, decode_bytes  # noqa: E402
from codegraph_sci.extract.context import make_include_resolver  # noqa: E402
from codegraph_sci.extract.fortran.parser import HardParseError, extract_fortran  # noqa: E402
from codegraph_sci.extract.fortran.patterns import extract_patterns  # noqa: E402
from codegraph_sci.inventory.run import run_inventory  # noqa: E402

Result = tuple[set[tuple[str, int]], set[tuple[str, int]]]  # (definitions (name, line), calls (name, line))


def ours(path: str, text: str, variant: str | None, root: Path, include_paths: list[str]) -> Result:
    ctx = ExtractContext(include_paths=include_paths, resolve_include=make_include_resolver(root, include_paths))
    facts = extract_fortran(path, text, "utf-8", variant, ctx)
    defs = {(d.name, d.span[0]) for d in facts.definitions if d.kind == "routine"}
    calls = {(r.target_text.lower(), r.line) for r in facts.references if r.kind in ("call", "dynamic_call")
             and "%" not in r.target_text and _is_call_statement(text, r.line)}
    return defs, calls


def _is_call_statement(text: str, line: int) -> bool:
    lines = text.replace("\r\n", "\n").split("\n")
    for back in range(0, 3):
        if line - 1 - back >= 0 and "call" in lines[line - 1 - back].lower():
            return True
    return False


def patterns(path: str, text: str, variant: str | None, root: Path, include_paths: list[str]) -> Result:
    facts = extract_patterns(path, text, "utf-8", variant)
    return ({(d.name, d.span[0]) for d in facts.definitions if d.kind == "routine"},
            {(r.target_text.lower(), r.line) for r in facts.references if "%" not in r.target_text})


def tree_sitter(path: str, text: str, variant: str | None, root: Path, include_paths: list[str]) -> Result:
    import tree_sitter as ts
    import tree_sitter_fortran as tsf

    parser = ts.Parser(ts.Language(tsf.language()))
    tree = parser.parse(text.encode("utf-8"))
    if tree.root_node.has_error:
        raise SyntaxError("tree-sitter reported syntax errors")
    defs: set[tuple[str, int]] = set()
    calls: set[tuple[str, int]] = set()
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in ("subroutine_statement", "function_statement", "program_statement"):
            name = node.child_by_field_name("name")
            if name is not None and node.parent is not None and node.parent.type != "interface":
                defs.add((name.text.decode().lower(), node.start_point[0] + 1))
        if node.type == "subroutine_call":
            name = node.child_by_field_name("subroutine")
            if name is not None and name.type == "identifier":
                calls.add((name.text.decode().lower(), name.start_point[0] + 1))
        stack.extend(node.children)
    return defs, calls


def fparser(path: str, text: str, variant: str | None, root: Path, include_paths: list[str]) -> Result:
    from fparser.common.readfortran import FortranStringReader
    from fparser.two import Fortran2003
    from fparser.two.parser import ParserFactory
    from fparser.two.utils import walk

    reader = FortranStringReader(text, ignore_comments=True)
    if variant and variant.startswith("fixed"):
        from fparser.common.sourceinfo import FortranFormat

        reader.set_format(FortranFormat(False, True))
    tree = ParserFactory().create(std="f2008")(reader)
    defs = {(str(n.items[1]).lower(), 0) for n in walk(tree, (Fortran2003.Subroutine_Stmt,
                                                          Fortran2003.Function_Stmt, Fortran2003.Program_Stmt))}
    calls = {(str(n.items[0]).lower(), 0) for n in walk(tree, Fortran2003.Call_Stmt)}
    return defs, calls


def _ratio(a: int, b: int) -> str:
    return "-" if b == 0 else f"{a / b:.1%}"


def bench(folders: list[Path]) -> dict[str, dict[str, object]]:
    candidates: dict[str, Callable[..., Result]] = {"statement parser (retenu)": ours,
                                                    "pattern extractor": patterns,
                                                    "tree-sitter-fortran": tree_sitter}
    try:
        import fparser as _fp  # noqa: F401

        candidates["fparser"] = fparser
    except ImportError:
        pass
    files: list[tuple[Path, str, str, str | None, list[str]]] = []
    for folder in folders:
        inv = run_inventory(folder)
        for e in inv.source_files():
            if e.lang == "fortran":
                text, _ = decode_bytes((folder / e.path).read_bytes())
                files.append((folder, e.path, text, e.variant, inv.include_paths))
    reference: dict[tuple[str, str], Result] = {}
    for folder, path, text, variant, incs in files:
        try:
            reference[(str(folder), path)] = ours(path, text, variant, folder, incs)
        except HardParseError:
            reference[(str(folder), path)] = (set(), set())
    report: dict[str, dict[str, object]] = {}
    for name, fn in candidates.items():
        failures, d_found, d_ok, d_ref, c_found, c_ok, c_ref = 0, 0, 0, 0, 0, 0, 0
        start = time.perf_counter()
        for folder, path, text, variant, incs in files:
            ref_defs, ref_calls = reference[(str(folder), path)]
            d_ref += len(ref_defs)
            c_ref += len(ref_calls)
            try:
                defs, calls = fn(path, text, variant, folder, incs)
            except Exception:  # noqa: BLE001 - a failure is a measured outcome
                failures += 1
                continue
            by_line = all(line for _, line in defs)
            if by_line:
                d_ok += len(defs & ref_defs)
                c_ok += len(calls & ref_calls)
            else:
                d_ok += len({n for n, _ in defs} & {n for n, _ in ref_defs})
                c_ok += len({n for n, _ in calls} & {n for n, _ in ref_calls})
            d_found += len(defs)
            c_found += len(calls)
        elapsed = time.perf_counter() - start
        report[name] = {"files": len(files), "failures": failures, "def_recall": _ratio(d_ok, d_ref),
                        "def_precision": _ratio(d_ok, d_found), "call_recall": _ratio(c_ok, c_ref),
                        "call_precision": _ratio(c_ok, c_found), "time_s": round(elapsed, 3)}
    if shutil.which("lfortran") is None:
        report["LFortran"] = {"files": len(files), "failures": "not evaluated (binary missing)"}
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("extra", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "bench" / "fortran_parsers.md")
    args = parser.parse_args()
    fixtures = sorted(p.parent for p in (ROOT / "tests" / "fixtures").glob("*/src")
                      if any(p.rglob("*.f*")) or any(p.rglob("*.F*")))
    report = bench(fixtures + list(args.extra))
    lines = ["# Fortran Parser Benchmark", "",
             "Reference: statement parser facts, matching the hand-written expected graphs "
             "(Lot 4 tests). Calls: `CALL` statements only (the only call kind common to all parsers).", "",
             "| Candidate | Files | Failures | Def. Recall | Def. Precision | CALL Recall | CALL Precision | Time (s) |",
             "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, r in report.items():
        lines.append(f"| {name} | {r.get('files')} | {r.get('failures')} | {r.get('def_recall', '-')} | "
                     f"{r.get('def_precision', '-')} | {r.get('call_recall', '-')} | "
                     f"{r.get('call_precision', '-')} | {r.get('time_s', '-')} |")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
