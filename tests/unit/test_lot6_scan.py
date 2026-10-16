from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from tests.helpers import FIXTURES, graph_diff, load_expected, scan_fixture

from codegraph_sci.core.project import open_project
from codegraph_sci.scan import ScanOptions, python_module_namer, scan
from codegraph_sci.store.export import export_dict, export_json

GRAPH_FIXTURES = ["fortran_basic", "fortran_fixed_form", "fortran_preproc", "fortran_ambiguity",
                  "fortran_arrays_includes", "fortran_advanced", "fortran_data", "fortran_traps", "python_basic",
                  "c_basic", "cpp_basic", "cpp_overloads", "mini_hybrid", "partial_scope", "robustness"]


@pytest.mark.parametrize("name", GRAPH_FIXTURES)
def test_fixture_graph_equals_expected(name: str, tmp_path: Path) -> None:
    result = scan_fixture(name, tmp_path / "proj")
    diff = graph_diff(export_dict(result.db_path), load_expected(name))
    assert diff == [], "\n".join(diff)


def test_scan_is_deterministic(tmp_path: Path) -> None:
    a = scan_fixture("mini_hybrid", tmp_path / "a")
    b = scan_fixture("mini_hybrid", tmp_path / "b")
    assert export_json(a.db_path) == export_json(b.db_path)


def _copy(name: str, dest: Path) -> Path:
    shutil.copytree(FIXTURES / name / "src", dest)
    return dest


def test_incremental_cache(tmp_path: Path) -> None:
    repo = _copy("fortran_arrays_includes", tmp_path / "repo")
    shutil.copytree(FIXTURES / "fortran_basic" / "src", repo / "basic")
    first = scan_fixture("fortran_arrays_includes", tmp_path / "proj", repo)
    before = export_json(first.db_path)
    assert first.stats["files_extracted"] == 5
    again = scan_fixture("fortran_arrays_includes", tmp_path / "proj", repo)
    assert again.stats["files_extracted"] == 0 and again.stats["files_cached"] == 5
    assert export_json(again.db_path) == before
    # Modify one file: only that file is extracted again.
    solve = repo / "basic" / "solve.f90"
    solve.write_text(solve.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    third = scan_fixture("fortran_arrays_includes", tmp_path / "proj", repo)
    assert third.stats["files_extracted"] == 1
    # Modify an included file: every file that includes it is extracted again.
    inc = repo / "vars.inc"
    inc.write_text(inc.read_text(encoding="utf-8") + "      DIMENSION YGLOB(5)\n", encoding="utf-8")
    fourth = scan_fixture("fortran_arrays_includes", tmp_path / "proj", repo)
    assert fourth.stats["files_extracted"] == 2  # arrays.f (includes vars.inc) and vars.inc itself


def test_partial_scope_out_of_scope_is_not_unresolved(tmp_path: Path) -> None:
    result = scan_fixture("partial_scope", tmp_path / "proj")
    sites = export_dict(result.db_path)["call_sites"]
    by_target = {s["target_text"]: s["resolution"] for s in sites}
    assert by_target["lib_routine"] == "out_of_scope"
    assert by_target["missing_routine"] == "unresolved"
    assert "lib_inner" not in by_target  # calls of out-of-scope files are not extracted


def test_robustness_nothing_blocks(tmp_path: Path) -> None:
    repo = _copy("robustness", tmp_path / "repo")
    big = repo / "big.f90"
    with big.open("w", encoding="utf-8") as handle:
        line = "! " + "x" * 98 + "\n"
        handle.write("subroutine big_routine()\n")
        for _ in range(90_000):
            handle.write(line)
        handle.write("end subroutine big_routine\n")
    long_dir = repo
    try:
        for i in range(6):
            long_dir = long_dir / (f"long_directory_name_number_{i}_" + "y" * 20)
        long_dir.mkdir(parents=True)
        (long_dir / "deep_routine.f90").write_text("subroutine deep()\nend subroutine deep\n", encoding="utf-8")
        has_long = len(str(long_dir / "deep_routine.f90")) > 260
    except OSError:
        has_long = False
    result = scan_fixture("robustness", tmp_path / "proj", repo)
    data = export_dict(result.db_path)
    diff = graph_diff(data, load_expected("robustness"))
    assert diff == [], "\n".join(diff)
    status = {f["path"]: f["parse_status"] for f in data["files"]}
    expected_status = load_expected("robustness")["file_status"]
    for path, allowed in expected_status.items():
        assert status[path] in allowed, (path, status[path])
    assert status["big.f90"] == "failed"
    if has_long:
        assert any(n["uid"] == "f:deep" for n in data["nodes"])


def test_python_module_namer() -> None:
    namer = python_module_namer(["src/pkg/__init__.py", "src/pkg/sub/__init__.py", "src/pkg/sub/m.py",
                                 "scripts/run.py"])
    assert namer("src/pkg/sub/m.py") == "pkg.sub.m"
    assert namer("src/pkg/__init__.py") == "pkg"
    assert namer("scripts/run.py") == "scripts.run"


def test_cli_scan_json_progress(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    try:
        assert main(["scan", str(FIXTURES / "c_basic" / "src"), "--project", str(tmp_path / "p"),
                     "--progress", "json"]) == 0
    finally:
        netguard.uninstall()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["event"] == "start" and events[-1]["event"] == "done"


def _synthetic(tmp_path: Path, routines: int, files: int) -> tuple[Path, dict[str, object]]:
    sys.path.insert(0, str(Path(__file__).parents[1] / "synthetic"))
    from generate import generate

    repo = tmp_path / "syn"
    expected = generate(repo, routines=routines, files=files, seed=42)
    return repo, expected


def _check_synthetic(db: Path, expected: dict[str, object]) -> None:
    data = export_dict(db)
    routines = {n["uid"] for n in data["nodes"] if n["kind"] == "routine"}
    assert routines == set(expected["routines"])  # type: ignore[call-overload]
    got: dict[str, list[list[object]]] = {}
    for s in data["call_sites"]:
        if s["ref_kind"] in ("call", "maybe_call"):
            got.setdefault(s["src"], []).append([s["dst"], s["line"], s["col"]])
    calls = expected["calls"]
    assert isinstance(calls, dict)
    for src, sites in calls.items():
        assert sorted(got.get(src, []), key=str) == sorted(sites, key=str), src


def test_synthetic_small_parallel(tmp_path: Path) -> None:
    repo, expected = _synthetic(tmp_path, 1200, 120)
    project = open_project(repo, tmp_path / "proj")
    result = scan(project, ScanOptions(jobs=2))
    assert result.stats["files_failed"] == 0
    _check_synthetic(result.db_path, expected)


@pytest.mark.slow
def test_synthetic_full_size(tmp_path: Path) -> None:
    repo, expected = _synthetic(tmp_path, 15000, 3000)
    project = open_project(repo, tmp_path / "proj")
    start = time.perf_counter()
    result = scan(project, ScanOptions())
    first = time.perf_counter() - start
    _check_synthetic(result.db_path, expected)
    for f in sorted(repo.rglob("*.f90"))[:50]:
        f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    start = time.perf_counter()
    second = scan(project, ScanOptions())
    rescan = time.perf_counter() - start
    print(f"\nsynthetic 15000 routines / 3000 files: full scan {first:.1f} s, "
          f"{result.stats['call_sites']} sites; rescan after 50 changes {rescan:.1f} s "
          f"({second.stats['files_extracted']} extracted); cores={os.cpu_count()}")
    assert second.stats["files_extracted"] == 50
    assert first < 15 * 60 and rescan < 30
