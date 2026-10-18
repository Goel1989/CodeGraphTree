from __future__ import annotations

import shutil
from pathlib import Path

import pytest

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
    files = window.graph_files
    # The embedded page answers through the JS bridge even without WebGL (offscreen tests).
    qtbot.waitUntil(lambda: files.page_ready, timeout=20000)
    window.select_file("fsrc/kernel.f90")
    qtbot.waitUntil(lambda: files.root_uid == "file:fsrc/kernel.f90"
                    and "file:csrc/solver.c" in files.node_ids, timeout=5000)
    qtbot.waitUntil(lambda: files.js_nodes == len(files.node_ids), timeout=5000)  # data reached the page
    assert all(uid.startswith("file:") for uid in files.node_ids)


def test_graphs_3d_start_from_main(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = window.graph_files
    qtbot.waitUntil(lambda: "file:app/run.py" in graph.node_ids and "file:fsrc/kernel.f90" in graph.node_ids,
                    timeout=5000)
    # The project fits under the node ceiling: the overview shows every file and every dependency.
    assert graph.overview and graph.main_uid == "file:app/run.py"
    assert ("file:app/run.py", "file:ext/bindings.cpp", "binding") in graph.link_keys
    graph.btn_from_main.click()
    qtbot.waitUntil(lambda: not graph.overview and graph.root_uid == graph.main_uid, timeout=5000)


def test_graph_3d_groups_open_and_back(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = window.graph_files
    qtbot.waitUntil(lambda: graph.overview and bool(graph.node_ids), timeout=5000)
    everything = set(graph.node_ids)
    selected = []
    graph.node_selected.connect(selected.append)
    graph.handle_event({"event": "select", "uid": "group:file:csrc/solver.c"})  # a group opens, it is not a file
    qtbot.waitUntil(lambda: not graph.overview and "file:fsrc/kernel.f90" in graph.node_ids, timeout=5000)
    assert selected == [] and "file:csrc/solver.c" in graph.node_ids
    graph.btn_groups.click()
    qtbot.waitUntil(lambda: graph.overview and graph.node_ids == everything, timeout=5000)


def test_graph_3d_events_select_expand_link_and_paths(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = window.graph_files
    qtbot.waitUntil(lambda: graph.main_uid is not None, timeout=5000)
    graph.depth.setValue(1)
    assert window.db is not None
    graph.set_root(window.db, "file:fsrc/kernel.f90")
    qtbot.waitUntil(lambda: graph.node_ids == {"file:fsrc/kernel.f90", "file:csrc/solver.c"}, timeout=5000)
    # Right-click in the page: neighbours are merged, nothing already shown is dropped.
    graph.handle_event({"event": "expand", "uid": "file:csrc/solver.c"})
    qtbot.waitUntil(lambda: "file:ext/bindings.cpp" in graph.node_ids, timeout=5000)
    assert {"file:fsrc/kernel.f90", "file:csrc/solver.c"} <= graph.node_ids
    # Click in the page: the panels follow, the graph stays.
    shown = set(graph.node_ids)
    graph.handle_event({"event": "select", "uid": "file:csrc/solver.c"})
    qtbot.waitUntil(lambda: window.current_file == "csrc/solver.c" and window.relations_loaded, timeout=5000)
    assert graph.node_ids == shown and graph.root_uid == "file:fsrc/kernel.f90"
    # Click on a link: its occurrences, filtered by its relationship, in the Dependencies view.
    graph.handle_event({"event": "link", "source": "file:csrc/solver.c", "target": "file:fsrc/kernel.f90",
                        "kind": "bridge"})
    view = window.deps_view
    qtbot.waitUntil(lambda: view.page is not None and len(view.model.rows) == 1, timeout=5000)
    assert window.views.currentWidget() is view and view.filters.relationships == ("bridge",)
    # Paths to main: only the files between main and the selected file.
    view.back.click()
    graph.handle_event({"event": "select", "uid": "file:fsrc/kernel.f90"})
    graph.btn_to_main.setChecked(True)
    qtbot.waitUntil(lambda: "file:app/run.py" in graph.node_ids and "main" in graph.info.text().lower(),
                    timeout=5000)
    graph.handle_event({"event": "bogus"})  # unknown events are ignored
    graph.handle_event({"event": "select"})


def test_frameless_shell_and_navigation(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt

    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.title_bar.height() == 28 and window.rail.width() == 50
    assert window.title_bar.title.text().startswith("CodeGraph-Sci")
    window.rail_buttons["project"].click()
    assert [b.text() for b in window.nav_buttons] == ["Inventory", "Analysis health"]
    window.nav_buttons[1].click()
    assert window.views.currentWidget() is window.health_view
    assert window.header_title.text() == "ANALYSIS HEALTH" and window.nav_buttons[1].isChecked()
    window.show_view(window.graph_files)  # jumps to the group of the view
    assert window.rail_buttons["explore"].isChecked() and window.header_title.text() == "FILES"
    assert [b.text() for b in window.nav_buttons] == ["Files", "Folders", "Dependencies"]


def test_hero_card_badges_and_popovers(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox, QPushButton

    hero = window.hero
    assert "Select a file" in hero.subtitle.text()
    window.select_file("fsrc/kernel.f90")
    qtbot.waitUntil(lambda: hero.title.text() == "kernel.f90" and window.relations_loaded, timeout=5000)
    assert hero.badge_dependents.text().startswith("1") and hero.badge_dependencies.text().startswith("0")
    assert (hero.badge_dependents.width(), hero.badge_dependents.height()) == (48, 48)
    hero.badge_dependencies.click()
    assert window.links_tabs.currentIndex() == 1
    hero.btn_filters.click()
    assert window.filters_popover.isVisible()
    assert window.filter_relationship in window.filters_popover.findChildren(QComboBox)
    window.filters_popover.close()
    hero.btn_analysis.click()
    assert window.btn_scan in window.analysis_popover.findChildren(QPushButton)
    window.analysis_popover.close()


def test_title_bar_window_controls(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    window.show()
    window.title_bar.btn_max.click()
    qtbot.waitUntil(window.isMaximized, timeout=3000)
    window.title_bar.btn_max.click()
    qtbot.waitUntil(lambda: not window.isMaximized(), timeout=3000)


def test_opening_a_project_stops_the_running_command(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    assert window.project is not None
    window.start_scan()
    assert window.process.running()
    window.open_project_folder(window.repo, window.project.folder)
    assert not window.process.running() and not window.pending_scan
    qtbot.waitUntil(lambda: window.btn_scan.isEnabled(), timeout=5000)


def test_inventory_shows_skipped_folders_and_all_subfolders_option(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    gen = window.repo / "build" / "gen.f90"
    gen.parent.mkdir()
    gen.write_text("subroutine gen\nend subroutine gen\n", encoding="utf-8")
    window.start_scan()
    qtbot.waitUntil(lambda: not window.process.running(), timeout=60000)
    qtbot.waitUntil(lambda: "build" in window.skipped_label.text(), timeout=5000)
    assert not window.all_subfolders.isChecked()
    window.all_subfolders.setChecked(True)  # profile change, then a new analysis
    qtbot.waitUntil(lambda: window.process.running() or window.pending_scan, timeout=5000)
    qtbot.waitUntil(lambda: not window.process.running() and not window.pending_scan, timeout=60000)
    qtbot.waitUntil(lambda: "No folder skipped" in window.skipped_label.text(), timeout=5000)
    assert window.all_subfolders.isChecked()
