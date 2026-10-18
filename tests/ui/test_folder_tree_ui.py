"""Folders 3D: the folder tree from the selected folder, every level, spheres; dependencies off at opening."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("pytestqt")

FILES = {
    "src/a/x.c": "void x(void) { y(); }\n",
    "src/b/y.c": "void y(void) {}\n",
    "src/b/c/z.py": "def z():\n    pass\n",
    "docs/readme.md": "# readme\n",
}


def _stats(qtbot: Any, graph: Any) -> dict[str, Any]:
    box: list[Any] = []
    graph.query_js("JSON.stringify(window.cgs.stats())", box.append)
    qtbot.waitUntil(lambda: bool(box), timeout=5000)
    return json.loads(box[0])


@pytest.fixture()
def window(qtbot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan
    from codegraph_sci.ui.main_window import MainWindow

    repo = tmp_path / "repo"
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1))
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project_folder(repo, tmp_path / "proj")
    dirs = win.graph_dirs
    qtbot.waitUntil(lambda: dirs.page_ready and "dir:src/b/c" in dirs.node_ids, timeout=20000)
    return win


def test_opens_on_the_tree_alone(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    dirs = window.graph_dirs
    window.show_view(dirs)
    assert dirs.node_ids == {"dir:.", "dir:src", "dir:src/a", "dir:src/b", "dir:src/b/c", "dir:docs"}
    assert {k[2] for k in dirs.link_keys} == {"contains"} and not dirs.with_dependencies.isChecked()
    qtbot.waitUntil(lambda: dirs.js_nodes == 6, timeout=5000)
    stats = _stats(qtbot, dirs)
    assert stats["kinds"] == ["contains"] and stats["level"] == "directory"
    assert stats["layout"] in ("radialout", "none")  # "none": no WebGL on this machine (offscreen tests)


def test_tree_from_the_selected_folder_and_back(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    dirs = window.graph_dirs
    dirs.handle_event({"event": "expand", "uid": "dir:src/b"})  # right-click on a folder
    qtbot.waitUntil(lambda: dirs.node_ids == {"dir:src/b", "dir:src/b/c"}, timeout=5000)
    assert dirs.btn_parent.isEnabled()
    dirs.btn_parent.click()
    qtbot.waitUntil(lambda: "dir:src/a" in dirs.node_ids and "dir:docs" not in dirs.node_ids, timeout=5000)
    dirs.btn_project_root.click()
    qtbot.waitUntil(lambda: "dir:docs" in dirs.node_ids, timeout=5000)
    assert not dirs.btn_parent.isEnabled()


def test_explorer_folder_opens_its_tree(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.ui.models import FileTreeModel

    qtbot.waitUntil(lambda: window.files_view.model() is not None, timeout=5000)
    model = window.files_view.model()
    matches = model.match(model.index(0, 0), FileTreeModel.PATH_ROLE, "dir:src/b", 1,
                          __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.MatchFlag.MatchRecursive)
    assert matches
    window._file_activated(matches[0])
    assert window.views.currentWidget() is window.graph_dirs
    qtbot.waitUntil(lambda: window.graph_dirs.node_ids == {"dir:src/b", "dir:src/b/c"}, timeout=5000)


def test_dependencies_are_an_optional_layer(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    dirs = window.graph_dirs
    dirs.with_dependencies.setChecked(True)
    qtbot.waitUntil(lambda: ("dir:src/a", "dir:src/b", "calls") in dirs.link_keys, timeout=5000)
    dirs.handle_event({"event": "link", "source": "dir:.", "target": "dir:src", "kind": "contains"})
    assert window.deps_view.filters.caller_dir is None  # a parent-child link has no dependency rows
