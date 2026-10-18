"""Non-regression tests of the UI audit (9 findings, October 2026).

P1: minimum window width and overlapping graph controls; stale selection after a project change; Cancel leaving
worker processes alive. P2: call tree queries on the GUI thread; link evidence loaded in a hidden view with stale
filters; overestimated confidence; failures leaving the UI blocked; counters and badges with different filters;
keyboard access and accessible names.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import FIXTURES, scan_fixture

pytest.importorskip("pytestqt")

MAX_MIN_WIDTH = 1100  # the window must fit a 1280-pixel screen with its frame


def _open(qtbot: Any, repo: Path, proj: Path) -> Any:
    from codegraph_sci.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.open_project_folder(repo, proj)
    qtbot.waitUntil(lambda: win.inventory_table.rowCount() > 0 and win.deps_view.page is not None, timeout=10000)
    return win


@pytest.fixture()
def hybrid(qtbot, tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "mini_hybrid" / "src", repo)
    scan_fixture("mini_hybrid", tmp_path / "proj", repo, expected_file="expected_graph_bridges.json")
    win = _open(qtbot, repo, tmp_path / "proj")
    win.repo = repo  # type: ignore[attr-defined]
    return win


def _select(qtbot: Any, win: Any, uid: str) -> None:
    win.select_symbol(uid)
    qtbot.waitUntil(lambda: win.current is not None and win.current.uid == uid, timeout=5000)


# ----------------------------------------------------------------- P1: width and overlaps
def test_window_fits_a_small_screen_with_a_project_loaded(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "f:kernel")
    long = "x" * 400  # long texts (paths, uids, status) must not widen the window
    hybrid.status_label.setText(long)
    hybrid.header_info.setText(long)
    hybrid.hero.subtitle.setText(long)
    hybrid.graph_functions.info.setText(long)
    hybrid.skipped_label.setText(long)
    for view in (hybrid.graph_functions, hybrid.graph_files, hybrid.graph_dirs, hybrid.deps_view,
                 hybrid.inventory_view, hybrid.health_view):
        hybrid.show_view(view)
        qtbot.wait(20)
        assert hybrid.minimumSizeHint().width() <= MAX_MIN_WIDTH, view
    hybrid.resize(MAX_MIN_WIDTH, 760)
    qtbot.wait(50)
    assert hybrid.width() <= MAX_MIN_WIDTH + 20


def test_graph_page_controls_never_overlap(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph = hybrid.graph_functions
    hybrid.show_view(graph)
    qtbot.waitUntil(lambda: graph.page_ready, timeout=20000)
    for width in (1400, 900, 600):
        graph.web.setFixedSize(width, 520)
        qtbot.wait(150)
        box: list[Any] = []
        graph.query_js("JSON.stringify(window.cgs.overlaps())", box.append)
        qtbot.waitUntil(lambda box=box: bool(box), timeout=5000)
        assert json.loads(box[0]) == [], width


# ----------------------------------------------------------------- P1: project change
def test_project_change_clears_the_previous_selection(hybrid, qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "f:kernel")
    qtbot.waitUntil(lambda: hybrid.inspector.path == "fsrc/kernel.f90", timeout=5000)
    other = tmp_path / "other"
    shutil.copytree(FIXTURES / "fortran_basic" / "src", other)
    scan_fixture("fortran_basic", tmp_path / "proj2", other)
    hybrid.open_project_folder(other, tmp_path / "proj2")
    assert hybrid.current is None  # immediately, before any answer of the new project
    assert hybrid.inspector.path is None and hybrid.inspector.editor.toPlainText() == ""
    assert hybrid.callers_tree.topLevelItemCount() == 0 and hybrid.callees_tree.topLevelItemCount() == 0
    assert hybrid.hero.badge_callers.text().startswith("—") and hybrid.tree_view.model() is None
    assert hybrid.results.count() == 0 and hybrid.graph_functions.node_ids == set()
    assert hybrid.deps_view.model.rowCount() == 0
    qtbot.waitUntil(lambda: hybrid.deps_view.page is not None and hybrid.deps_view.db is not None
                    and all(r.caller_file.endswith(".f90") for r in hybrid.deps_view.model.rows), timeout=10000)


# ----------------------------------------------------------------- P1: cancel stops every process
def test_cancel_stops_the_whole_process_tree(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import os
    import subprocess
    import sys
    import time

    marker = tmp_path / "workers"
    marker.mkdir()
    script = tmp_path / "pool.py"
    script.write_text(f'''
import os, sys, time
sys.path.insert(0, {str(Path(__file__).parents[2])!r})
from codegraph_sci.extract_pool import run_tasks

def job(path):
    open(os.path.join({str(marker)!r}, str(os.getpid())), "w").close()
    time.sleep(60)
    return path, None, None

if __name__ == "__main__":
    run_tasks([("a",), ("b",)], workers=2, timeout_s=120, on_done=lambda *a: None, job=job)
''', encoding="utf-8")
    parent = subprocess.Popen([sys.executable, str(script)])
    deadline = time.time() + 30
    while len(list(marker.iterdir())) < 2 and time.time() < deadline:
        time.sleep(0.2)
    pids = [int(p.name) for p in marker.iterdir()]
    assert len(pids) == 2
    parent.kill()  # what Cancel did: only the main process
    parent.wait(10)

    def alive(pid: int) -> bool:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
            return str(pid) in out
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    deadline = time.time() + 15
    while any(alive(p) for p in pids) and time.time() < deadline:
        time.sleep(0.2)
    assert not any(alive(p) for p in pids), "extraction workers outlived their parent"


def test_cancel_kills_the_command_and_its_children(qtbot, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import sys

    import codegraph_sci.ui.workers as workers

    killed: list[int] = []
    monkeypatch.setattr(workers, "kill_tree", lambda pid: killed.append(pid))
    process = workers.CgsProcess()
    monkeypatch.setattr(workers, "cgs_command", lambda: (sys.executable, ["-c", "import time; time.sleep(30)"]))
    process.start([])
    qtbot.waitUntil(process.running, timeout=5000)
    pid = process.proc.processId()
    done: list[int] = []
    process.finished.connect(lambda code, _err: done.append(code))
    process.cancel(wait=True)
    assert killed == [pid]
    qtbot.waitUntil(lambda: bool(done), timeout=5000)


# ----------------------------------------------------------------- P2: call tree off the GUI thread
def test_call_tree_never_queries_on_the_gui_thread(hybrid, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.query.api import GraphQuery

    main = threading.main_thread()
    calls: list[bool] = []
    original = GraphQuery.children

    def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(threading.current_thread() is main)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GraphQuery, "children", spy)
    _select(qtbot, hybrid, "py:app.run.run_case")
    hybrid.show_view(hybrid.tree_box)
    model = hybrid.tree_model
    qtbot.waitUntil(lambda: model is not None and model.rowCount(model.index(0, 0)) > 0, timeout=5000)
    assert calls and not any(calls), "a call-tree query ran on the GUI thread"
    assert not hasattr(model, "q")  # the model holds no database connection


# ----------------------------------------------------------------- P2: link evidence
def test_link_evidence_is_shown_with_consistent_filters(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph, view = hybrid.graph_functions, hybrid.deps_view
    hybrid.show_view(graph)
    view.relationship.setCurrentText("include")  # a stale filter of the table
    qtbot.waitUntil(lambda: view.page is not None and view.page.total == 2, timeout=5000)
    qtbot.waitUntil(lambda: bool(graph.link_keys), timeout=20000)
    src, dst, kind = next(k for k in sorted(graph.link_keys) if k[2] != "defines")
    graph.handle_event({"event": "link", "source": src, "target": dst, "kind": kind})
    assert hybrid.views.currentWidget() is view  # shown, not loaded in a hidden view
    assert view.relationship.currentIndex() == 0 and view.text.text() == "" and view.level_box.currentIndex() == 0
    assert view.scope_bar.isVisibleTo(view) and src in view.scope_label.text()
    qtbot.waitUntil(lambda: view.page is not None and bool(view.model.rows)
                    and all(r.caller == src and r.target == dst for r in view.model.rows), timeout=5000)
    view.status.setCurrentText("resolved")  # a widget filter keeps the link scope
    qtbot.waitUntil(lambda: view.filters.statuses == ("resolved",) and view.filters.caller == src, timeout=5000)
    view.back.click()
    assert hybrid.views.currentWidget() is graph
    view.clear_scope.click()
    qtbot.waitUntil(lambda: view.filters.caller is None and not view.scope_bar.isVisibleTo(view), timeout=5000)


# ----------------------------------------------------------------- P2: confidence
def test_the_weakest_confidence_of_a_routine_is_shown(hybrid) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.query.types import CallerReport, CallSite, LinkItem, NodeSummary

    node = NodeSummary("f:x", "x", "routine", None, "fortran", "a.f90", 1)
    sites = [CallSite("a.f90", 2, 1, "x", "call", None, "native:fortran", confidence, "resolved")
             for confidence in ("exact", "heuristic", "resolved")]
    report = CallerReport(node, 1, 1, 3, [LinkItem(node, sites)])
    hybrid._fill_links(hybrid.callers_tree, report)
    assert hybrid.callers_tree.topLevelItem(0).text(2) == "heuristic"


# ----------------------------------------------------------------- P2: failures
def test_failed_command_unblocks_the_interface(hybrid, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    hybrid.project = type(hybrid.project)(hybrid.project.folder, hybrid.repo / "missing-folder")
    hybrid.start_scan()
    qtbot.waitUntil(lambda: not hybrid.process.running(), timeout=20000)
    qtbot.waitUntil(lambda: hybrid.btn_scan.isEnabled(), timeout=5000)
    assert "in progress" not in hybrid.status_label.text().lower() and "failed" in hybrid.status_label.text().lower()
    assert not hybrid.btn_cancel.isEnabled() and hybrid.progress.isHidden()


def test_command_that_cannot_start_unblocks_the_interface(hybrid, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    import codegraph_sci.ui.workers as workers

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(workers, "cgs_command", lambda: ("no-such-program-cgs", []))
    hybrid.start_scan()
    qtbot.waitUntil(lambda: hybrid.btn_scan.isEnabled(), timeout=10000)
    assert "failed" in hybrid.status_label.text().lower() and hybrid.progress.isHidden()


# ----------------------------------------------------------------- P2: counters
def test_badges_and_summary_count_what_the_lists_show(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "c:c_solve")
    callees_all = hybrid.hero.badge_callees.text().split("\n")[0]
    hybrid.min_conf.setCurrentIndex(3)  # exact only: the bridge call (resolved) is filtered out
    qtbot.waitUntil(lambda: hybrid.links_tabs.tabText(1) == "Callees (0)", timeout=5000)
    assert hybrid.hero.badge_callees.text().split("\n")[0] == "0"
    assert f"of {callees_all}" in hybrid.summary.text() or callees_all == "0"


# ----------------------------------------------------------------- P2: keyboard and accessible names
def test_main_actions_are_reachable_by_keyboard_and_named(hybrid) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton

    buttons = [b for b in hybrid.findChildren(QAbstractButton) if b.isVisibleTo(hybrid)]
    assert buttons
    for b in buttons:
        assert b.accessibleName() or b.text().strip(), b.toolTip() or b.objectName()
    for b in list(hybrid.rail_buttons.values()) + [hybrid.hero.badge_callers, hybrid.hero.badge_callees,
                                                   hybrid.hero.btn_view, hybrid.hero.btn_filters,
                                                   hybrid.hero.btn_analysis]:
        assert b.focusPolicy() & Qt.FocusPolicy.TabFocus, b.accessibleName()
        assert b.accessibleName()
    shortcuts = {a.shortcut().toString() for a in hybrid.actions()}
    assert {"Ctrl+O", "Ctrl+F", "F5"} <= shortcuts


# ----------------------------------------------------------------- gaps of the full audit report
def test_cancelled_queries_never_come_back(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """UI-02: after cancel_all, a new request with the same key must not accept the old answer."""
    import time

    from codegraph_sci.ui.workers import QueryRunner

    db = scan_fixture("fortran_basic", tmp_path / "proj").db_path
    runner = QueryRunner()
    got: list[str] = []
    runner.submit(db, "symbol", lambda q: (time.sleep(0.6), "old")[1], got.append)
    runner.cancel_all()
    runner.submit(db, "symbol", lambda q: "new", got.append)
    qtbot.wait(1500)
    assert got == ["new"]


def test_link_evidence_respects_the_relationship_type() -> None:
    """UI-05: two relationship types between the same pair are not mixed."""
    from codegraph_sci.query.api import GraphQuery

    assert GraphQuery.link_evidence("file:a.c", "file:b.h", "uses").relationships == ("import", "include", "inherit")
    assert "bridge" in GraphQuery.link_evidence("dir:a", "dir:b", "calls").relationships  # aggregated at that level
    assert GraphQuery.link_evidence("py:a", "py:b", "uses").relationships == ("import", "include")
    assert GraphQuery.link_evidence("c:a", "f:b", "bridges").relationships == ("bridge",)
    assert GraphQuery.link_evidence("c:a", "f:b", "calls").relationships == ("call", "dynamic_call")
    assert GraphQuery.link_evidence("c:a", "f:b").relationships == ()


def test_closing_the_window_stops_the_analysis(hybrid, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """UI-03: the window-close path stops a running command and its children."""
    import sys

    import codegraph_sci.ui.workers as workers

    killed: list[int] = []
    monkeypatch.setattr(workers, "kill_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(workers, "cgs_command", lambda: (sys.executable, ["-c", "import time; time.sleep(30)"]))
    hybrid.start_scan()
    qtbot.waitUntil(hybrid.process.running, timeout=5000)
    hybrid.close()
    assert killed and not hybrid.process.running()


def test_panel_filters_say_what_they_apply_to(hybrid) -> None:  # type: ignore[no-untyped-def]
    """UI-08: the filters popover names its scope; UI-09: it has a shortcut."""
    assert "callers" in hybrid.hero.btn_filters.accessibleName().lower()
    shortcuts = {a.shortcut().toString() for a in hybrid.actions()}
    assert "Ctrl+Shift+F" in shortcuts
