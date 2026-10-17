"""Command line interface ``cgs``."""

from __future__ import annotations

import argparse
import errno
import json
import os
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


def _cmd_audit_corpus(args: argparse.Namespace) -> int:
    """Exit codes: 0 all required PASS, 1 a required FAIL, 2 configuration error, 3 internal audit error."""
    from codegraph_sci.corpus_audit import (
        EXIT_CONFIG,
        EXIT_INTERNAL,
        AuditConfigError,
        AuditOptions,
        print_report,
        run_audit,
    )

    try:
        report = run_audit(AuditOptions(Path(args.manifest), Path(args.project) if args.project else None,
                                        scan=not args.no_scan))
    except AuditConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception as exc:  # noqa: BLE001 - never report success when the audit itself broke
        print(f"internal audit error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    else:
        print_report(report)
    return int(report["exit_code"])


def _cmd_profile(args: argparse.Namespace) -> int:
    """Changes of the analysis profile made by the user (each one creates a new profile version)."""
    from codegraph_sci.core.profile import FileOverride, HistoryEntry, IgnoredGroup
    from codegraph_sci.core.project import open_project
    from codegraph_sci.inventory.profile_io import load_profile, profile_from_inventory, save_profile
    from codegraph_sci.inventory.run import run_inventory

    project = open_project(args.root, args.project)
    profile = load_profile(project.profile_path) if project.profile_path.is_file() else profile_from_inventory(
        run_inventory(project.root))
    if args.action == "set-language":
        profile.file_overrides = [o for o in profile.file_overrides if o.glob != args.glob]
        profile.file_overrides.append(FileOverride(args.glob, args.language, args.reason or "forced by the user"))
        change = f"language of {args.glob} forced to {args.language}"
    elif args.action == "ignore":
        ext = args.glob if args.glob.startswith(".") else f".{args.glob}"
        profile.ignored = [g for g in profile.ignored if g.ext != ext]
        profile.ignored.append(IgnoredGroup(ext, 0, args.reason or "ignored by the user"))
        change = f"extension {ext} ignored"
    elif args.action == "all-subfolders":
        if args.glob not in ("on", "off"):
            raise SystemExit("error: all-subfolders takes 'on' or 'off'")
        profile.all_subfolders = args.glob == "on"
        change = ("every sub-folder analyzed (.gitignore and default exclusions ignored)" if profile.all_subfolders
                  else ".gitignore and default folder exclusions applied")
    else:
        print(json.dumps(profile.to_dict(), indent=1, ensure_ascii=False))
        return 0
    profile.profile_version += 1
    profile.history.append(HistoryEntry(profile.profile_version, change, "user"))
    save_profile(project.profile_path, profile)
    print(f"profile v{profile.profile_version}: {change}")
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

    p = sub.add_parser("profile", help="show or change the analysis profile")
    p.add_argument("action", choices=["show", "set-language", "ignore", "all-subfolders"])
    p.add_argument("root", help="repository folder")
    p.add_argument("glob", nargs="?", default="", help="file glob (set-language), extension (ignore) or on/off (all-subfolders)")
    p.add_argument("language", nargs="?", default="", help="language (set-language)")
    p.add_argument("--project", help="project folder")
    p.add_argument("--reason", help="reason recorded in the profile")
    p.set_defaults(func=_cmd_profile)

    p = sub.add_parser("export", help="canonical export of a project database")
    p.add_argument("format", choices=["json"])
    p.add_argument("db", help="project database (.sqlite)")
    p.add_argument("-o", "--output", help="output file (default: stdout)")
    p.set_defaults(func=_cmd_export)

    from codegraph_sci.audit.commands import register as register_audit
    from codegraph_sci.cli_ai import register as register_ai
    from codegraph_sci.cli_query import register as register_query

    register_query(sub)
    register_ai(sub)

    register_audit(sub, _cmd_audit_corpus)
    _register_extensions(sub)
    return parser


def _register_extensions(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Commands added by installed extensions (entry point group ``codegraph_sci.commands``).

    The core never imports an extension by name: an extension declares itself, and its absence
    or failure never blocks the core.
    """
    from importlib.metadata import entry_points

    for ep in sorted(entry_points(group="codegraph_sci.commands"), key=lambda e: e.name):
        try:
            ep.load()(sub)
        except Exception as exc:  # noqa: BLE001 - an extension must never block the core
            print(f"warning: extension '{ep.name}' not loaded: {exc}", file=sys.stderr)


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
    try:
        result: int = args.func(args)
        sys.stdout.flush()
    except OSError as exc:
        # The reader went away (``cgs … | head``): stop quietly, and keep the interpreter's final flush silent.
        # Windows reports a closed pipe as EINVAL rather than EPIPE.
        if not (isinstance(exc, BrokenPipeError) or (os.name == "nt" and exc.errno == errno.EINVAL)):
            raise
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    return result


if __name__ == "__main__":
    sys.exit(main())
