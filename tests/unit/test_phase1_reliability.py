"""Phase 1 acceptance: cache context, reproducibility, identity and cancellation."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from codegraph_sci.core.project import open_project
from codegraph_sci.inventory.profile_io import load_profile, save_profile
from codegraph_sci.scan import ScanCancelled, ScanOptions, scan
from codegraph_sci.store.export import export_dict, export_json


def _project(tmp_path: Path, files: dict[str, str]):
    root = tmp_path / "repo"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return open_project(root, tmp_path / "project")


def test_identical_files_cold_cached_parallel(tmp_path: Path) -> None:
    project = _project(tmp_path, dict.fromkeys(["a.py", "b.py"], "def hello():\n    hello()\n"))
    scan(project, ScanOptions(jobs=1))
    cold = export_json(project.db_path)
    assert scan(project, ScanOptions(jobs=2)).stats["files_cached"] == 2
    assert export_json(project.db_path) == cold
    scan(project, ScanOptions(jobs=2, full=True))
    assert export_json(project.db_path) == cold


def test_package_marker_changes_naming_context(tmp_path: Path) -> None:
    project = _project(tmp_path, {"src/pkg/m.py": "def hello(): pass\n"})
    scan(project, ScanOptions(jobs=1))
    (project.root / "src/pkg/__init__.py").write_text("", encoding="utf-8")
    result = scan(project, ScanOptions(jobs=1))
    assert result.stats["files_extracted"] == 2
    assert "py:pkg.m.hello" in {n["uid"] for n in export_dict(project.db_path)["nodes"]}


@pytest.mark.parametrize("change", ["precedence", "shadow", "missing", "nested"])
def test_include_resolution_changes_invalidate_cache(tmp_path: Path, change: str) -> None:
    project = _project(tmp_path, {"main.c": '#include "defs.h"\nvoid run(void) { DO(); }\n',
                                  "a/defs.h": "#define DO() first()\n",
                                  "b/defs.h": "#define DO() second()\n"})
    scan(project, ScanOptions(jobs=1))
    profile = load_profile(project.profile_path)
    profile.include_paths = ["a", "b"]
    if change == "missing":
        (project.root / "a/defs.h").unlink()
        (project.root / "b/defs.h").unlink()
    if change == "nested":
        (project.root / "a/defs.h").write_text('#include "nested.h"\n', encoding="utf-8")
    save_profile(project.profile_path, profile)
    scan(project, ScanOptions(jobs=1, full=True))
    if change == "precedence":
        profile.include_paths.reverse()
        save_profile(project.profile_path, profile)
        assert load_profile(project.profile_path).include_paths == ["b", "a"]
    elif change == "nested":
        (project.root / "a/nested.h").write_text("#define DO() second()\n", encoding="utf-8")
    else:
        (project.root / "defs.h").write_text("#define DO() second()\n", encoding="utf-8")
    scan(project, ScanOptions(jobs=1))
    warm = export_json(project.db_path)
    scan(project, ScanOptions(jobs=1, full=True))
    assert export_json(project.db_path) == warm


def test_link_settings_do_not_invalidate_extraction(tmp_path: Path) -> None:
    project = _project(tmp_path, {"a.py": "def hello(): pass\n"})
    scan(project, ScanOptions(jobs=1))
    assert scan(project, ScanOptions(jobs=1, native_bridges=False)).stats["files_cached"] == 1


def test_bridge_partition_is_stable_across_hash_seeds() -> None:
    script = ("from codegraph_sci.ai.complete import _sample_half; "
              "print([_sample_half(f'file{i}.py') for i in range(30)])")
    results = [subprocess.check_output([sys.executable, "-c", script],
               env={**os.environ, "PYTHONHASHSEED": str(seed)}, text=True) for seed in (1, 2)]
    assert results[0] == results[1]


def test_inventory_variant_invalidates_extraction(tmp_path: Path) -> None:
    from codegraph_sci.core.profile import FileOverride

    project = _project(tmp_path, {"a.f": "      subroutine hello\n      end\n"})
    scan(project, ScanOptions(jobs=1))
    profile = load_profile(project.profile_path)
    profile.file_overrides = [FileOverride("a.f", "fortran", variant="free")]
    save_profile(project.profile_path, profile)
    assert scan(project, ScanOptions(jobs=1)).stats["files_extracted"] == 1


def test_incompatible_and_damaged_facts_are_cache_misses() -> None:
    import json
    import zlib

    from codegraph_sci.core.facts import FileFacts
    from codegraph_sci.store.cache import get_facts

    old = FileFacts("a.py", "python", "utf-8", "python", "1").to_dict()
    old["format_version"] = 1
    assert get_facts({"old": zlib.compress(json.dumps(old).encode())}, "old") is None
    assert get_facts({"damaged": b"invalid"}, "damaged") is None


def _blocked(path: str, lang: str, variant: str | None, mode: str):
    time.sleep(3600)


@pytest.mark.parametrize("stage", ["extract", "write"])
@pytest.mark.parametrize("full", [False, True])
def test_cancellation_preserves_committed_database(tmp_path: Path, stage: str, full: bool) -> None:
    import multiprocessing

    project = _project(tmp_path, {"a.py": "def hello(): pass\n"})
    scan(project, ScanOptions(jobs=1))
    before = project.db_path.read_bytes()
    (project.root / "a.py").write_text("def changed(): pass\n", encoding="utf-8")
    started = None

    def progress(event):
        nonlocal started
        if event["event"] == stage:
            started = time.monotonic()

    def cancelled():
        return started is not None and (stage == "write" or time.monotonic() - started > 2)

    with pytest.raises(ScanCancelled):
        scan(project, ScanOptions(jobs=1, full=full, cancel=cancelled,
                                  extract_job=_blocked if stage == "extract" else None), progress)
    assert project.db_path.read_bytes() == before
    assert not multiprocessing.active_children()


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_scan_requires_finite_positive_deadline(tmp_path: Path, timeout: float) -> None:
    project = _project(tmp_path, {"a.py": "pass\n"})
    with pytest.raises(ValueError, match="timeout"):
        scan(project, ScanOptions(timeout_s=timeout))


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "abc"])
def test_cli_rejects_a_deadline_that_is_not_finite_and_positive(
        tmp_path: Path, value: str, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    project = _project(tmp_path, {"a.py": "pass\n"})
    try:
        with pytest.raises(SystemExit) as exc:
            main(["scan", str(project.root), "--project", str(project.folder), "--timeout", value])
    finally:
        netguard.uninstall()
    assert exc.value.code == 2  # argparse usage error, no traceback
    assert "finite number of seconds greater than zero" in capsys.readouterr().err
