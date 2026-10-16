"""Command line interface ``cgs``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cgs", description="CodeGraph-Sci command line.")
    parser.add_argument("--version", action="version", version=f"CodeGraph-Sci {APP_VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("selftest", help="check that this installation works offline")
    p.set_defaults(func=_cmd_selftest)
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
