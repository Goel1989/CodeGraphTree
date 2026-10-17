"""Phase 7: the dependency table view of the desktop application."""

from __future__ import annotations

import csv
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
    qtbot.waitUntil(lambda: win.deps_view.page is not None, timeout=5000)
    return win


def test_table_filters_sorts_pages_and_drills_down(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    view = window.deps_view
    window.show_view(view)
    assert view.page.total == 9 and view.model.rowCount() == 9
    view.relationship.setCurrentText("include")
    qtbot.waitUntil(lambda: view.page.total == 2, timeout=5000)
    assert {r.relationship for r in view.model.rows} == {"include"}
    view.relationship.setCurrentIndex(0)
    view.level_box.setCurrentText("Files")
    qtbot.waitUntil(lambda: view.level == "file" and view.page is not None
                    and all(hasattr(r, "count") for r in view.model.rows), timeout=5000)
    group = next(i for i, r in enumerate(view.model.rows) if r.relationship == "include")
    count = view.model.rows[group].count
    view.activate(view.model.index(group, 0))  # the occurrences under the aggregated row
    qtbot.waitUntil(lambda: view.level == "site" and view.page.total == count
                    and all(hasattr(r, "site_id") for r in view.model.rows), timeout=5000)
    view.sort_by(5)  # relationship column
    qtbot.waitUntil(lambda: view.sort == "relationship", timeout=5000)


def test_row_opens_source_and_evidence_then_export(window, qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view = window.deps_view
    row = next(i for i, r in enumerate(view.model.rows) if r.rule == "bridge:fortran_c")
    view.activate(view.model.index(row, 0))
    qtbot.waitUntil(lambda: window.inspector.path == "csrc/solver.c", timeout=5000)
    qtbot.waitUntil(lambda: "bind" in view.evidence_view.toPlainText() or "mechanism" in view.evidence_view.toPlainText(),
                    timeout=5000)
    assert "trailing_underscore" in view.evidence_view.toPlainText()
    out = tmp_path / "deps.csv"
    view.export_to(out)
    qtbot.waitUntil(lambda: "exported" in view.evidence_view.toPlainText(), timeout=5000)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 9 and {"relationship", "rule", "line"} <= set(rows[0])
