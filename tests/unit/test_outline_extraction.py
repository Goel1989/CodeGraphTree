"""FULL and OUTLINE extraction (corrective audit P1 §3): out-of-scope files are only indexed for their definitions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.helpers import FIXTURES

from codegraph_sci.core.facts import FileFacts, decode_facts

A = "subroutine a()\n  call b(1)\nend subroutine a\n"
B = """subroutine b(k)
  integer :: k
  call c()
  select case (k)
  case (1)
    call c()
  end select
end subroutine b
"""
C = "subroutine c()\nend subroutine c\n"


def _facts(db: Path) -> dict[str, FileFacts]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT f.path, c.facts FROM files f JOIN facts_cache c ON c.cache_key = f.cache_key")
        return {path: decode_facts(blob) for path, blob in rows}
    finally:
        con.close()


def _scan(repo: Path, proj: Path, scope: list[str] | None = None) -> dict[str, object]:
    from codegraph_sci.core.profile import Scope
    from codegraph_sci.core.project import open_project
    from codegraph_sci.inventory.profile_io import load_profile, profile_from_inventory, save_profile
    from codegraph_sci.inventory.run import run_inventory
    from codegraph_sci.scan import ScanOptions, scan

    project = open_project(repo, proj)
    profile = load_profile(project.profile_path) if project.profile_path.is_file() else profile_from_inventory(
        run_inventory(repo))
    if scope is not None:
        profile.scope = Scope(include=scope, exclude=[])
        proj.mkdir(parents=True, exist_ok=True)
        save_profile(project.profile_path, profile)
    return scan(project, ScanOptions()).stats


def test_full_and_outline_files(tmp_path: Path) -> None:
    from codegraph_sci.query.api import GraphQuery

    repo, proj = tmp_path / "repo", tmp_path / "proj"
    for rel, text in {"scope/a.f90": A, "external/b.f90": B, "external/c.f90": C}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _scan(repo, proj, ["scope/"])
    facts = _facts(proj / "project.sqlite")
    assert facts["scope/a.f90"].extraction_mode == "full" and facts["scope/a.f90"].references  # 1
    b = facts["external/b.f90"]
    assert b.extraction_mode == "outline"  # 2
    assert b.references == [] and b.data_accesses == [] and b.directives == []  # 4: no detailed extraction
    assert [d.name for d in b.definitions] == ["b"]
    assert b.definitions[0].attrs.get("select_cases") == {"k": ["1"]}  # kept: packs dispatch on it
    with GraphQuery(proj / "project.sqlite") as q:
        assert [i.node.uid for i in q.callees("f:a", hide_noise=False).items] == ["f:b"]  # 3
        assert q.callees("f:b", hide_noise=False).items == []

    again = _scan(repo, proj)  # 5: the next scan reuses both kinds of facts
    assert again["files_extracted"] == 0 and again["files_cached"] == 3

    moved = _scan(repo, proj, ["scope/", "external/"])  # 6: b in scope -> FULL extraction, never the outline
    assert moved["files_extracted"] == 2  # b.f90 and c.f90 change mode
    facts = _facts(proj / "project.sqlite")
    assert facts["external/b.f90"].extraction_mode == "full" and facts["external/b.f90"].references
    with GraphQuery(proj / "project.sqlite") as q:
        assert [i.node.uid for i in q.callees("f:b", hide_noise=False).items] == ["f:c"]


@pytest.mark.parametrize("name", ["fortran_basic", "fortran_advanced", "fortran_traps", "fortran_preproc",
                                  "fortran_data", "fortran_ambiguity"])
def test_outline_keeps_exactly_the_definitions(name: str) -> None:
    """Skipping executable statements must not change any definition (attributes, local symbols)."""
    from codegraph_sci.core.plugins import ExtractContext, decode_bytes
    from codegraph_sci.extract.fortran.parser import extract_fortran
    from codegraph_sci.inventory.run import run_inventory

    root = FIXTURES / name / "src"
    inventory = run_inventory(root)
    for entry in inventory.source_files():
        if entry.lang != "fortran":
            continue
        text, enc = decode_bytes((root / entry.path).read_bytes())
        full = extract_fortran(entry.path, text, enc, entry.variant, ExtractContext())
        outline = extract_fortran(entry.path, text, enc, entry.variant, ExtractContext(outline=True))
        assert outline.definitions == full.definitions, entry.path
        assert outline.includes == full.includes, entry.path
