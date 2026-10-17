"""Groups of the 3D view: separate programs, isolated nodes, links between folders, non-code files."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph_sci.query.api import GraphQuery, QueryError
from codegraph_sci.query.types import Level

SOURCES = {
    # Program A: three routines in one folder.
    "progA/main_a.f90": "program main_a\n  call a1()\nend program main_a\n",
    "progA/a1.f90": "subroutine a1()\n  call a2()\nend subroutine a1\n",
    "progA/a2.f90": "subroutine a2()\nend subroutine a2\n",
    # Program B: crosses from progB/ to lib/.
    "progB/main_b.f90": "program main_b\n  call b1()\nend program main_b\n",
    "progB/b1.f90": "subroutine b1()\n  call b2()\nend subroutine b1\n",
    "lib/b2.f90": "subroutine b2()\nend subroutine b2\n",
    # Linked to nothing.
    "lonely/alone.f90": "subroutine alone()\nend subroutine alone\n",
    # Not code.
    "docs/readme.md": "# Notes\n",
    "data/mesh.csv": "x,y\n1,2\n",
    "notes.xyz": "free text\n",
}


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    base = tmp_path_factory.mktemp("groups")
    repo = base / "repo"
    for rel, text in SOURCES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (repo / "img").mkdir()
    (repo / "img" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    try:
        assert main(["scan", str(repo), "--project", str(base / "proj")]) == 0
    finally:
        netguard.uninstall()
    return base / "proj" / "project.sqlite"


def _uid(q: GraphQuery, name: str) -> str:
    return q.resolve(name)[0].uid


def test_function_groups_and_isolated(db: Path) -> None:
    with GraphQuery(db) as q:
        report = q.groups(Level.ROUTINE)
        a, b, alone = _uid(q, "a1"), _uid(q, "b1"), _uid(q, "alone")
    assert [g.size for g in report.groups] == [3, 3]
    members = [set(g.members) for g in report.groups]
    assert any(a in m for m in members) and any(b in m for m in members)
    assert report.isolated == [alone]
    group_b = next(g for g in report.groups if b in g.members)
    assert dict(group_b.top_dirs) == {"progB": 2, "lib": 1} and group_b.langs == {"fortran": 3}


def test_file_groups(db: Path) -> None:
    with GraphQuery(db) as q:
        report = q.groups(Level.FILE)
    assert sorted(sorted(g.members) for g in report.groups) == [
        ["file:lib/b2.f90", "file:progB/b1.f90", "file:progB/main_b.f90"],
        ["file:progA/a1.f90", "file:progA/a2.f90", "file:progA/main_a.f90"],
    ]
    assert report.isolated == ["file:lonely/alone.f90"]


def test_overview_shows_everything_when_it_fits(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = q.graph3d_overview(mode="functions", max_nodes=300)
        ids = {n.id for n in graph.nodes}
        assert {_uid(q, n) for n in ("main_a", "a1", "a2", "main_b", "b1", "b2", "alone")} == ids
        assert (_uid(q, "b1"), _uid(q, "b2")) in {(lk.source, lk.target) for lk in graph.links}
    assert not graph.truncated


def test_overview_draws_one_sphere_per_group_when_too_big(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = q.graph3d_overview(mode="functions", max_nodes=4)
        assert graph.links == []
        kinds = sorted(n.kind for n in graph.nodes)
        assert kinds == ["group", "group", "isolated"]
        spheres = [n for n in graph.nodes if n.kind == "group"]
        assert all(n.size == 3 and n.id.startswith("group:") for n in spheres)
        isolated = next(n for n in graph.nodes if n.kind == "isolated")
        assert isolated.size == 1 and isolated.id == "isolated:functions"
        more = q.graph3d_overview(mode="functions", max_nodes=2)  # 1 sphere, "more" and "isolated" buckets
        assert sorted(n.kind for n in more.nodes) == ["group", "isolated", "more"]


def test_group_detail_and_links_between_folders(db: Path) -> None:
    with GraphQuery(db) as q:
        b1, b2, main_b = _uid(q, "b1"), _uid(q, "b2"), _uid(q, "main_b")
        group = q.graph3d_group(f"group:{b1}", mode="functions", max_nodes=300)
        alone = q.graph3d_group("isolated:functions", mode="functions", max_nodes=300)
        with pytest.raises(QueryError):
            q.graph3d_group("nonsense", mode="functions")
    assert {n.id for n in group.nodes} == {b1, b2, main_b}
    crossing = {(lk.source, lk.target): lk.cross_dir for lk in group.links}
    assert crossing == {(main_b, b1): False, (b1, b2): True}
    assert [n.label for n in alone.nodes] == ["alone"] and alone.links == []


def test_non_code_files_are_kept_apart(db: Path) -> None:
    with GraphQuery(db) as q:
        report = q.non_code_files()
        files = q.graph3d_overview(mode="files", max_nodes=300)
    assert report.counts == {"data": 1, "docs": 1, "images": 1, "unknown type": 1}
    assert ("data/mesh.csv", "data") in [(f.path, f.category) for f in report.files]
    non_code = {n.id for n in files.nodes if n.kind == "noncode"}
    assert non_code == {"noncode:data/mesh.csv", "noncode:docs/readme.md", "noncode:img/plot.png",
                        "noncode:notes.xyz"}
    assert not any(lk.source in non_code or lk.target in non_code for lk in files.links)
    assert "file:lonely/alone.f90" in {n.id for n in files.nodes}
