"""Phase 8: interactions of the 3D views (2D/3D, filters, grouping, cycles, entry points, levels, shared evidence)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import FIXTURES, scan_fixture

pytest.importorskip("pytestqt")


def _stats(qtbot: Any, graph: Any) -> dict[str, Any]:
    box: list[Any] = []
    graph.query_js("JSON.stringify(window.cgs.stats())", box.append)
    qtbot.waitUntil(lambda: bool(box), timeout=5000)
    return json.loads(box[0])


def _open(qtbot: Any, repo: Path, proj: Path) -> Any:
    from codegraph_sci.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project_folder(repo, proj)
    graph = win.graph_functions
    qtbot.waitUntil(lambda: graph.page_ready and bool(graph.node_ids) and graph.js_nodes == len(graph.node_ids),
                    timeout=20000)
    return win


@pytest.fixture()
def hybrid(qtbot, tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "mini_hybrid" / "src", repo)
    scan_fixture("mini_hybrid", tmp_path / "proj", repo, expected_file="expected_graph_bridges.json")
    return _open(qtbot, repo, tmp_path / "proj")


def test_dimensions_filters_and_grouping(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = hybrid.graph_functions
    hybrid.show_view(graph)
    full = _stats(qtbot, graph)
    assert full["dims"] == 3 and full["nodes"] == len(graph.node_ids) and full["links"] > 0
    graph._run_js("window.cgs.setDims(2)")
    assert _stats(qtbot, graph)["dims"] == 2
    graph._run_js("window.cgs.setDims(3)")
    graph._run_js("window.cgs.filter({langs: ['python']})")
    no_python = _stats(qtbot, graph)
    assert no_python["nodes"] < full["nodes"]
    graph._run_js("window.cgs.filter({langs: [], kinds: " + json.dumps(full["kinds"]) + "})")
    assert _stats(qtbot, graph)["links"] == 0
    graph._run_js("window.cgs.filter({kinds: [], path: 'csrc/'})")
    only_c = _stats(qtbot, graph)
    assert 0 < only_c["nodes"] < full["nodes"]
    graph._run_js("window.cgs.reset()")
    graph._run_js("window.cgs.setGroupBy('directory')")
    grouped = _stats(qtbot, graph)
    assert grouped["groupBy"] == "directory" and grouped["groups"] >= 3 and grouped["nodes"] == full["nodes"]
    graph._run_js("window.cgs.setGroupBy('language')")
    assert _stats(qtbot, graph)["groups"] >= 3


def test_link_click_opens_the_same_evidence_as_the_table(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.query.api import GraphQuery

    graph = hybrid.graph_functions
    src, dst, kind = next(k for k in sorted(graph.link_keys) if k[2] != "defines")
    graph.handle_event({"event": "link", "source": src, "target": dst, "kind": kind})
    view = hybrid.deps_view
    qtbot.waitUntil(lambda: view.filters.caller == src and view.page is not None and bool(view.page.rows)
                    and all(r.caller == src and r.target == dst for r in view.model.rows), timeout=5000)
    with GraphQuery(hybrid.db) as q:
        expected = q.dependencies(q.link_evidence(src, dst, kind), limit=100)
    assert [r.site_id for r in view.model.rows] == [r.site_id for r in expected.rows]
    files = hybrid.graph_files
    qtbot.waitUntil(lambda: files.page_ready and bool(files.link_keys), timeout=20000)
    fsrc, fdst, fkind = sorted(files.link_keys)[0]
    files.handle_event({"event": "link", "source": fsrc, "target": fdst, "kind": fkind})
    qtbot.waitUntil(lambda: view.filters.caller_file == fsrc[5:] and bool(view.page.rows)
                    and all(r.caller_file == fsrc[5:] and r.target_file == fdst[5:] for r in view.model.rows),
                    timeout=5000)


def test_directory_level_view(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    dirs = hybrid.graph_dirs
    hybrid.show_view(dirs)
    qtbot.waitUntil(lambda: dirs.page_ready and dirs.node_ids == {"dir:.", "dir:app", "dir:csrc", "dir:ext",
                                                                   "dir:fsrc"}, timeout=20000)
    qtbot.waitUntil(lambda: dirs.js_nodes == 5, timeout=5000)  # the folder tree, from the project root
    assert _stats(qtbot, dirs)["level"] == "directory"


def test_cycles_and_entry_points_without_main(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "lib"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "core.py").write_text(
        "def ping():\n    pong()\n\n\ndef pong():\n    ping()\n\n\ndef start():\n    ping()\n\n\n"
        "def other():\n    helper()\n\n\ndef helper():\n    pass\n", encoding="utf-8")
    scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1))
    win = _open(qtbot, repo, tmp_path / "proj")
    graph = win.graph_functions
    win.show_view(graph)
    stats = _stats(qtbot, graph)
    assert stats["cycleNodes"] == ["py:pkg.core.ping", "py:pkg.core.pong"]
    assert {"py:pkg.core.start", "py:pkg.core.other"} <= set(stats["entries"])  # several entry points, no main
