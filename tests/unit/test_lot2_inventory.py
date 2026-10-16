from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from codegraph_sci.core.profile import AnalysisProfile, FileOverride
from codegraph_sci.inventory.gitignore import GitIgnore
from codegraph_sci.inventory.profile_io import (
    ConfigError,
    load_profile,
    profile_from_inventory,
    profile_text,
    save_profile,
)
from codegraph_sci.inventory.run import run_inventory

FIXTURE = Path(__file__).parents[1] / "fixtures" / "inventory_mixed"


@pytest.fixture()
def mixed_repo(tmp_path: Path) -> tuple[Path, bool]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE / "src", repo)
    (repo / "data" / "blob.bin").write_bytes(b"\x7fELF\x00\x01\x02\x00binary")
    has_link = True
    try:
        os.symlink(repo, repo / "loop", target_is_directory=True)
    except OSError:
        has_link = False
    return repo, has_link


def test_inventory_mixed_matches_expected(mixed_repo: tuple[Path, bool]) -> None:
    repo, has_link = mixed_repo
    expected = json.loads((FIXTURE / "expected_inventory.json").read_text(encoding="utf-8"))
    result = run_inventory(repo)
    got = {e.path: {"lang": e.lang, "variant": e.variant, "status": e.status} for e in result.entries}
    assert got == expected["files"]
    assert result.include_paths == expected["include_paths"]
    assert {k: len(v) for k, v in result.unknown_groups.items()} == expected["unknown_groups"]
    assert result.coverage["fortran"].adapter == "native:fortran"
    assert result.coverage["cuda"].adapter == "none"
    assert result.entry("scripts/runjob").decided_by.startswith("shebang")  # type: ignore[union-attr]
    if has_link:
        assert any("loop" in p.message for p in result.problems)


def test_inventory_is_deterministic(mixed_repo: tuple[Path, bool], tmp_path: Path) -> None:
    repo, _ = mixed_repo
    p1 = profile_from_inventory(run_inventory(repo))
    p2 = profile_from_inventory(run_inventory(repo))
    assert profile_text(p1) == profile_text(p2)
    path = tmp_path / "analysis_profile.yaml"
    save_profile(path, p1)
    again = profile_from_inventory(run_inventory(repo, load_profile(path)), load_profile(path))
    assert again.profile_version == p1.profile_version
    assert profile_text(again) == profile_text(p1)


def test_override_forces_language(mixed_repo: tuple[Path, bool]) -> None:
    repo, _ = mixed_repo
    profile = AnalysisProfile(file_overrides=[FileOverride("cpp/engine.h", "c", "test")])
    result = run_inventory(repo, profile)
    entry = result.entry("cpp/engine.h")
    assert entry is not None and entry.lang == "c" and entry.decided_by == "override:cpp/engine.h"


def test_profile_strict_loading(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("profile_version: 1\nunknown_key: 3\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown_key"):
        load_profile(bad)
    bad.write_text("profile_version: one\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="profile_version"):
        load_profile(bad)
    bad.write_text("profile_version: !!python/object/apply:os.system ['echo hacked']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_profile(bad)


def test_gitignore() -> None:
    gi = GitIgnore()
    gi.add_file("", "*.o\nbuild/\n/top.txt\n!keep.o\ndocs/**/gen\n")
    gi.add_file("sub", "local.f90\n")
    assert gi.ignored("a/b.o", False)
    assert not gi.ignored("a/keep.o", False)
    assert gi.ignored("x/build", True)
    assert gi.ignored("x/build/y.c", False)
    assert gi.ignored("top.txt", False) and not gi.ignored("a/top.txt", False)
    assert gi.ignored("docs/a/b/gen", True)
    assert gi.ignored("sub/local.f90", False) and not gi.ignored("local.f90", False)


def test_inventory_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / "skip").mkdir()
    (tmp_path / "skip" / "a.f90").write_text("subroutine a\nend\n", encoding="utf-8")
    (tmp_path / "b.f90").write_text("subroutine b\nend\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("skip/\n", encoding="utf-8")
    result = run_inventory(tmp_path)
    assert [e.path for e in result.entries if e.status == "source"] == ["b.f90"]


def test_cli_inventory(mixed_repo: tuple[Path, bool], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    repo, _ = mixed_repo
    project = tmp_path / "proj"
    try:
        assert main(["inventory", str(repo), "--project", str(project)]) == 0
    finally:
        netguard.uninstall()
    out = capsys.readouterr().out
    assert "fortran" in out and "Unknown files by extension: .xyz (2)" in out
    profile = load_profile(project / "analysis_profile.yaml")
    assert profile.languages["fortran"].files == 4
    assert profile.include_paths == ["c", "cpp", "include"]


@pytest.mark.slow
def test_inventory_15000_files_under_one_minute(tmp_path: Path) -> None:
    for d in range(150):
        folder = tmp_path / f"d{d:03d}"
        folder.mkdir()
        for i in range(100):
            ext = (".f90", ".py", ".cpp", ".c", ".h")[i % 5]
            body = "subroutine s\n  call t()\nend subroutine s\n" * 20 if ext == ".f90" else "int f();\n" * 40
            (folder / f"f{i:03d}{ext}").write_text(body, encoding="utf-8")
    start = time.perf_counter()
    result = run_inventory(tmp_path)
    elapsed = time.perf_counter() - start
    print(f"\ninventory of 15000 files: {elapsed:.1f} s")
    assert len(result.entries) == 15000
    assert elapsed < 60
