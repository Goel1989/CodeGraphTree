"""Phase 2 of the requirements plan: a persistent inventory that accounts for every discovered entry.

Discovery is separate from analysis selection: every directory, file, link, exclusion and discovery problem is
recorded with the reason why it was (or was not) analyzed.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from codegraph_sci.core.profile import AnalysisProfile
from codegraph_sci.inventory.run import run_inventory

FILES: dict[str, bytes] = {
    "src/a.f90": b"subroutine a\n  call b()\nend subroutine a\n",
    "src/b.py": b"def b():\n    pass\n",
    "src/notes.md": b"# notes\n",
    "src/data.bin": b"\x00\x01\x02binary",
    "src/odd.xyz": b"something\n",
    "src/k.pyx": b"def k():\n    pass\n",
    "README": b"read me\n",
    "build/gen.f90": b"subroutine gen\nend subroutine gen\n",
    "vendor/old.c": b"int old(void) { return 0; }\n",
    "scratch.f90": b"subroutine scratch\nend subroutine scratch\n",
    ".gitignore": b"vendor/\nscratch.f90\n",
    ".git/config": b"[core]\n",
}

# path -> (kind, eligibility, status, reason) with the default "analysis" policy.
EXPECTED_ANALYSIS: dict[str, tuple[str, str, str, str | None]] = {
    ".": ("directory", "not_applicable", "walked", None),
    ".git": ("directory", "excluded", "not_walked", "version-control metadata"),
    ".gitignore": ("file", "not_source", "not_analyzed", "ignored extension"),
    "README": ("file", "not_source", "not_analyzed", "ignored file name"),
    "build": ("directory", "excluded", "not_walked", "default exclusion"),
    "empty": ("directory", "not_applicable", "walked", None),
    "scratch.f90": ("file", "excluded", "not_analyzed", ".gitignore"),
    "src": ("directory", "not_applicable", "walked", None),
    "src/a.f90": ("file", "eligible", "pending", None),
    "src/b.py": ("file", "eligible", "pending", None),
    "src/data.bin": ("file", "not_source", "not_analyzed", "binary content"),
    "src/k.pyx": ("file", "unsupported_language", "not_analyzed", "language not covered"),
    "src/notes.md": ("file", "not_source", "not_analyzed", "ignored extension"),
    "src/odd.xyz": ("file", "not_source", "not_analyzed", "unknown language"),
    "vendor": ("directory", "excluded", "not_walked", ".gitignore"),
}


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel, data in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "empty").mkdir()
    return root


def _summary(items: list[Any]) -> dict[str, tuple[str, str, str, str | None]]:
    return {i.path: (i.kind, i.eligibility, i.status, i.reason) for i in items}


def _symlink(target: Path, link: Path, *, directory: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available on this system")


def test_every_discovered_entry_is_accounted_for(tree: Path) -> None:
    result = run_inventory(tree)
    assert result.policy == "analysis"
    assert _summary(result.items) == EXPECTED_ANALYSIS
    by_path = {i.path: i for i in result.items}
    root = by_path["."]
    assert root.parent is None and by_path["src"].parent == "." and by_path["src/a.f90"].parent == "src"
    a = by_path["src/a.f90"]
    assert (a.extension, a.size, a.lang, a.evidence) == (".f90", len(FILES["src/a.f90"]), "fortran", "extension:.f90")
    assert by_path["src/k.pyx"].lang == "cython"
    # Directories count the files below them, including those of folders that were not walked.
    assert (by_path["build"].files, by_path["vendor"].files, by_path["empty"].files) == (1, 1, 0)
    assert by_path["src"].files == 6 and root.files == 11
    assert by_path[".git"].files is None  # version-control metadata is never walked nor counted
    # An excluded file is never read: its language comes from the extension alone.
    scratch = by_path["scratch.f90"]
    assert (scratch.lang, scratch.evidence, scratch.size) == ("fortran", "extension:.f90", len(FILES["scratch.f90"]))
    # The analysis selection itself is unchanged.
    assert [e.path for e in result.source_files()] == ["src/a.f90", "src/b.py"]
    assert result.issues == []


def test_items_are_sorted_and_deterministic(tree: Path) -> None:
    first, second = run_inventory(tree), run_inventory(tree)
    assert [i.path for i in first.items] == sorted(i.path for i in first.items)
    assert first.items == second.items


def test_complete_policy_records_excluded_content_without_analyzing_it(tree: Path) -> None:
    analysis = run_inventory(tree)
    complete = run_inventory(tree, AnalysisProfile(inventory_policy="complete"))
    assert complete.policy == "complete"
    summary = _summary(complete.items)
    assert summary["build"] == ("directory", "excluded", "walked", "default exclusion")
    assert summary["vendor"] == ("directory", "excluded", "walked", ".gitignore")
    assert summary["build/gen.f90"] == ("file", "excluded", "not_analyzed", "default exclusion")
    assert summary["vendor/old.c"] == ("file", "excluded", "not_analyzed", ".gitignore")
    assert summary[".git"] == EXPECTED_ANALYSIS[".git"]  # still never walked
    old = next(i for i in complete.items if i.path == "vendor/old.c")
    assert (old.lang, old.evidence) == ("c", "extension:.c")
    # Same analysis selection, same skipped-folder report: only the record is more complete.
    assert [e.path for e in complete.source_files()] == [e.path for e in analysis.source_files()]
    assert complete.skipped_dirs == analysis.skipped_dirs
    assert {p: v for p, v in summary.items() if p not in ("build/gen.f90", "vendor/old.c", "build", "vendor")} == {
        p: v for p, v in EXPECTED_ANALYSIS.items() if p not in ("build", "vendor")}


def test_all_subfolders_makes_excluded_content_eligible(tree: Path) -> None:
    summary = _summary(run_inventory(tree, AnalysisProfile(all_subfolders=True)).items)
    assert summary["build/gen.f90"] == ("file", "eligible", "pending", None)
    assert summary["vendor/old.c"] == ("file", "eligible", "pending", None)
    assert summary["scratch.f90"] == ("file", "eligible", "pending", None)


def test_unreadable_directories_and_files_are_recorded(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import codegraph_sci.inventory.walk as walk

    (tree / "locked").mkdir()
    (tree / "locked" / "hidden.f90").write_text("subroutine h\nend subroutine h\n", encoding="utf-8")
    real_scandir, real_open = os.scandir, Path.open

    def scandir(path: Any) -> Any:
        if str(path).endswith("locked"):
            raise PermissionError("access denied")
        return real_scandir(path)

    def open_(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "b.py":
            raise PermissionError("access denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(walk.os, "scandir", scandir)
    monkeypatch.setattr(Path, "open", open_)
    result = run_inventory(tree)
    summary = _summary(result.items)
    assert summary["locked"] == ("directory", "unreadable", "not_walked", "unreadable")
    assert summary["src/b.py"] == ("file", "unreadable", "not_analyzed", "unreadable")
    assert "src/b.py" not in [e.path for e in result.source_files()]
    assert {(i.path, i.kind) for i in result.issues} == {("locked", "unreadable"), ("src/b.py", "unreadable")}


def test_symbolic_links(tree: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "ext.f90").write_text("subroutine ext\nend subroutine ext\n", encoding="utf-8")
    _symlink(tree / "src", tree / "src" / "again", directory=True)  # loop
    _symlink(outside, tree / "external", directory=True)  # outside the root: followed, flagged
    _symlink(tree / "missing.f90", tree / "broken.f90", directory=False)
    _symlink(tree / "src" / "a.f90", tree / "alias.f90", directory=False)
    result = run_inventory(tree)
    by_path = {i.path: i for i in result.items}
    assert _summary(result.items)["src/again"] == ("directory", "excluded", "not_walked", "symbolic link loop")
    assert by_path["src/again"].link_target is not None
    assert _summary(result.items)["broken.f90"] == ("symlink", "unreadable", "not_analyzed", "broken symbolic link")
    assert _summary(result.items)["external"] == ("directory", "not_applicable", "walked", None)
    assert by_path["external"].link_target is not None
    assert _summary(result.items)["external/ext.f90"] == ("file", "eligible", "pending", None)
    assert _summary(result.items)["alias.f90"] == ("file", "eligible", "pending", None)
    assert by_path["alias.f90"].link_target is not None
    kinds = {(i.path, i.kind) for i in result.issues}
    assert {("src/again", "loop"), ("external", "external_link"), ("broken.f90", "broken_link")} <= kinds


def test_profile_inventory_policy_round_trip_and_unchanged_hash(tmp_path: Path, tree: Path) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard
    from codegraph_sci.inventory.profile_io import load_profile, profile_sha256, profile_text

    default = AnalysisProfile()
    assert "inventory_policy" not in profile_text(default)  # existing profiles keep their hash
    complete = AnalysisProfile(inventory_policy="complete")
    assert AnalysisProfile.from_dict(complete.to_dict()).inventory_policy == "complete"
    assert profile_sha256(complete) != profile_sha256(default)
    proj = tmp_path / "proj"
    try:
        assert main(["profile", "inventory-policy", str(tree), "complete", "--project", str(proj)]) == 0
        assert load_profile(proj / "analysis_profile.yaml").inventory_policy == "complete"
        assert main(["profile", "inventory-policy", str(tree), "analysis", "--project", str(proj)]) == 0
        assert load_profile(proj / "analysis_profile.yaml").inventory_policy == "analysis"
        with pytest.raises(SystemExit):
            main(["profile", "inventory-policy", str(tree), "everything", "--project", str(proj)])
    finally:
        netguard.uninstall()


def test_cli_inventory_json_accounts_for_entries(tree: Path, tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    try:
        assert main(["inventory", str(tree), "--project", str(tmp_path / "proj"), "--json", "--entries"]) == 0
    finally:
        netguard.uninstall()
    data = json.loads(capsys.readouterr().out)
    assert data["policy"] == "analysis"
    assert data["accounting"]["by_eligibility"] == {"eligible": 2, "excluded": 4, "not_applicable": 3,
                                                    "not_source": 5, "unsupported_language": 1}
    assert {e["path"] for e in data["entries"]} == set(EXPECTED_ANALYSIS)


def _scan(tree: Path, proj: Path, profile: AnalysisProfile | None = None) -> dict[str, Any]:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.inventory.profile_io import profile_from_inventory, save_profile
    from codegraph_sci.scan import ScanOptions, scan

    project = open_project(tree, proj)
    if profile is not None:
        project.folder.mkdir(parents=True, exist_ok=True)
        save_profile(project.profile_path, profile_from_inventory(run_inventory(tree, profile), profile))
    return scan(project, ScanOptions(jobs=1)).stats


def test_scan_persists_the_inventory_and_queries_it(tree: Path, tmp_path: Path) -> None:
    from codegraph_sci.query.api import GraphQuery
    from codegraph_sci.store.export import export_dict

    proj = tmp_path / "proj"
    stats = _scan(tree, proj)
    assert stats["inventory_policy"] == "analysis"
    assert stats["inventory_entries"] == len(EXPECTED_ANALYSIS)
    db = proj / "project.sqlite"
    with GraphQuery(db) as q:
        entries = q.inventory_entries()
        summary = _summary(entries)
        assert set(summary) == set(EXPECTED_ANALYSIS)
        assert summary["src/a.f90"] == ("file", "eligible", "ok", None)
        assert summary["src/b.py"] == ("file", "eligible", "ok", None)
        assert {p: v for p, v in summary.items() if p not in ("src/a.f90", "src/b.py")} == {
            p: v for p, v in EXPECTED_ANALYSIS.items() if p not in ("src/a.f90", "src/b.py")}
        assert [e.path for e in q.inventory_entries(parent="src")] == [
            "src/a.f90", "src/b.py", "src/data.bin", "src/k.pyx", "src/notes.md", "src/odd.xyz"]
        assert [e.path for e in q.inventory_entries(eligibility="excluded")] == [".git", "build", "scratch.f90",
                                                                                "vendor"]
        assert [e.path for e in q.inventory_entries(kind="directory", limit=2, offset=1)] == [".git", "build"]
        accounting = q.inventory_accounting()
        assert accounting.policy == "analysis" and accounting.total == len(EXPECTED_ANALYSIS)
        assert accounting.by_kind == {"directory": 6, "file": 9}
        assert accounting.by_status["ok"] == 2
        assert accounting.by_reason[".gitignore"] == 2
        assert q.inventory_issues() == []
        assert q.inventory().unknown_groups == {".xyz": 1}
    export = export_dict(db)
    assert [e["path"] for e in export["inventory_entries"]] == sorted(EXPECTED_ANALYSIS)
    assert export["inventory_issues"] == []


def test_scan_statuses_outline_and_complete_policy(tree: Path, tmp_path: Path) -> None:
    from codegraph_sci.core.profile import Scope
    from codegraph_sci.query.api import GraphQuery

    profile = AnalysisProfile(inventory_policy="complete", scope=Scope(include=["src/a.f90"]))
    _scan(tree, tmp_path / "proj", profile)
    with GraphQuery(tmp_path / "proj" / "project.sqlite") as q:
        summary = _summary(q.inventory_entries())
        assert q.inventory_accounting().policy == "complete"
    assert summary["src/a.f90"] == ("file", "eligible", "ok", None)
    assert summary["src/b.py"] == ("file", "eligible", "outline", "outside the analysis scope")
    assert summary["vendor/old.c"] == ("file", "excluded", "not_analyzed", ".gitignore")


def test_database_of_the_previous_schema_is_rebuilt_and_keeps_its_cache(tree: Path, tmp_path: Path) -> None:
    from codegraph_sci.core.versions import DB_SCHEMA_VERSION
    from codegraph_sci.query.api import GraphQuery

    proj = tmp_path / "proj"
    _scan(tree, proj)
    db = proj / "project.sqlite"
    con = sqlite3.connect(db)
    con.execute("DROP TABLE inventory_entries")
    con.execute("DROP TABLE inventory_issues")
    con.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION - 1}")
    con.commit()
    con.close()
    stats = _scan(tree, proj)
    assert stats["files_cached"] == 2  # extraction reused from the old database
    with GraphQuery(db) as q:
        assert q.inventory_accounting().total == len(EXPECTED_ANALYSIS)
