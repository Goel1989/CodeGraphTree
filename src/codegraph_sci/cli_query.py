"""Query commands of ``cgs``: file dependencies (``files``, D41), dependency table (``deps``), search, health, and the
symbol-level checking tools (callers, callees, path, impact, data, unresolved; lot 9)."""

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
from codegraph_sci.query.types import (
    DEPENDENCY_SORTS,
    RELATIONSHIPS,
    CallerReport,
    DependencyFilter,
    Direction,
    NodeSummary,
)


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
    open_sites = []
    if report.unresolved_sites:
        open_sites.append(f"{report.unresolved_sites} unresolved call site(s)")
    if report.ambiguous_sites:
        open_sites.append(f"{report.ambiguous_sites} ambiguous call site(s)"
                          + (" listing it as a candidate" if direction is Direction.CALLERS else ""))
    if open_sites:
        print(f"  (not counted above: {', '.join(open_sites)}; see `cgs unresolved --ambiguous`)")
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
            if s.evidence.get("mechanism"):  # bridges: the mechanism and the declaration that justify the link
                extra.append(f"via {s.evidence['mechanism']}"
                             + (f" ({s.evidence['binding']})" if s.evidence.get("binding") else ""))
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
        categories = q.reference_categories()
    if args.json:
        _json({**dataclasses.asdict(health), "reference_categories": dataclasses.asdict(categories)})
        return 0
    print("Files: " + ", ".join(f"{k} {v}" for k, v in health.files_by_status.items()))
    print("Call sites: " + ", ".join(f"{k} {v}" for k, v in health.sites_by_resolution.items()))
    print(f"Unresolved rate: {health.unresolved_rate:.2%}   ambiguous sites: {health.ambiguous}")
    total = categories.references_total
    print("Non-resolved references by category (every one counted once): " + ", ".join(
        f"{name} {n} ({n / total:.1%})" if total else f"{name} {n}" for name, n in categories.counts.items()))
    last = health.last_scan
    if last:
        print(f"Last analysis: {last['finished_at']}  profile v{last['profile_version']}  "
              f"{last['stats'].get('seconds', '?')} s")
    for f in health.failures[:20]:
        print(f"  {f['status']:<9} {f['path']}: {f['error']}")
    return 0


def cmd_view3d(args: argparse.Namespace) -> int:
    """3D view of the connections between functions and files (PyWebView window, or an HTML export)."""
    from codegraph_sci.ui.view3d.html import build_html

    db = _db(args)
    with GraphQuery(db) as q:
        if args.routine.startswith("file:"):
            uid, label = args.routine, args.routine[5:]
        else:
            node = _pick(q, args.routine)
            uid, label = node.uid, node.display_name
        if args.export:
            graph = q.graph3d(uid, mode=args.mode, depth=args.depth, max_nodes=args.max_nodes,
                              hide_noise=not args.all)
            Path(args.export).write_text(build_html(graph, label), encoding="utf-8")
            print(f"{len(graph.nodes)} node(s), {len(graph.links)} link(s) written to {args.export}")
            return 0
    from codegraph_sci.ui.view3d.app import run_window

    return run_window(db, uid, label, mode=args.mode, depth=args.depth, max_nodes=args.max_nodes,
                      hide_noise=not args.all)


def _file_relation(rel: Any) -> dict[str, Any]:
    return {"path": rel.path, "lang": rel.lang, "relationships": dict(sorted(rel.relationships.items())),
            "confirmed": rel.confirmed,
            "details": [{"relationship": d.relationship, "resolution": d.resolution, "count": d.count}
                        for d in rel.details]}


def cmd_files(args: argparse.Namespace) -> int:
    """File dependencies (D39-D41): what a file depends on, what depends on it, what a change may affect, cycles."""
    wanted = set(args.relationship or ())
    resolution = args.resolution
    with GraphQuery(_db(args)) as q:
        try:
            if args.action == "cycles":
                cycles = q.file_cycles(confirmed_only=args.confirmed_only)
                if args.json:
                    _json(cycles)
                    return 0
                print(f"{len(cycles)} file cycle(s)" + (" (confirmed dependencies only)" if args.confirmed_only
                                                        else " (possible dependencies included)"))
                for c in cycles:
                    print(f"  {len(c):>4} files  {', '.join(c)}")
                return 0
            if not args.file:
                raise SystemExit(f"error: `cgs files {args.action}` needs a file (repository-relative path)")
            if args.action == "impact":
                impact = q.file_impact(args.file, max_depth=args.max_depth)
                if args.json:
                    _json(impact)
                    return 0
                print(f"Changing {args.file} may affect {len(impact.confirmed) + len(impact.possible)} file(s): "
                      f"{len(impact.confirmed)} confirmed, {len(impact.possible)} possible")
                rows = sorted([(impact.depth[f], f, "confirmed") for f in impact.confirmed]
                              + [(impact.depth[f], f, "possible") for f in impact.possible])
                for depth, path, certainty in rows:
                    print(f"  [{depth}] {path}  {certainty}")
                return 0
            relations = q.file_relations(args.file, incoming=args.action == "dependents")
        except QueryError as exc:
            raise SystemExit(f"error: {exc}") from exc
    out = []
    for rel in relations:
        details = [d for d in rel.details if (not wanted or d.relationship in wanted)
                   and (resolution is None or d.confirmed == (resolution == "confirmed"))]
        if details:
            out.append(dataclasses.replace(rel, details=details,
                                           relationships={r: sum(d.count for d in details if d.relationship == r)
                                                          for r in sorted({d.relationship for d in details})},
                                           confirmed=any(d.confirmed for d in details)))
    if args.json:
        _json([_file_relation(r) for r in out])
        return 0
    if args.action == "dependents":
        print(f"{len(out)} file(s) depend on {args.file}")
    else:
        print(f"{args.file} depends on {len(out)} file(s)")
    for rel in out:
        kinds = ", ".join(f"{k} {v}" for k, v in rel.relationships.items())
        print(f"  {rel.path:<60} {kinds:<30} {'confirmed' if rel.confirmed else 'possible'}")
    return 0


DEP_COLUMNS = ("caller", "caller_file", "caller_lang", "target_text", "target", "candidates", "target_file",
               "target_lang", "relationship", "line", "col", "resolution", "confidence", "rule", "condition")
GROUP_COLUMNS = ("source", "target", "relationship", "count", "statuses")


def cmd_deps(args: argparse.Namespace) -> int:
    """Dependency table (every relationship), filtered and sorted by the database; table, CSV or JSON."""
    import csv

    filters = DependencyFilter(text=args.text, relationships=tuple(args.relationship or ()),
                               statuses=tuple(args.status or ()), language=args.language, path=args.path,
                               caller=args.caller, target=args.target, rule=args.rule)
    with GraphQuery(_db(args)) as q:
        def page(offset: int, size: int) -> Any:
            if args.level == "site":
                return q.dependencies(filters, sort=args.sort, descending=args.desc, limit=size, offset=offset)
            sort = args.sort if args.sort in ("target", "relationship") else "source"
            return q.dependency_groups(args.level, filters, sort=sort, descending=args.desc, limit=size,
                                       offset=offset)

        rows: list[Any] = []
        first = page(args.offset, min(args.limit or 5000, 5000))
        total = first.total
        rows += first.rows
        while (args.limit is None or len(rows) < args.limit) and args.offset + len(rows) < total and first.rows:
            first = page(args.offset + len(rows), 5000)
            rows += first.rows
        if args.limit is not None:
            rows = rows[:args.limit]
    columns = DEP_COLUMNS if args.level == "site" else GROUP_COLUMNS

    def record(row: Any) -> dict[str, Any]:
        data = {c: getattr(row, c) for c in columns}
        if "candidates" in data:
            data["candidates"] = " ".join(data["candidates"])
        if "statuses" in data:
            data["statuses"] = " ".join(f"{k}={v}" for k, v in data["statuses"].items())
        return data

    out = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout  # noqa: SIM115
    try:
        if args.format == "json":
            out.write(json.dumps({"level": args.level, "total": total, "offset": args.offset,
                                  "rows": [record(r) for r in rows]}, indent=1, ensure_ascii=False) + "\n")
        elif args.format == "csv":
            writer = csv.DictWriter(out, fieldnames=list(columns), lineterminator="\n")
            writer.writeheader()
            writer.writerows(record(r) for r in rows)
        else:
            for r in rows:
                if args.level == "site":
                    target = r.target or (" | ".join(r.candidates) if r.candidates else "-")
                    out.write(f"{r.caller_file}:{r.line}:{r.col}  {r.relationship:<19} {r.caller}  ->  {target}  "
                              f"[{r.resolution}, {r.rule}]\n")
                else:
                    out.write(f"{r.count:>6}  {r.relationship:<19} {r.source}  ->  {r.target or '-'}\n")
            out.write(f"{len(rows)} of {total} row(s)\n")
    finally:
        if args.output:
            out.close()
    return 0


def register(sub: Any) -> None:
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", help="repository folder (default: current folder)")
        p.add_argument("--project", help="project folder")
        p.add_argument("--db", help="project database")
        p.add_argument("--json", action="store_true", help="JSON output")

    p = sub.add_parser("files", help="file dependencies: dependencies, dependents, impact or cycles of files")
    p.add_argument("action", choices=["dependencies", "dependents", "impact", "cycles"])
    p.add_argument("file", nargs="?", help="repository-relative path (not for cycles)")
    p.add_argument("--relationship", action="append", choices=list(RELATIONSHIPS), help="repeatable")
    p.add_argument("--resolution", choices=["confirmed", "possible"], help="keep confirmed or possible links only")
    p.add_argument("--max-depth", type=int, default=None, help="impact: levels of dependents")
    p.add_argument("--confirmed-only", action="store_true", help="cycles: ignore possible dependencies")
    common(p)
    p.set_defaults(func=cmd_files)
    for name, helptext in (("callers", "symbol level: which routines call X (checking tool)"),
                           ("callees", "symbol level: what X calls (checking tool)")):
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
    p = sub.add_parser("file-links", help="files linked to a file (calls and uses; see `cgs files`)")
    p.add_argument("file", help="repository-relative path")
    common(p)
    p.set_defaults(func=cmd_file_links)
    p = sub.add_parser("path", help="symbol level: how routine A reaches routine B (checking tool)")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("-k", type=int, default=5, help="number of paths")
    p.add_argument("--max-len", type=int, default=15)
    p.add_argument("--edge-kinds", choices=["call_path", "file_dependency"], default="call_path")
    common(p)
    p.set_defaults(func=cmd_path)
    p = sub.add_parser("impact", help="symbol level: routines concerned if X changes (files: `cgs files impact`)")
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
    p = sub.add_parser("view3d", help="3D view of the connections between functions and files")
    p.add_argument("routine", help="routine name or identifier, or file:<path>")
    p.add_argument("--mode", choices=["functions", "files", "both"], default="both")
    p.add_argument("--depth", type=int, default=2, help="levels of callers and callees")
    p.add_argument("--max-nodes", type=int, default=400)
    p.add_argument("--all", action="store_true", help="also show utility routines (noise)")
    p.add_argument("--export", help="write a self-contained HTML page instead of opening a window")
    common(p)
    p.set_defaults(func=cmd_view3d)
    p = sub.add_parser("deps", help="dependency table: every relationship, filtered, sorted, exported")
    p.add_argument("--text", help="search caller, target, resolved target and file")
    p.add_argument("--relationship", action="append", choices=list(RELATIONSHIPS), help="repeatable")
    p.add_argument("--status", action="append", choices=["resolved", "ambiguous", "external", "out_of_scope",
                                                         "unresolved"], help="repeatable")
    p.add_argument("--language", help="language of the caller's file")
    p.add_argument("--path", help="caller files under this path")
    p.add_argument("--caller", help="exact caller identifier")
    p.add_argument("--target", help="exact target identifier")
    p.add_argument("--rule", help="resolution rule (origin) starting with this text")
    p.add_argument("--level", choices=["site", "entity", "file", "directory"], default="site",
                   help="site: every occurrence; others: aggregated rows")
    p.add_argument("--sort", choices=list(DEPENDENCY_SORTS), default="path")
    p.add_argument("--desc", action="store_true", help="descending order")
    p.add_argument("--limit", type=int, help="number of rows (default: all)")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--format", choices=["table", "csv", "json"], default="table")
    p.add_argument("-o", "--output", help="write to this file")
    common(p)
    p.set_defaults(func=cmd_deps)
    p = sub.add_parser("health", help="health of the analysis")
    common(p)
    p.set_defaults(func=cmd_health)


__all__ = ["register", "QueryError"]
