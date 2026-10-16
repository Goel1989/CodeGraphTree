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
    qtbot.waitUntil(lambda: "Taux de non-résolus" in window.health_view.toPlainText(), timeout=5000)


def test_s2_search_then_callers(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.search.setText("kernel")
    window.run_search()
    qtbot.waitUntil(lambda: window.current is not None and window.current.uid == "f:kernel", timeout=5000)
    assert "Appelée par <b>1</b> routine(s) dans <b>1</b>" in window.summary.text()
    assert window.links_tabs.tabText(0) == "Appelants (1)"
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
