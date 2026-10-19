"""File dependencies in the interface (file_dependency_migration_instructions_EN.md, lot 2, decision D40).

Files is the opening view; Functions 3D, the function tree and function navigation are gone. The side panel shows the
Dependents and Dependencies of the selected file and its potential impact; a link (in the panel or in a graph) opens
its occurrences filtered by relationship; filters by path, language, relationship and resolution; file cycles.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import FIXTURES, scan_fixture

pytest.importorskip("pytestqt")


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
    return _open(qtbot, repo, tmp_path / "proj")


def _select(qtbot: Any, win: Any, path: str) -> None:
    win.select_file(path)
    qtbot.waitUntil(lambda: win.current_file == path and win.relations_loaded, timeout=5000)


def _tops(tree: Any) -> list[str]:
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_files_is_the_opening_view_and_function_views_are_gone(hybrid) -> None:  # type: ignore[no-untyped-def]
    assert hybrid.views.currentWidget() is hybrid.graph_files
    assert [b.text() for b in hybrid.nav_buttons] == ["Files", "Folders", "Dependencies"]
    for gone in ("graph_functions", "tree_box", "tree_view", "callers_tree", "callees_tree", "select_symbol"):
        assert not hasattr(hybrid, gone), gone
    assert [hybrid.links_tabs.tabText(i).split(" (")[0] for i in range(hybrid.links_tabs.count())] == \
        ["Dependents", "Dependencies", "Impact"]
    assert "file" in hybrid.hero.subtitle.text().lower()


def test_selected_file_shows_its_dependents_and_dependencies(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "csrc/solver.c")
    assert hybrid.links_tabs.tabText(0) == "Dependents (1)" and hybrid.links_tabs.tabText(1) == "Dependencies (2)"
    assert _tops(hybrid.dependents_tree) == ["ext/bindings.cpp"]
    assert _tops(hybrid.dependencies_tree) == ["csrc/solver_api.h", "fsrc/kernel.f90"]
    kernel = hybrid.dependencies_tree.topLevelItem(1)
    assert kernel.text(1) == "bridge 1" and kernel.text(2) == "confirmed"
    assert kernel.child(0).text(0) == "bridge" and kernel.child(0).text(2) == "resolved"
    assert hybrid.hero.badge_dependents.text() == "1\ndependents"
    assert hybrid.hero.badge_dependencies.text() == "2\ndependencies"
    assert hybrid.hero.title.text() == "solver.c"
    assert "impact" in hybrid.summary.text().lower()
    qtbot.waitUntil(lambda: hybrid.inspector.path == "csrc/solver.c", timeout=5000)


def test_a_link_of_the_panel_opens_its_occurrences(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "csrc/solver.c")
    kernel = hybrid.dependencies_tree.topLevelItem(1)
    hybrid._relation_activated(kernel.child(0), 0)  # the relationship row: its occurrences
    view = hybrid.deps_view
    assert hybrid.views.currentWidget() is view and view.scope_bar.isVisibleTo(view)
    assert view.filters.caller_file == "csrc/solver.c" and view.filters.target_file == "fsrc/kernel.f90"
    assert view.filters.relationships == ("bridge",) and view.level == "site"
    qtbot.waitUntil(lambda: view.page is not None and len(view.model.rows) == 1, timeout=5000)
    row = view.model.rows[0]
    assert (row.caller_file, row.line, row.relationship) == ("csrc/solver.c", 7, "bridge")
    view.open_row(row)  # its source location
    qtbot.waitUntil(lambda: hybrid.inspector.path == "csrc/solver.c"
                    and hybrid.inspector.editor.textCursor().blockNumber() == 6, timeout=5000)
    hybrid._relation_activated(hybrid.dependents_tree.topLevelItem(0), 0)  # a file row: select that file
    qtbot.waitUntil(lambda: hybrid.current_file == "ext/bindings.cpp", timeout=5000)


def test_a_graph_link_opens_its_occurrences_by_relationship(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    graph, view = hybrid.graph_files, hybrid.deps_view
    qtbot.waitUntil(lambda: bool(graph.link_keys), timeout=20000)
    kinds = {k[2] for k in graph.link_keys}
    assert kinds <= {"bridge", "binding", "binding_declaration", "include", "call", "import"} and "bridge" in kinds
    graph.handle_event({"event": "link", "source": "file:csrc/solver.c", "target": "file:csrc/solver_api.h",
                        "kind": "include"})
    assert hybrid.views.currentWidget() is view
    assert view.filters.relationships == ("include",) and view.filters.caller_file == "csrc/solver.c"
    qtbot.waitUntil(lambda: view.page is not None and [r.relationship for r in view.model.rows] == ["include"],
                    timeout=5000)


def test_panel_filters_path_language_relationship_resolution(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "csrc/solver.c")
    hybrid.filter_relationship.setCurrentText("include")
    assert _tops(hybrid.dependencies_tree) == ["csrc/solver_api.h"]
    assert hybrid.hero.badge_dependencies.text().startswith("1")
    hybrid.filter_relationship.setCurrentIndex(0)
    hybrid.filter_language.setCurrentText("fortran")
    assert _tops(hybrid.dependencies_tree) == ["fsrc/kernel.f90"] and _tops(hybrid.dependents_tree) == []
    hybrid.filter_language.setCurrentIndex(0)
    hybrid.filter_path.setText("csrc/")
    assert _tops(hybrid.dependencies_tree) == ["csrc/solver_api.h"]
    hybrid.filter_path.clear()
    hybrid.filter_resolution.setCurrentText("possible")
    assert _tops(hybrid.dependencies_tree) == [] and hybrid.links_tabs.tabText(1) == "Dependencies (0)"


def test_impact_lists_every_file_that_may_be_affected(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    _select(qtbot, hybrid, "fsrc/kernel.f90")
    assert hybrid.links_tabs.tabText(2) == "Impact (3)"
    rows = [(hybrid.impact_tree.topLevelItem(i).text(0), hybrid.impact_tree.topLevelItem(i).text(1),
             hybrid.impact_tree.topLevelItem(i).text(2)) for i in range(hybrid.impact_tree.topLevelItemCount())]
    assert rows == [("csrc/solver.c", "1", "confirmed"), ("ext/bindings.cpp", "2", "confirmed"),
                    ("app/run.py", "3", "confirmed")]


def test_file_cycles_without_any_main(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    for rel, text in {"cyc/__init__.py": "", "cyc/a.py": "from cyc import b\n\n\ndef fa():\n    b.fb()\n",
                      "cyc/b.py": "from cyc import a\n\n\ndef fb():\n    a.fa()\n",
                      "lone.py": "def alone():\n    pass\n"}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1))
    win = _open(qtbot, repo, tmp_path / "proj")
    qtbot.waitUntil(lambda: "File cycles: 1" in win.health_view.toPlainText(), timeout=5000)
    assert "cyc/a.py, cyc/b.py" in win.health_view.toPlainText()
    _select(qtbot, win, "cyc/a.py")
    assert "in a cycle with 1 other file" in win.summary.text()
    _select(qtbot, win, "lone.py")  # an isolated file is still a file of the project
    assert win.links_tabs.tabText(0) == "Dependents (0)" and "cycle" not in win.summary.text()


def test_search_and_explorer_open_files(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    hybrid.search.setText("kernel")
    hybrid.run_search()
    qtbot.waitUntil(lambda: hybrid.current_file == "fsrc/kernel.f90", timeout=5000)
    qtbot.waitUntil(lambda: hybrid.graph_files.root_uid == "file:fsrc/kernel.f90", timeout=5000)
    hybrid.open_target("c:c_solve")  # a reference in the source: the file defining its target
    qtbot.waitUntil(lambda: hybrid.current_file == "csrc/solver.c", timeout=5000)


def test_dependency_table_offers_file_levels_and_filters(hybrid, qtbot) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.query.api import GraphQuery

    view = hybrid.deps_view
    assert [view.level_box.itemText(i) for i in range(view.level_box.count())] == ["Files", "Folders", "Occurrences"]
    assert view.level == "file"
    qtbot.waitUntil(lambda: view.page is not None and view.page.total > 0, timeout=5000)
    with GraphQuery(hybrid.db) as q:  # between two files, the table counts what the graph draws
        graph = {(d.source, d.target, d.relationship): d.count for d in q.file_dependencies()}
    assert {(g.source, g.target, g.relationship): g.count for g in view.model.rows
            if g.target is not None and g.target != g.source} == graph
    view.language.setCurrentText("c")
    qtbot.waitUntil(lambda: view.filters.language == "c", timeout=5000)
    view.path.setText("csrc/")
    view.apply_filters()
    qtbot.waitUntil(lambda: view.filters.path == "csrc/" and view.page is not None
                    and {g.source for g in view.model.rows} <= {"csrc/solver.c"}, timeout=5000)


def test_panels_never_query_on_the_gui_thread(hybrid, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.query.api import GraphQuery

    main = threading.main_thread()
    calls: list[bool] = []
    for name in ("file_relations", "file_impact"):
        original = getattr(GraphQuery, name)

        def spy(self: Any, *args: Any, _original: Any = original, **kwargs: Any) -> Any:
            calls.append(threading.current_thread() is main)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(GraphQuery, name, spy)
    _select(qtbot, hybrid, "ext/bindings.cpp")
    assert calls and not any(calls), "a file query ran on the GUI thread"
