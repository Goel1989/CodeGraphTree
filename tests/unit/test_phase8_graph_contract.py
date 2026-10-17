"""Phase 8 of the requirements plan: renderer-neutral graph contract behind the 3D views.

Nodes carry identifiers, labels, kinds, languages, groups and scope; links carry type, count and resolution status;
every link leads to the same dependency rows as the table; entity, file and directory levels exist; a library without
``main`` is fully navigable.
"""

from __future__ import annotations

from pathlib import Path

from tests.helpers import scan_fixture

from codegraph_sci.query.api import GraphQuery


def test_nodes_and_links_carry_the_contract(tmp_path: Path) -> None:
    db = scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json").db_path
    with GraphQuery(db) as q:
        graph = q.graph3d("py:app.run.run_case", mode="both", depth=3)
        assert graph.level == "entity" and graph.layout["version"] == 1 and graph.layout["dimensions"] == 3
        for node in graph.nodes:
            assert node.id and node.label and node.kind
            if node.file:
                assert node.group == (node.file.rsplit("/", 1)[0] if "/" in node.file else ".")
        assert {lk.status for lk in graph.links} <= {"resolved", "ambiguous", "external", "out_of_scope"}
        for link in graph.links:
            if link.kind in ("defines",):
                continue
            rows = q.dependencies(q.link_evidence(link.source, link.target), limit=100)
            assert rows.total >= 1, link  # the table and the graph open the same evidence
        files = q.graph3d_overview(mode="files")
        assert files.level == "file"
        for link in files.links:
            assert q.dependencies(q.link_evidence(link.source, link.target), limit=100).total >= 1, link


def test_link_statuses(tmp_path: Path) -> None:
    db = scan_fixture("partial_scope", tmp_path / "scope").db_path
    with GraphQuery(db) as q:
        graph = q.graph3d_overview(mode="functions", max_nodes=1000)
        statuses = {lk.status for lk in graph.links}
        assert "out_of_scope" in statuses
        assert any(not n.in_scope for n in graph.nodes)
    db = scan_fixture("cpp_overloads", tmp_path / "amb").db_path
    with GraphQuery(db) as q:
        graph = q.graph3d_overview(mode="functions", max_nodes=1000)
        assert "ambiguous" in {lk.status for lk in graph.links}


def test_directory_level(tmp_path: Path) -> None:
    db = scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json").db_path
    with GraphQuery(db) as q:
        graph = q.graph3d_directories()
        assert graph.level == "directory" and graph.mode == "directories"
        assert {n.id for n in graph.nodes} == {"dir:app", "dir:csrc", "dir:ext", "dir:fsrc"}
        assert all(n.kind == "directory" and n.size >= 1 for n in graph.nodes)
        assert ("dir:app", "dir:ext") in {(lk.source, lk.target) for lk in graph.links}
        for link in graph.links:
            assert q.dependencies(q.link_evidence(link.source, link.target), limit=100).total >= 1, link
        assert q.graph3d_directories(max_nodes=2).truncated


def test_library_without_main_is_navigable(tmp_path: Path) -> None:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "lib"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "core.py").write_text("def a():\n    b()\n\n\ndef b():\n    a()\n\n\ndef c():\n    b()\n",
                                          encoding="utf-8")
    db = scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1)).db_path
    with GraphQuery(db) as q:
        assert q.default_roots().main_routine is None or q.default_roots().main_routine.uid != "py:pkg.core.main"
        graph = q.graph3d_overview(mode="functions")
        assert {"py:pkg.core.a", "py:pkg.core.b", "py:pkg.core.c"} <= {n.id for n in graph.nodes}
        assert q.graph3d("py:pkg.core.b", depth=1).nodes
