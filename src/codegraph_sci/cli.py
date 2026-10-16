"""Command line interface ``cgs``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from codegraph_sci.core import netguard
from codegraph_sci.core.versions import APP_VERSION


def _cmd_selftest(args: argparse.Namespace) -> int:
    from codegraph_sci.selftest import header, run_selftest

    print(header())
    results = run_selftest()
    for res in results:
        print(f"[{'OK' if res.ok else 'FAIL'}] {res.name:<12} {res.detail}")
    failed = [r for r in results if not r.ok]
    print("selftest: " + ("PASSED" if not failed else f"FAILED ({len(failed)} check(s))"))
    return 0 if not failed else 1


def _cmd_export(args: argparse.Namespace) -> int:
    from codegraph_sci.store.export import export_json

    text = export_json(args.db)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_inventory(args: argparse.Namespace) -> int:
    import json

    from codegraph_sci.core.project import open_project
    from codegraph_sci.inventory.profile_io import load_profile, profile_from_inventory, save_profile
    from codegraph_sci.inventory.report import inventory_dict, inventory_table
    from codegraph_sci.inventory.run import run_inventory

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    project = open_project(root, args.project)
    previous = load_profile(project.profile_path) if project.profile_path.is_file() else None
    result = run_inventory(root, previous)
    profile = profile_from_inventory(result, previous)
    if not args.no_write:
        save_profile(project.profile_path, profile)
    if args.json:
        sys.stdout.write(json.dumps(inventory_dict(result), indent=1, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(inventory_table(result))
        if not args.no_write:
            print(f"Profile: {project.profile_path} (version {profile.profile_version})")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    import json

    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    project = open_project(root, args.project)

    def progress(event: dict[str, object]) -> None:
        if args.progress == "json":
            print(json.dumps(event, ensure_ascii=False), flush=True)
        elif event["event"] in ("extract", "done"):
            print(" ".join(f"{k}={v}" for k, v in event.items()), file=sys.stderr, flush=True)

    options = ScanOptions(full=args.full, timeout_s=args.timeout)
    if args.jobs:
        options.jobs = args.jobs
    result = scan(project, options, progress)
    if args.progress != "json":
        s = result.stats
        print(f"Database: {result.db_path}")
        print(f"Files: {s['files_source']} source ({s['files_extracted']} extracted, {s['files_cached']} from cache, "
              f"{s['files_failed']} failed, {s['files_fallback']} fallback)")
        print(f"Nodes: {s['nodes']}  call sites: {s['call_sites']} (resolved {s['resolved']}, ambiguous "
              f"{s['ambiguous']}, external {s['external']}, out of scope {s['out_of_scope']}, unresolved "
              f"{s['unresolved']})  edges: {s['edges']}  time: {s['seconds']} s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cgs", description="CodeGraph-Sci command line.")
    parser.add_argument("--version", action="version", version=f"CodeGraph-Sci {APP_VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("selftest", help="check that this installation works offline")
    p.set_defaults(func=_cmd_selftest)

    p = sub.add_parser("inventory", help="detect the languages of a repository and write the profile")
    p.add_argument("root", help="repository folder")
    p.add_argument("--project", help="project folder (default: in the user data folder)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--no-write", action="store_true", help="do not write the analysis profile")
    p.set_defaults(func=_cmd_inventory)

    p = sub.add_parser("scan", help="analyse a repository (deterministic, reads only the analysis profile)")
    p.add_argument("root", help="repository folder")
    p.add_argument("--project", help="project folder (default: in the user data folder)")
    p.add_argument("--jobs", type=int, default=0, help="worker processes (default: cores - 1)")
    p.add_argument("--timeout", type=float, default=60.0, help="time limit per file, in seconds")
    p.add_argument("--full", action="store_true", help="ignore the facts cache")
    p.add_argument("--progress", choices=["text", "json"], default="text", help="progress format")
    p.set_defaults(func=_cmd_scan)

    p = sub.add_parser("export", help="canonical export of a project database")
    p.add_argument("format", choices=["json"])
    p.add_argument("db", help="project database (.sqlite)")
    p.add_argument("-o", "--output", help="output file (default: stdout)")
    p.set_defaults(func=_cmd_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    netguard.install()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
