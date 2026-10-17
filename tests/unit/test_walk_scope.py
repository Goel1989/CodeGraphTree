"""Which sub-folders the inventory walks, which it skips (and says why), and the "all subfolders" option."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph_sci.core.profile import AnalysisProfile
from codegraph_sci.inventory.run import run_inventory
from codegraph_sci.inventory.table import load_table
from codegraph_sci.inventory.walk import SkippedDir, walk_repo


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    files = {
        "src/a.f90": "subroutine a\nend subroutine a\n",
        "src/deep/er/b.f90": "subroutine b\nend subroutine b\n",
        "build/gen/gen.f90": "subroutine gen\nend subroutine gen\n",
        ".venv/lib/site.py": "def site():\n    pass\n",
        "vendor/old.c": "int old(void) { return 0; }\n",
        "vendor/keep.c": "int keep(void) { return 1; }\n",
        ".git/config": "[core]\n",
        ".gitignore": "vendor/\nscratch.f90\n",
        "scratch.f90": "subroutine scratch\nend subroutine scratch\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _walk(root: Path, **kw: object) -> tuple[list[str], list[SkippedDir]]:
    skipped: list[SkippedDir] = []
    rels = [w.rel for w in walk_repo(root, load_table().excluded_dirs, skipped=skipped, **kw)]  # type: ignore[arg-type]
    return rels, skipped


def test_default_walk_goes_into_every_subfolder_and_reports_skipped_ones(tree: Path) -> None:
    rels, skipped = _walk(tree)
    assert rels == [".gitignore", "src/a.f90", "src/deep/er/b.f90"]
    assert [(s.path, s.reason, s.files) for s in skipped] == [
        (".venv", "default exclusion", 1),
        ("build", "default exclusion", 1),
        ("scratch.f90", ".gitignore", 1),
        ("vendor", ".gitignore", 2),
    ]


def test_all_subfolders_ignores_gitignore_and_default_exclusions_but_not_vcs_metadata(tree: Path) -> None:
    rels, skipped = _walk(tree, all_subfolders=True)
    assert rels == [".gitignore", ".venv/lib/site.py", "build/gen/gen.f90", "scratch.f90", "src/a.f90",
                    "src/deep/er/b.f90", "vendor/keep.c", "vendor/old.c"]
    assert skipped == []


def test_profile_exclusions_still_apply_with_all_subfolders(tree: Path) -> None:
    rels, skipped = _walk(tree, extra_excluded=["src/deep"], all_subfolders=True)
    assert "src/deep/er/b.f90" not in rels and "src/a.f90" in rels
    assert [(s.path, s.reason) for s in skipped] == [("src/deep", "profile")]


def test_inventory_reports_skipped_dirs_and_follows_the_profile(tree: Path) -> None:
    from codegraph_sci.inventory.report import inventory_dict, inventory_table

    default = run_inventory(tree)
    assert {e.path for e in default.source_files()} == {"src/a.f90", "src/deep/er/b.f90"}
    listed = inventory_dict(default)["skipped_dirs"]
    assert listed[0] == {"path": "vendor", "reason": ".gitignore", "files": 2}  # largest first
    assert {"path": ".venv", "reason": "default exclusion", "files": 1} in listed
    assert "Skipped: .venv (default exclusion, 1 file)" in inventory_table(default)
    everything = run_inventory(tree, AnalysisProfile(all_subfolders=True))
    assert {"build/gen/gen.f90", "vendor/old.c", "scratch.f90", ".venv/lib/site.py"} <= {
        e.path for e in everything.source_files()}
    assert everything.skipped_dirs == []


def test_profile_option_round_trip_and_unchanged_hash_when_off() -> None:
    from codegraph_sci.inventory.profile_io import profile_sha256, profile_text

    off = AnalysisProfile()
    assert "all_subfolders" not in profile_text(off)  # existing profiles keep their hash
    on = AnalysisProfile(all_subfolders=True)
    assert AnalysisProfile.from_dict(on.to_dict()).all_subfolders is True
    assert profile_sha256(on) != profile_sha256(off)


def test_cli_profile_all_subfolders_then_scan_stats(tree: Path, tmp_path: Path) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard
    from codegraph_sci.query.api import GraphQuery

    proj = tmp_path / "proj"
    try:
        assert main(["scan", str(tree), "--project", str(proj)]) == 0
        with GraphQuery(proj / "project.sqlite") as q:
            stats = q.scan_health().last_scan["stats"]  # type: ignore[index]
        assert stats["all_subfolders"] is False
        assert {d["path"] for d in stats["skipped_dirs"]} == {".venv", "build", "scratch.f90", "vendor"}
        assert main(["profile", "all-subfolders", str(tree), "on", "--project", str(proj)]) == 0
        assert main(["scan", str(tree), "--project", str(proj)]) == 0
        with GraphQuery(proj / "project.sqlite") as q:
            stats = q.scan_health().last_scan["stats"]  # type: ignore[index]
            assert q.resolve("gen") and q.resolve("old")
        assert stats["all_subfolders"] is True and stats["skipped_dirs"] == []
        assert main(["profile", "all-subfolders", str(tree), "off", "--project", str(proj)]) == 0
        with pytest.raises(SystemExit):
            main(["profile", "all-subfolders", str(tree), "maybe", "--project", str(proj)])
    finally:
        netguard.uninstall()
