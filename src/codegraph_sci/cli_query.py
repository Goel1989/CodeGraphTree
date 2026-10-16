"""Query commands of ``cgs`` (lot 9): callers, callees, file-links, path, impact, find, data, unresolved, health."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from codegraph_sci.core.model import CALL_PATH, FILE_DEPENDENCY
from codegraph_sci.core.project import open_project
from codegraph_sci.query.api import GraphQuery, QueryError
from codegraph_sci.query.types import CallerReport, Direction, NodeSummary


def _db(args: argparse.Namespace) -> Path:
    if args.db:
        return Path(args.db)
    project = open_project(args.root, args.project) if args.project or args.root else open_project(".")
    if not project.db_path.is_file():
        raise SystemExit(f"error: no analysis for {project.root}; run `cgs scan {project.root}` first")
    return project.db_path


def _json(data: Any) -> None:
    def default(o: Any) -> Any:
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if hasattr(o, "value"):
            return o.value
        return str(o)

    sys.stdout.write(json.dumps(data, default=default, indent=1, ensure_ascii=False) + "\n")


def _pick(q: GraphQuery, name: str) -> NodeSummary:
    matches = q.resolve(name)
    routines = [m for m in matches if m.kind == "routine"]
    if len(matches) > 1 and len(routines) == 1:
        return routines[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        suggestions = q.find(name, limit=8)
        hint = "".join(f"\n  {s.uid}  ({s.file}:{s.line})" for s in suggestions)
        raise SystemExit(f"error: no symbol named '{name}'." + (f" Did you mean:{hint}" if hint else ""))
    listing = "".join(f"\n  {m.uid}  ({m.file}:{m.line})" for m in matches)
    raise SystemExit(f"error: '{name}' is ambiguous; use one of these identifiers:{listing}")


def _print_report(report: CallerReport, direction: Direction) -> None:
    t = report.target
    where = f"{t.file}:{t.line}" if t.file else "outside the repository"
    if direction is Direction.CALLERS:
        print(f"{t.display_name} ({t.uid}, {where}) is called by {report.count} routine(s) "
              f"in {report.file_count} file(s), {report.site_count} call site(s)")
    else:
        print(f"{t.display_name} ({t.uid}, {where}) calls {report.count} routine(s), "
              f"{report.site_count} call site(s)")
    if report.hidden_noise:
        print(f"  (+{report.hidden_noise} utility routine(s) hidden; use --all)")
    for item in report.items:
        n = item.node
        loc = f"{n.file}:{n.line}" if n.file else n.uid.split(":", 1)[0]
        print(f"  {n.display_name:<32} {n.uid:<50} {loc}")
        for s in item.sites:
            extra = []
            if s.condition:
                extra.append(f"if {s.condition}")
            if s.confidence != "exact":
                extra.append(s.confidence)
            if s.origin != f"native:{n.lang}" and not s.origin.startswith("native:"):
                extra.append(s.origin)
            print(f"      {s.file}:{s.line}:{s.col}  {s.target_text}" + (f"  [{', '.join(extra)}]" if extra else ""))


def cmd_links(args: argparse.Namespace) -> int:
    direction = Direction.CALLERS if args.command == "callers" else Direction.CALLEES
    with GraphQuery(_db(args)) as q:
        node = _pick(q, args.routine)
        report = (q.callers if direction is Direction.CALLERS else q.callees)(node.uid, hide_noise=not args.all)
    if args.json:
        _json(report)
    else:
        _print_report(report, direction)
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    with GraphQuery(_db(args)) as q:
        results = q.find(args.text, set(args.kind) if args.kind else None, args.limit)
    if args.json:
        _json(results)
        return 0
    for r in results:
        print(f"{r.display_name:<32} {r.kind:<10} {r.uid:<50} {r.file or '-'}:{r.line or ''}  "
              f"callers={r.fan_in} callees={r.fan_out}")
    return 0 if results else 1


def cmd_file_links(args: argparse.Namespace) -> int:
    with GraphQuery(_db(args)) as q:
        out = {d.value: q.file_links(args.file, direction=d) for d in (Direction.CALLEES, Direction.CALLERS)}
    if args.json:
        _json(out)
        return 0
    for label, d in (("Files used by", "callees"), ("Files using", "callers")):
        print(f"{label} {args.file}:")
        for link in out[d]:
            print(f"  {link.file:<60} {link.kind:<6} {link.count}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    kinds = FILE_DEPENDENCY if args.edge_kinds == "file_dependency" else CALL_PATH
    with GraphQuery(_db(args)) as q:
        a, b = _pick(q, args.source), _pick(q, args.target)
        report = q.paths(a.uid, b.uid, edge_kinds=kinds, k=args.k, max_len=args.max_len)
    if args.json:
        _json(report)
        return 0
    if not report.paths:
        print(f"no path from {a.uid} to {b.uid} within {args.max_len} steps")
    for i, path in enumerate(report.paths, start=1):
        print(f"path {i} ({len(path.steps) - 1} steps):")
        for step in path.steps:
            arrow = "" if step.edge_kind is None else f"--{step.edge_kind}" + (" (possible)" if step.possible else "") \
                + (f", {step.confidence}" if step.confidence not in (None, "exact") else "") + "--> "
            print(f"   {arrow}{step.uid}")
    if report.truncated:
        print("(search stopped at its bounds: more paths may exist)")
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    with GraphQuery(_db(args)) as q:
        node = _pick(q, args.routine)
        report = q.impact(node.uid, max_depth=args.max_depth, limit=args.limit)
    if args.json:
        _json(report)
        return 0
    print(f"Changing {node.uid} concerns {report.total} routine(s) (transitive callers)"
          + (" - bounded" if report.truncated else ""))
    print("  by depth: " + ", ".join(f"{d}: {n}" for d, n in report.by_depth.items()))
    if report.entry_points:
        print(f"  entry points: {', '.join(report.entry_points[:20])}")
    for depth, s in report.items:
        print(f"  [{depth}] {s.display_name:<30} {s.uid:<50} {s.file or '-'}:{s.line or ''}")
    return 0


def cmd_data(args: argparse.Namespace) -> int:
    with GraphQuery(_db(args)) as q:
        node = _pick(q, args.routine)
        items = q.data_accesses(node.uid)
    if args.json:
        _json(items)
        return 0
    if not items:
        print(f"no data access recorded for {node.uid} (data accesses come with packs, lot 12)")
    for a in items:
        print(f"  {a.routine:<30} {a.mode:<8} {a.data:<40} ({a.key_kind})  {a.file}:{a.line}")
    return 0


def cmd_unresolved(args: argparse.Namespace) -> int:
    with GraphQuery(_db(args)) as q:
        groups = q.unresolved(include_ambiguous=args.ambiguous, limit=args.limit)
    if args.json:
        _json(groups)
        return 0
    for g in groups:
        ex = g.examples[0]
        print(f"{g.count:>6}  {g.lang:<8} {g.resolution:<10} {g.pattern:<30} {g.files} file(s)  "
              f"e.g. {ex['file']}:{ex['line']} {ex['target']}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    with GraphQuery(_db(args)) as q:
        health = q.scan_health()
    if args.json:
        _json(health)
        return 0
    print("Files: " + ", ".join(f"{k} {v}" for k, v in health.files_by_status.items()))
    print("Call sites: " + ", ".join(f"{k} {v}" for k, v in health.sites_by_resolution.items()))
    print(f"Unresolved rate: {health.unresolved_rate:.2%}   ambiguous sites: {health.ambiguous}")
    last = health.last_scan
    if last:
        print(f"Last analysis: {last['finished_at']}  profile v{last['profile_version']}  "
              f"{last['stats'].get('seconds', '?')} s")
    for f in health.failures[:20]:
        print(f"  {f['status']:<9} {f['path']}: {f['error']}")
    return 0


def register(sub: Any) -> None:
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", help="repository folder (default: current folder)")
        p.add_argument("--project", help="project folder")
        p.add_argument("--db", help="project database")
        p.add_argument("--json", action="store_true", help="JSON output")

    for name, helptext in (("callers", "how many routines call X, and which (default question)"),
                           ("callees", "what X calls")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("routine", help="name or identifier")
        p.add_argument("--all", action="store_true", help="also show utility routines (noise)")
        common(p)
        p.set_defaults(func=cmd_links)
    p = sub.add_parser("find", help="search routines, files, modules")
    p.add_argument("text")
    p.add_argument("--kind", action="append", help="node kind filter (repeatable)")
    p.add_argument("--limit", type=int, default=30)
    common(p)
    p.set_defaults(func=cmd_find)
    p = sub.add_parser("file-links", help="files linked to a file")
    p.add_argument("file", help="repository-relative path")
    common(p)
    p.set_defaults(func=cmd_file_links)
    p = sub.add_parser("path", help="how A reaches B")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("-k", type=int, default=5, help="number of paths")
    p.add_argument("--max-len", type=int, default=15)
    p.add_argument("--edge-kinds", choices=["call_path", "file_dependency"], default="call_path")
    common(p)
    p.set_defaults(func=cmd_path)
    p = sub.add_parser("impact", help="what is concerned if X changes")
    p.add_argument("routine")
    p.add_argument("--max-depth", type=int, default=None)
    p.add_argument("--limit", type=int, default=200)
    common(p)
    p.set_defaults(func=cmd_impact)
    p = sub.add_parser("data", help="data read or written by X")
    p.add_argument("routine")
    common(p)
    p.set_defaults(func=cmd_data)
    p = sub.add_parser("unresolved", help="unresolved sites grouped by pattern")
    p.add_argument("--ambiguous", action="store_true", help="include ambiguous sites")
    p.add_argument("--limit", type=int, default=50)
    common(p)
    p.set_defaults(func=cmd_unresolved)
    p = sub.add_parser("health", help="health of the analysis")
    common(p)
    p.set_defaults(func=cmd_health)


__all__ = ["register", "QueryError"]
