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


def test_s3_s4_treegraphs(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.select_symbol("py:app.run.run_case")
    graph = window.graph_functions
    qtbot.waitUntil(lambda: "cpp:hybrid::solve(int)" in graph.items, timeout=5000)
    start_positions = {u: (i.pos().x(), i.pos().y()) for u, i in graph.items.items()}
    graph.activate(graph.items["cpp:hybrid::solve(int)"])
    qtbot.waitUntil(lambda: "c:c_solve" in graph.items, timeout=5000)
    graph.activate(graph.items["c:c_solve"])
    qtbot.waitUntil(lambda: "f:kernel" in graph.items, timeout=5000)
    for uid, pos in start_positions.items():  # nodes already placed never move
        assert (graph.items[uid].pos().x(), graph.items[uid].pos().y()) == pos
    files = window.graph_files
    qtbot.waitUntil(lambda: len(files.items) >= 1, timeout=5000)
    assert "file:app/run.py" in files.items
    window.show_link_sites("c:c_solve", "f:kernel")
    qtbot.waitUntil(lambda: window.results.count() == 1, timeout=5000)
    assert "csrc/solver.c:7:5" in window.results.item(0).text()


def test_treegraphs_auto_from_main_and_directed_edges(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.ui.treegraph import EdgeItem

    graph_fn = window.graph_functions
    graph_fl = window.graph_files
    qtbot.waitUntil(lambda: "py:app.run.run_case" in graph_fn.items and "f:kernel" in graph_fn.items, timeout=5000)
    qtbot.waitUntil(lambda: "file:app/run.py" in graph_fl.items and "file:fsrc/kernel.f90" in graph_fl.items,
                    timeout=5000)

    fn_edges = [i for i in graph_fn.scene.items() if isinstance(i, EdgeItem)]
    assert fn_edges
    pairs = {(e.src.uid, e.dst.uid) for e in fn_edges}
    assert ("py:app.run.run_case", "cpp:hybrid::solve(int)") in pairs
    assert ("c:c_solve", "f:kernel") in pairs
    for edge in fn_edges:
        assert not edge.arrow_polygon.isEmpty()


def test_treegraph_click_connected_and_paths_to_main(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph_fn = window.graph_functions
    qtbot.waitUntil(lambda: "c:c_solve" in graph_fn.items, timeout=5000)
    # Set root to an intermediate node and click it to open both callers and callees.
    assert window.db is not None
    graph_fn.set_root(window.db, "c:c_solve", "c_solve", "c")
    qtbot.waitUntil(lambda: "c:c_solve" in graph_fn.items, timeout=5000)
    graph_fn.on_node_clicked(graph_fn.items["c:c_solve"])
    qtbot.waitUntil(
        lambda: "cpp:hybrid::solve(int)" in graph_fn.items and "f:kernel" in graph_fn.items,
        timeout=5000,
    )
    # Filter to only links up to main.
    graph_fn.on_node_clicked(graph_fn.items["f:kernel"])
    graph_fn.btn_to_main.setChecked(True)
    qtbot.waitUntil(
        lambda: "py:app.run.run_case" in graph_fn.items
        and "f:kernel" in graph_fn.items
        and "main" in graph_fn.info.text().lower(),
        timeout=5000,
    )

