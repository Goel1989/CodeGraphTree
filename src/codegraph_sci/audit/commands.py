"""``cgs audit ...`` sub-commands (lot 7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.core.project import open_project


def _db(args: argparse.Namespace) -> Path:
    if getattr(args, "db", None):
        return Path(args.db)
    project = open_project(args.root, args.project)
    if not project.db_path.is_file():
        raise SystemExit(f"error: no analysis for {project.root}; run `cgs scan` first")
    return project.db_path


def _out(data: Any, args: argparse.Namespace) -> None:
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str) if args.json else yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, width=120)
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _inventory(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.report import inventory_coherence

    data = inventory_coherence(_db(args))
    _out(data, args)
    return 0 if not data["issues"] else 1


def _baseline(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.baseline import compare_baseline

    data = compare_baseline(_db(args))
    data["missing_definitions"] = data["missing_definitions"][: args.limit]
    data["missing_calls"] = data["missing_calls"][: args.limit]
    _out(data, args)
    return 0


def _diff(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.diff import double_extraction

    _out(double_extraction(_db(args), limit_per_lang=args.max_files), args)
    return 0


def _invariants(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.invariants import invariants, unresolved_groups

    data = invariants(_db(args))
    data["unresolved_groups"] = unresolved_groups(_db(args), include_ambiguous=True, limit=args.limit)
    _out(data, args)
    return 0


def _sample(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.sample import precision_sample, recall_sample, save_sheet

    db = _db(args)
    if args.command_audit == "sample":
        sheet = precision_sample(db, args.per_group, args.seed, args.revision)
    else:
        sheet = recall_sample(db, args.per_group, args.seed, args.revision)
    out = Path(args.output)
    save_sheet(out, sheet)
    print(f"{len(sheet['entries'])} entries written to {out}; review them with `cgs audit review {out}`")
    return 0


def _review(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.sample import review

    left = review(Path(args.sheet))
    print(f"\n{left} entries left to review")
    return 0


def _report(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.report import audit_report

    thresholds = None
    if args.expectations:
        exp = yaml.safe_load(Path(args.expectations).read_text(encoding="utf-8")) or {}
        thresholds = {k: float(v) for k, v in (exp.get("metrics") or {}).items()}
    data = audit_report(_db(args), Path(args.precision) if args.precision else None,
                        Path(args.recall) if args.recall else None, thresholds)
    if args.json:
        _out(data, args)
    else:
        print(f"{'Metric':<34}{'Value':>10}{'Lower':>10}{'Threshold':>11}  Status")
        for m in data["metrics"]:
            value = m["value"]
            v = "-" if value is None else (f"{value:.2%}" if isinstance(value, float) else str(value))
            low = m.get("lower_bound")
            lb = "-" if low is None else f"{low:.2%}"
            th = "-" if m["threshold"] is None else f"{m['threshold']:.0%}"
            print(f"{m['metric']:<34}{v:>10}{lb:>10}{th:>11}  {'OK' if m['ok'] else 'NOT MET'}")
        print("\nV1 criteria: " + ("MET" if data["all_ok"] else "NOT MET (see §2.1 plan B)"))
    return 0 if data["all_ok"] else 1


def _replay(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.sample import replay_reference

    problems = replay_reference(Path(args.reference), _db(args))
    for p in problems:
        print(p)
    print("replay: " + ("OK" if not problems else f"{len(problems)} regression(s)"))
    return 0 if not problems else 1


def _accept(args: argparse.Namespace) -> int:
    from codegraph_sci.audit.sample import load_sheet, merge_into_reference

    added = merge_into_reference(load_sheet(Path(args.sheet)), Path(args.reference))
    print(f"{added} verified entries added to {args.reference}")
    return 0


def register(sub: Any, corpus_handler: Any = None) -> None:
    audit = sub.add_parser("audit", help="validation of the analysis without a compiler (§2.1)")
    asub = audit.add_subparsers(dest="command_audit", metavar="CHECK", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("root", nargs="?", help="repository folder")
        p.add_argument("--project", help="project folder")
        p.add_argument("--db", help="project database (instead of root/project)")
        p.add_argument("--json", action="store_true", help="JSON output (default: YAML)")

    p = asub.add_parser("inventory", help="coherence of the language inventory")
    common(p)
    p.set_defaults(func=_inventory)
    p = asub.add_parser("baseline", help="independent textual reference vs graph")
    common(p)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_baseline)
    p = asub.add_parser("diff", help="double extraction: disagreements between two extractors")
    common(p)
    p.add_argument("--max-files", type=int, default=None, help="files per language")
    p.set_defaults(func=_diff)
    p = asub.add_parser("invariants", help="duplicates, unresolved groups, never-called routines, failures")
    common(p)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=_invariants)
    for name, helptext in (("sample", "stratified precision sample sheet"),
                           ("recall-sample", "recall sample sheet (random code locations)")):
        p = asub.add_parser(name, help=helptext)
        common(p)
        p.add_argument("-o", "--output", required=True, help="sheet to write (.yaml)")
        p.add_argument("--per-group", type=int, default=150)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--revision", help="exact revision of the analysed code")
        p.set_defaults(func=_sample)
    p = asub.add_parser("review", help="review a sheet, one key per entry")
    p.add_argument("sheet")
    p.set_defaults(func=_review)
    p = asub.add_parser("report", help="metrics of §2.1 with Wilson bounds")
    common(p)
    p.add_argument("--precision", help="reviewed precision sheet")
    p.add_argument("--recall", help="reviewed recall sheet")
    p.add_argument("--expectations", help="corpus expectations.yaml (thresholds)")
    p.set_defaults(func=_report)
    p = asub.add_parser("accept", help="add verified entries of a sheet to reference_sample.yaml")
    p.add_argument("sheet")
    p.add_argument("reference")
    p.set_defaults(func=_accept)
    p = asub.add_parser("corpus", help="analyse a real-code corpus (manifest) and check its expectations")
    p.add_argument("manifest", help="tests/corpus/<code>/manifest.yaml")
    p.add_argument("--project", help="project folder")
    p.add_argument("--no-scan", action="store_true", help="check the existing analysis only")
    p.set_defaults(func=corpus_handler)
    p = asub.add_parser("replay", help="replay reference_sample.yaml against the current analysis")
    common(p)
    p.add_argument("--reference", required=True)
    p.set_defaults(func=_replay)
