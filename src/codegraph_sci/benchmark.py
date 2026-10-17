"""``cgs benchmark``: measured analysis phases on a given machine (corrective audit §7: measure before optimizing).

Runs, on a private project folder (temporary unless one is given): a cold full analysis, a rescan without change
(cache), and optionally a rescan with ``N`` files re-extracted — simulated by ignoring their cached facts, the
sources are never modified. The report gives every phase in milliseconds, file counts per extraction mode, and the
machine, so that performance claims can be reproduced.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from codegraph_sci.core.project import open_project
from codegraph_sci.core.versions import APP_VERSION
from codegraph_sci.query.api import GraphQuery
from codegraph_sci.scan import ScanOptions, scan

PHASES = ("inventory_ms", "cache_lookup_ms", "extract_wall_ms", "extract_full_ms", "extract_outline_ms", "link_ms",
          "enrich_ms", "index_ms", "sqlite_write_ms", "total_ms")


def machine() -> dict[str, Any]:
    return {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
            "cpu_count": os.cpu_count(), "python": platform.python_version()}


def _run(name: str, stats: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "phases_ms": {p: stats["phases_ms"].get(p, 0.0) for p in PHASES}, "files": stats["files"],
            "files_source": stats["files_source"], "call_sites": stats.get("call_sites"), "jobs": stats.get("jobs")}


def changed_sample(db: Path, count: int) -> list[str]:
    """``count`` analysed files spread evenly over the sorted file list (deterministic)."""
    with GraphQuery(db) as q:
        paths = sorted(f["path"] for f in q.files() if f["status"] == "ok")
    if count <= 0 or not paths:
        return []
    step = max(1, len(paths) // count)
    return paths[::step][:count]


def run_benchmark(source: Path, *, project: Path | None = None, changed: int = 0,
                  jobs: int | None = None) -> dict[str, Any]:
    folder = project or Path(tempfile.mkdtemp(prefix="cgs-bench-"))
    try:
        target = open_project(source, folder)
        options = ScanOptions() if jobs is None else ScanOptions(jobs=jobs)
        runs = [_run("cold_full", scan(target, ScanOptions(jobs=options.jobs, full=True)).stats),
                _run("rescan_unchanged", scan(target, ScanOptions(jobs=options.jobs)).stats)]
        if changed:
            paths = changed_sample(target.db_path, changed)
            stats = scan(target, ScanOptions(jobs=options.jobs, force_paths=frozenset(paths))).stats
            runs.append({**_run(f"rescan_{len(paths)}_changed", stats), "changed_files": len(paths)})
    finally:
        if project is None:
            shutil.rmtree(folder, ignore_errors=True)
    return {"tool_version": APP_VERSION, "source": str(source), "machine": machine(), "runs": runs}


def print_report(report: dict[str, Any]) -> None:
    m = report["machine"]
    print(f"CodeGraph-Sci {report['tool_version']} on {m['platform']}, {m['cpu_count']} logical CPU(s), "
          f"Python {m['python']}")
    print(f"source: {report['source']}")
    header = f"{'phase (ms)':<20}" + "".join(f"{r['name']:>22}" for r in report["runs"])
    print(header)
    for phase in PHASES:
        print(f"{phase:<20}" + "".join(f"{r['phases_ms'][phase]:>22.1f}" for r in report["runs"]))
    for key in ("reused", "full_parsed", "outline_parsed", "failed", "timeout"):
        print(f"{'files ' + key:<20}" + "".join(f"{r['files'][key]:>22}" for r in report["runs"]))


__all__ = ["run_benchmark", "print_report", "sys"]
