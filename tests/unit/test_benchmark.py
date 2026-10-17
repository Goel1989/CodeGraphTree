"""`cgs benchmark` and the phase instrumentation of the scan (corrective audit §7)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.helpers import FIXTURES

from codegraph_sci.benchmark import PHASES


def test_scan_reports_every_phase_and_file_counts(tmp_path: Path) -> None:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    stats = scan(open_project(FIXTURES / "fortran_basic" / "src", tmp_path / "p"), ScanOptions(jobs=1)).stats
    assert set(PHASES) <= set(stats["phases_ms"])
    assert stats["files"] == {"reused": 0, "full_parsed": 3, "outline_parsed": 0, "failed": 0, "timeout": 0}
    parts = sum(v for k, v in stats["phases_ms"].items() if k not in ("total_ms", "extract_full_ms",
                                                                      "extract_outline_ms"))
    assert parts <= stats["phases_ms"]["total_ms"] + 1.0


def test_benchmark_cold_unchanged_and_changed_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    src = tmp_path / "src"
    shutil.copytree(FIXTURES / "fortran_basic" / "src", src)
    before = {p: p.read_bytes() for p in src.rglob("*") if p.is_file()}
    try:
        assert main(["benchmark", str(src), "--changed", "2", "--jobs", "1", "--json",
                     "--output", str(tmp_path / "bench.json")]) == 0
    finally:
        netguard.uninstall()
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads((tmp_path / "bench.json").read_text(encoding="utf-8"))
    names = [r["name"] for r in report["runs"]]
    assert names == ["cold_full", "rescan_unchanged", "rescan_2_changed"]
    cold, warm, changed = report["runs"]
    assert cold["files"]["full_parsed"] == 3 and warm["files"]["reused"] == 3 and warm["files"]["full_parsed"] == 0
    assert changed["files"]["full_parsed"] == 2 and changed["files"]["reused"] == 1
    assert report["machine"]["cpu_count"] and report["tool_version"]
    assert {p: p.read_bytes() for p in src.rglob("*") if p.is_file()} == before  # sources never modified
