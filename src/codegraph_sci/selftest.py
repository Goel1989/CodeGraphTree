"""``cgs selftest``: checks that the portable folder works on this machine, offline."""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

from codegraph_sci.core import netguard
from codegraph_sci.core.cpu import instruction_sets
from codegraph_sci.core.paths import data_dir
from codegraph_sci.core.versions import APP_VERSION


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _check_qt() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    _ = app
    return f"Qt {QtCore.qVersion()}"


def _check_tree_sitter() -> str:
    import tree_sitter
    import tree_sitter_c
    import tree_sitter_cpp
    import tree_sitter_fortran
    import tree_sitter_python

    names = []
    for name, mod in (("fortran", tree_sitter_fortran), ("python", tree_sitter_python),
                      ("c", tree_sitter_c), ("cpp", tree_sitter_cpp)):
        parser = tree_sitter.Parser(tree_sitter.Language(mod.language()))
        parser.parse(b"\n")
        names.append(name)
    return "grammars: " + ", ".join(names)


def _check_sqlite() -> str:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.execute("INSERT INTO t VALUES ('hello world')")
        n = con.execute("SELECT count(*) FROM t WHERE t MATCH 'hello'").fetchone()[0]
        if n != 1:
            raise RuntimeError("FTS5 query failed")
    finally:
        con.close()
    return f"SQLite {sqlite3.sqlite_version} with FTS5"


def _check_data_dir() -> str:
    path = data_dir()
    with tempfile.NamedTemporaryFile(dir=path, prefix="selftest-", delete=True) as handle:
        handle.write(b"ok")
    return str(path)


def _check_cpu() -> str:
    sets = instruction_sets()
    return " ".join(f"{k}={'yes' if v else 'no'}" for k, v in sets.items())


def _check_network() -> str:
    import socket

    if not netguard.is_installed():
        raise RuntimeError("network guard is not installed")
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
    except Exception:  # noqa: BLE001 - any refusal means the guard works
        return "network sockets are blocked"
    raise RuntimeError("network guard is not active")


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("qt", _check_qt),
    ("tree-sitter", _check_tree_sitter),
    ("sqlite-fts5", _check_sqlite),
    ("data-dir", _check_data_dir),
    ("cpu", _check_cpu),
    ("offline", _check_network),
]


def run_selftest() -> list[CheckResult]:
    """Run every check with the network guard active."""
    netguard.install()
    results = []
    for name, check in CHECKS:
        try:
            results.append(CheckResult(name, True, check()))
        except Exception as exc:  # noqa: BLE001 - every failure is reported
            results.append(CheckResult(name, False, f"{type(exc).__name__}: {exc}"))
    return results


def header() -> str:
    return (f"CodeGraph-Sci {APP_VERSION} - Python {platform.python_version()} - "
            f"{platform.system()} {platform.machine()} - {sys.executable}")
