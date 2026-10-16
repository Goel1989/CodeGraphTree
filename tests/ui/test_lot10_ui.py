from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph_sci.query.types import Direction
from tests.helpers import FIXTURES, scan_fixture

pytest.importorskip("pytestqt")


@pytest.fixture()
def window(qtbot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from codegraph_sci.ui.main_window import MainWindow

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "mini_hybrid" / "src", repo)
    scan_fixture("mini_hybrid", tmp_path / "proj", repo, expected_file="expected_graph_bridges.json")
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project_folder(repo, tmp_path / "proj")
    qtbot.waitUntil(lambda: win.inventory_table.rowCount() == 4, timeout=5000)
    win.repo = repo  # type: ignore[attr-defined]
    return win


def test_inventory_files_and_health(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    langs = {window.inventory_table.item(i, 0).text() for i in range(window.inventory_table.rowCount())}
    assert langs == {"c", "cpp", "fortran", "python"}
    qtbot.waitUntil(lambda: window.files_view.model() is not None, timeout=5000)
    assert window.files_view.model().rowCount() == 4  # app, csrc, ext, fsrc
    qtbot.waitUntil(lambda: "Unresolved rate" in window.health_view.toPlainText(), timeout=5000)


def test_s2_search_then_callers(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.search.setText("kernel")
    window.run_search()
    qtbot.waitUntil(lambda: window.current is not None and window.current.uid == "f:kernel", timeout=5000)
    assert "Called by <b>1</b> routine(s) in <b>1</b>" in window.summary.text()
    assert window.links_tabs.tabText(0) == "Callers (1)"
    top = window.callers_tree.topLevelItem(0)
    assert top.text(0).startswith("c_solve")
    site = top.child(0)
    assert site.text(1) == "csrc/solver.c:7:5"
    window._link_activated(site, 0)  # double-click -> code at the call line
    qtbot.waitUntil(lambda: window.inspector.path == "csrc/solver.c", timeout=5000)
    assert window.inspector.editor.textCursor().blockNumber() == 6


def test_lazy_tree_and_navigation(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.select_symbol("py:app.run.run_case")
    qtbot.waitUntil(lambda: window.tree_model is not None, timeout=5000)
    model = window.tree_model
    assert model.direction is Direction.CALLEES
    root = model.index(0, 0)
    model.fetchMore(root)
    first = model.index(0, 0, root)
    assert model.node_uid(first) == "cpp:hybrid::solve(int)"
    model.fetchMore(first)
    assert model.node_uid(model.index(0, 0, first)) == "c:c_solve"


def test_s10_stale_banner(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    target = window.repo / "fsrc" / "kernel.f90"
    target.write_text(target.read_text(encoding="utf-8") + "! changed\n", encoding="utf-8")
    window.show_file("fsrc/kernel.f90", 1)
    qtbot.waitUntil(lambda: window.inspector.path == "fsrc/kernel.f90", timeout=5000)
    assert window.inspector.banner.isVisibleTo(window.inspector)


def test_s1_open_folder_runs_inventory_and_scan(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.ui.main_window import MainWindow

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "fortran_basic" / "src", repo)
    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project_folder(repo, tmp_path / "proj")
    qtbot.waitUntil(lambda: win.db is not None and not win.process.running() and not win.pending_scan,
                    timeout=60000)
    qtbot.waitUntil(lambda: win.inventory_table.rowCount() == 1, timeout=5000)
    assert win.inventory_table.item(0, 0).text() == "fortran"
    # Cancel a running analysis: the interface stays usable.
    win.start_scan()
    assert win.process.running()
    win.cancel_scan()
    qtbot.waitUntil(lambda: not win.process.running(), timeout=10000)
    assert win.btn_scan.isEnabled()


def test_s3_s4_graphs_3d(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = window.graph_functions
    files = window.graph_files
    # The embedded page answers through the JS bridge even without WebGL (offscreen tests).
    qtbot.waitUntil(lambda: graph.page_ready and files.page_ready, timeout=20000)
    window.select_symbol("py:app.run.run_case")
    qtbot.waitUntil(lambda: graph.root_uid == "py:app.run.run_case"
                    and "cpp:hybrid::solve(int)" in graph.node_ids, timeout=5000)
    qtbot.waitUntil(lambda: graph.js_nodes == len(graph.node_ids), timeout=5000)  # data reached the page
    qtbot.waitUntil(lambda: "file:app/run.py" in files.node_ids, timeout=5000)
    assert all(uid.startswith("file:") for uid in files.node_ids)
    window.show_link_sites("c:c_solve", "f:kernel")
    qtbot.waitUntil(lambda: window.results.count() == 1, timeout=5000)
    assert "csrc/solver.c:7:5" in window.results.item(0).text()


def test_graphs_3d_start_from_main(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph_fn = window.graph_functions
    graph_fl = window.graph_files
    qtbot.waitUntil(lambda: "py:app.run.run_case" in graph_fn.node_ids and "c:c_solve" in graph_fn.node_ids,
                    timeout=5000)
    qtbot.waitUntil(lambda: "file:app/run.py" in graph_fl.node_ids, timeout=5000)
    assert graph_fn.main_uid == graph_fn.root_uid
    assert ("py:app.run.run_case", "cpp:hybrid::solve(int)") in {(s, t) for s, t, _ in graph_fn.link_keys}


def test_graph_3d_events_select_expand_link_and_paths(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = window.graph_functions
    qtbot.waitUntil(lambda: graph.main_uid is not None, timeout=5000)
    graph.depth.setValue(1)
    assert window.db is not None
    graph.set_root(window.db, "f:kernel")
    qtbot.waitUntil(lambda: graph.node_ids == {"f:kernel", "c:c_solve"}, timeout=5000)
    # Right-click in the page: neighbours are merged, nothing already shown is dropped.
    graph.handle_event({"event": "expand", "uid": "c:c_solve"})
    qtbot.waitUntil(lambda: "cpp:hybrid::solve(int)" in graph.node_ids, timeout=5000)
    assert {"f:kernel", "c:c_solve"} <= graph.node_ids
    # Click in the page: the panels follow, the graph stays.
    shown = set(graph.node_ids)
    graph.handle_event({"event": "select", "uid": "c:c_solve"})
    qtbot.waitUntil(lambda: window.current is not None and window.current.uid == "c:c_solve", timeout=5000)
    assert graph.node_ids == shown and graph.root_uid == "f:kernel"
    # Click on a link: its call sites are listed.
    graph.handle_event({"event": "link", "source": "c:c_solve", "target": "f:kernel"})
    qtbot.waitUntil(lambda: window.results.count() == 1, timeout=5000)
    # Paths to main: only the routines between main and the selected node.
    graph.handle_event({"event": "select", "uid": "f:kernel"})
    graph.btn_to_main.setChecked(True)
    qtbot.waitUntil(lambda: "py:app.run.run_case" in graph.node_ids and "main" in graph.info.text().lower(),
                    timeout=5000)
    graph.handle_event({"event": "bogus"})  # unknown events are ignored
    graph.handle_event({"event": "select"})
