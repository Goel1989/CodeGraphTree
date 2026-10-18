"""Folders 3D: the folder tree (every level) under a selected folder, drawn as spheres linked to their parent.

Dependencies between folders are an optional layer, off when the view opens. Excluded folders are shown greyed;
version-control metadata is never shown.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph_sci.query.api import GraphQuery, QueryError

FILES = {
    "src/a/x.c": "void x(void) { y(); }\n",
    "src/b/y.c": "void y(void) {}\n",
    "src/b/c/z.py": "def z():\n    pass\n",
    "src/only/deeper/w.py": "def w():\n    pass\n",
    "docs/readme.md": "# readme\n",
    "build/gen.c": "void gen(void) {}\n",
    ".git/config": "[core]\n",
}


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    (repo / "empty").mkdir()
    return scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1)).db_path


def test_tree_has_every_level_and_only_parent_links(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = q.graph3d_folder_tree()
    ids = {n.id for n in graph.nodes}
    assert ids == {"dir:.", "dir:src", "dir:src/a", "dir:src/b", "dir:src/b/c", "dir:src/only", "dir:src/only/deeper",
                   "dir:docs", "dir:build", "dir:empty"}  # intermediate folders included, .git never
    assert graph.level == "directory" and graph.root == "dir:."
    links = {(lk.source, lk.target, lk.kind) for lk in graph.links}
    assert links == {("dir:.", "dir:src", "contains"), ("dir:src", "dir:src/a", "contains"),
                     ("dir:src", "dir:src/b", "contains"), ("dir:src/b", "dir:src/b/c", "contains"),
                     ("dir:src", "dir:src/only", "contains"), ("dir:src/only", "dir:src/only/deeper", "contains"),
                     ("dir:.", "dir:docs", "contains"), ("dir:.", "dir:build", "contains"),
                     ("dir:.", "dir:empty", "contains")}  # the tree alone when the view opens
    by_id = {n.id: n for n in graph.nodes}
    assert all(n.kind == "directory" for n in graph.nodes)
    assert by_id["dir:build"].in_scope is False and "excluded" in by_id["dir:build"].note
    assert by_id["dir:src"].size == 4 and by_id["dir:."].size >= 6  # files below, every level
    assert by_id["dir:src/b"].lang == "c" and by_id["dir:src/only"].lang == "python"
    assert by_id["dir:src/b/c"].label == "src/b/c"


def test_tree_from_a_selected_folder(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = q.graph3d_folder_tree("src/b")
        assert {n.id for n in graph.nodes} == {"dir:src/b", "dir:src/b/c"}
        assert {n.label for n in graph.nodes} == {"src/b", "c"}  # paths relative to the selected folder
        assert graph.root == "dir:src/b"
        with pytest.raises(QueryError, match="unknown folder"):
            q.graph3d_folder_tree("nowhere")


def test_dependencies_between_folders_are_an_optional_layer(db: Path) -> None:
    with GraphQuery(db) as q:
        plain = q.graph3d_folder_tree()
        layered = q.graph3d_folder_tree(include_dependencies=True)
    assert {lk.kind for lk in plain.links} == {"contains"}
    extra = {(lk.source, lk.target, lk.kind) for lk in layered.links if lk.kind != "contains"}
    assert ("dir:src/a", "dir:src/b", "calls") in extra


def test_node_limit_keeps_the_upper_levels(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = q.graph3d_folder_tree(max_nodes=4)
    assert graph.truncated and len(graph.nodes) == 4 and "dir:." in {n.id for n in graph.nodes}
    ids = {n.id for n in graph.nodes}
    assert all(lk.source in ids and lk.target in ids for lk in graph.links)
