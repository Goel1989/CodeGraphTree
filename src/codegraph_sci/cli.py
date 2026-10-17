"""Command line interface ``cgs``."""

from __future__ import annotations

import argparse
import errno
import json
import math
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
    from codegraph_sci.core.profile import AnalysisProfile
    from codegraph_sci.extract.registry import LanguagePackageError
    from codegraph_sci.scan import language_hints, language_registry

    project = open_project(root, args.project)
    previous = load_profile(project.profile_path) if project.profile_path.is_file() else None
    try:
        hints = language_hints(language_registry(project, previous or AnalysisProfile()))
    except LanguagePackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = run_inventory(root, previous, hints=hints)
    profile = profile_from_inventory(result, previous)
    if not args.no_write:
        save_profile(project.profile_path, profile)
    if args.json:
        sys.stdout.write(json.dumps(inventory_dict(result, entries=args.entries), indent=1, ensure_ascii=False)
                         + "\n")
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

    from codegraph_sci.extract.registry import LanguagePackageError

    options = ScanOptions(full=args.full, timeout_s=args.timeout)
    if args.jobs:
        options.jobs = args.jobs
    try:
        result = scan(project, options, progress)
    except LanguagePackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.progress != "json":
        s = result.stats
        print(f"Database: {result.db_path}")
        print(f"Files: {s['files_source']} source ({s['files_extracted']} extracted, {s['files_cached']} from cache, "
              f"{s['files_failed']} failed, {s['files_fallback']} fallback)")
        print(f"Nodes: {s['nodes']}  call sites: {s['call_sites']} (resolved {s['resolved']}, ambiguous "
              f"{s['ambiguous']}, external {s['external']}, out of scope {s['out_of_scope']}, unresolved "
              f"{s['unresolved']})  edges: {s['edges']}  time: {s['seconds']} s")
    return 0


def _cmd_languages(args: argparse.Namespace) -> int:
    """Language packages: the one selected for each language (with its level), and the inactive ones."""
    from codegraph_sci.core.profile import AnalysisProfile
    from codegraph_sci.core.project import open_project
    from codegraph_sci.extract.registry import LanguagePackageError
    from codegraph_sci.inventory.profile_io import load_profile
    from codegraph_sci.scan import language_registry

    project = open_project(args.root, args.project)
    profile = load_profile(project.profile_path) if project.profile_path.is_file() else AnalysisProfile()
    try:
        registry = language_registry(project, profile)
    except LanguagePackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"packages": [registry.packages[k].summary() for k in sorted(registry.packages)],
                          "inactive": [{**i.package.summary(), "reason": i.reason} for i in registry.inactive]},
                         indent=1, ensure_ascii=False))
        return 0
    print(f"{'Language':<16}{'Version':<10}{'Level':<10}{'Backend':<18}Extensions")
    for lang, p in sorted(registry.packages.items()):
        print(f"{lang:<16}{p.version:<10}{p.level:<10}{p.backend:<18}{' '.join(p.extensions)}")
    for i in registry.inactive:
        print(f"inactive: {i.package.language} ({i.package.level}, {i.package.path}): {i.reason}")
    return 0


def _cmd_rules(args: argparse.Namespace) -> int:
    """Rule workflow: exit code 0 success, 1 invalid rule or failing tests, 2 usage error."""
    from codegraph_sci.core.project import open_project
    from codegraph_sci.rules import RuleWorkflowError, activate_rule, new_rule, run_rule_tests, validate_rule

    try:
        if args.action == "new":
            if not args.root:
                print("error: cgs rules new <kind> <name> <repository folder> [--project P]", file=sys.stderr)
                return 2
            path = new_rule(args.kind, args.name, open_project(args.root, args.project), extension=args.extension)
            print(f"created {path} (proposed): edit it, then cgs rules test {path}")
            return 0
        path = Path(args.path)
        if args.action == "validate":
            check = validate_rule(path)
            for error in check.errors:
                print(f"error: {error}")
            print(f"{check.kind or 'rule'} {check.name or path.name}: {'invalid' if check.errors else 'valid'}")
            return 1 if check.errors else 0
        if args.action == "test":
            results = run_rule_tests(path)
            for result in results:
                print(f"[{'PASS' if result.passed else 'FAIL'}] {result.name}")
                for detail in result.details:
                    print(f"    {detail}")
            if not results:
                print("no test case declared: at least one is required before activation")
            return 0 if results and all(r.passed for r in results) else 1
        print(activate_rule(path))
        return 0
    except RuleWorkflowError as exc:
        print(f"error: {exc}")
        return 1


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


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from codegraph_sci.benchmark import print_report, run_benchmark

    source = Path(args.root)
    if not source.is_dir():
        print(f"error: {source} is not a directory", file=sys.stderr)
        return 2
    report = run_benchmark(source, project=Path(args.project) if args.project else None, changed=args.changed,
                           jobs=args.jobs)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print_report(report)
    return 0


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
    elif args.action == "inventory-policy":
        if args.glob not in ("analysis", "complete"):
            raise SystemExit("error: inventory-policy takes 'analysis' or 'complete'")
        profile.inventory_policy = args.glob
        change = ("excluded content recorded in the inventory (never analyzed)" if args.glob == "complete"
                  else "excluded folders recorded without their content")
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


def _deadline(text: str) -> float:
    """Per-file extraction deadline: a finite number of seconds greater than zero (rule 12)."""
    try:
        value = float(text)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r}: a finite number of seconds greater than zero is required")
    return value


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
    p.add_argument("--entries", action="store_true", help="JSON output: also list every discovered entry")
    p.set_defaults(func=_cmd_inventory)

    p = sub.add_parser("scan", help="analyse a repository (deterministic, reads only the analysis profile)")
    p.add_argument("root", help="repository folder")
    p.add_argument("--project", help="project folder (default: in the user data folder)")
    p.add_argument("--jobs", type=int, default=0, help="worker processes (default: cores - 1)")
    p.add_argument("--timeout", type=_deadline, default=60.0,
                   help="deadline per file, in seconds (finite, greater than zero; rule 12)")
    p.add_argument("--full", action="store_true", help="ignore the facts cache")
    p.add_argument("--progress", choices=["text", "json"], default="text", help="progress format")
    p.set_defaults(func=_cmd_scan)

    p = sub.add_parser("languages", help="list the language packages (built-in, user, project) and their selection")
    p.add_argument("root", help="repository folder")
    p.add_argument("--project", help="project folder (default: in the user data folder)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=_cmd_languages)

    p = sub.add_parser("rules", help="create, validate, test and activate rules (guide: docs/rules/README.md)")
    rules = p.add_subparsers(dest="action", metavar="ACTION", required=True)
    q = rules.add_parser("new", help="create a rule from its template (proposed)")
    q.add_argument("kind", choices=["language", "bridge", "project"])
    q.add_argument("name", help="rule name: lower case letters, digits and _")
    q.add_argument("root", nargs="?", help="repository folder")
    q.add_argument("--project", help="project folder (default: in the user data folder)")
    q.add_argument("--extension", help="language: file extension (default: .<name>)")
    for action, text in (("validate", "check syntax, schema, pattern limits and test files"),
                         ("test", "run the rule's test cases"),
                         ("activate", "validate, test (all must pass), then approve")):
        q = rules.add_parser(action, help=text)
        q.add_argument("path", help="rule file (language.yaml, bridges/<name>.yaml, projects/<name>.yaml)")
    p.set_defaults(func=_cmd_rules)

    p = sub.add_parser("benchmark", help="measure the analysis phases: cold, unchanged and changed rescans")
    p.add_argument("root", help="source folder (never modified)")
    p.add_argument("--project", help="project folder to use (default: a temporary one, removed afterwards)")
    p.add_argument("--changed", type=int, default=0, help="also rescan with N files re-extracted (simulated)")
    p.add_argument("--jobs", type=int, help="worker processes (default: CPU count - 1)")
    p.add_argument("--json", action="store_true", help="JSON report")
    p.add_argument("--output", help="also write the JSON report to this file")
    p.set_defaults(func=_cmd_benchmark)
    p = sub.add_parser("profile", help="show or change the analysis profile")
    p.add_argument("action", choices=["show", "set-language", "ignore", "all-subfolders", "inventory-policy"])
    p.add_argument("root", help="repository folder")
    p.add_argument("glob", nargs="?", default="",
                   help="file glob (set-language), extension (ignore), on/off (all-subfolders) or "
                        "analysis/complete (inventory-policy)")
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
