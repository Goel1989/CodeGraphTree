"""Dependency table view (requirements plan phase 7): every relationship, filtered and paged by the database.

The view never queries on the main thread: pages, aggregates, evidence and exports run in the query runner.
A double click on an occurrence opens its source and evidence; on an aggregated row it lists its occurrences.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from codegraph_sci.query.api import GraphQuery
from codegraph_sci.query.types import (
    RELATIONSHIPS,
    DependencyEvidence,
    DependencyFilter,
    DependencyGroup,
    DependencyPage,
    DependencyRow,
)
from codegraph_sci.ui.workers import QueryRunner

PAGE_SIZE = 200
SITE_COLUMNS = [("Caller", "caller", "caller"), ("File", "caller_file", "path"), ("Lang.", "caller_lang", "language"),
                ("Line", "line", "line"), ("Col.", "col", None), ("Relationship", "relationship", "relationship"),
                ("Target text", "target_text", None), ("Target", "target", "target"),
                ("Candidates", "candidates", None), ("Target file", "target_file", None),
                ("Target lang.", "target_lang", None), ("Status", "resolution", "status"), ("Rule", "rule", "rule"),
                ("Condition", "condition", None)]
GROUP_COLUMNS = [("Source", "source", "source"), ("Target", "target", "target"),
                 ("Relationship", "relationship", "relationship"), ("Occurrences", "count", "count"),
                 ("Statuses", "statuses", None)]
LEVELS = [("Occurrences", "site"), ("Entities", "entity"), ("Files", "file"), ("Directories", "directory")]
STATUSES = ["resolved", "ambiguous", "external", "out_of_scope", "unresolved"]
EXPORT_COLUMNS = ("caller", "caller_file", "caller_lang", "target_text", "target", "candidates", "target_file",
                  "target_lang", "relationship", "line", "col", "resolution", "confidence", "rule", "condition")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(map(str, value))
    if isinstance(value, dict):
        return ", ".join(f"{k} {v}" for k, v in value.items())
    return str(value)


class DependencyModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Any] = []
        self.columns = SITE_COLUMNS

    def set_rows(self, rows: list[Any], columns: list[tuple[str, str, str | None]]) -> None:
        self.beginResetModel()
        self.rows, self.columns = rows, columns
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        return _cell(getattr(self.rows[index.row()], self.columns[index.column()][1]))

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802 - Qt API
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section][0]
        return None


class DependencyView(QWidget):
    """Search, filter, sort, page, export; double click: source and evidence (or the occurrences of a group)."""

    source_requested = Signal(str, int)  # path, line

    def __init__(self, runner: QueryRunner) -> None:
        super().__init__()
        self.runner = runner
        self.db: Path | None = None
        self.filters = DependencyFilter()
        self.level = "site"
        self.sort, self.descending, self.offset = "path", False, 0
        self.page: DependencyPage | None = None
        self.evidence: DependencyEvidence | None = None
        self.text = QLineEdit()
        self.text.setPlaceholderText("Search caller, target, file…")
        self.text.returnPressed.connect(self.apply_filters)
        self.relationship = QComboBox()
        self.relationship.addItems(["All relationships", *RELATIONSHIPS])
        self.status = QComboBox()
        self.status.addItems(["All statuses", *STATUSES])
        self.level_box = QComboBox()
        self.level_box.addItems([label for label, _k in LEVELS])
        for box in (self.relationship, self.status, self.level_box):
            box.currentIndexChanged.connect(self.apply_filters)
        self.prev = QPushButton("◀")
        self.next = QPushButton("▶")
        self.prev.clicked.connect(lambda: self.turn(-1))
        self.next.clicked.connect(lambda: self.turn(1))
        self.info = QLabel("")
        export = QPushButton("Export CSV…")
        export.clicked.connect(self.choose_export)
        bar = QHBoxLayout()
        for w in (self.text, self.relationship, self.status, self.level_box, self.prev, self.info, self.next, export):
            bar.addWidget(w)
        self.model = DependencyModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_by)
        self.table.doubleClicked.connect(self.activate)
        self.evidence_view = QPlainTextEdit()
        self.evidence_view.setReadOnly(True)
        self.evidence_view.setPlaceholderText("Double-click a row: its source opens and its evidence shows here.")
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.evidence_view)
        split.setSizes([500, 140])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(split, 1)

    # ------------------------------------------------------------ loading
    def set_db(self, db: Path | None) -> None:
        self.db = db
        self.offset = 0
        self.reload()

    def apply_filters(self) -> None:
        rel = self.relationship.currentText()
        status = self.status.currentText()
        self.filters = DependencyFilter(text=self.text.text().strip() or None,
                                        relationships=() if rel.startswith("All") else (rel,),
                                        statuses=() if status.startswith("All") else (status,))
        self.level = LEVELS[self.level_box.currentIndex()][1]
        self.sort = "path" if self.level == "site" else "source"
        self.offset = 0
        self.reload()

    def reload(self) -> None:
        db = self.db
        if db is None:
            return
        filters, level, sort, desc, offset = self.filters, self.level, self.sort, self.descending, self.offset

        def work(q: GraphQuery) -> DependencyPage:
            if level == "site":
                return q.dependencies(filters, sort=sort, descending=desc, limit=PAGE_SIZE, offset=offset)
            return q.dependency_groups(level, filters, sort=sort, descending=desc, limit=PAGE_SIZE, offset=offset)

        self.runner.submit(db, "dependencies", work, self._show_page, self._error)

    def _show_page(self, page: DependencyPage) -> None:
        self.page = page
        self.model.set_rows(page.rows, SITE_COLUMNS if self.level == "site" else GROUP_COLUMNS)
        last = page.offset + len(page.rows)
        self.info.setText(f"{page.offset + 1 if page.rows else 0}–{last} of {page.total}")
        self.prev.setEnabled(page.offset > 0)
        self.next.setEnabled(last < page.total)

    def _error(self, message: str) -> None:
        self.evidence_view.setPlainText(f"error: {message}")

    def turn(self, step: int) -> None:
        self.offset = max(0, self.offset + step * PAGE_SIZE)
        self.reload()

    def sort_by(self, column: int) -> None:
        columns = SITE_COLUMNS if self.level == "site" else GROUP_COLUMNS
        key = columns[column][2]
        if key is None:
            return
        self.descending = not self.descending if key == self.sort else False
        self.sort, self.offset = key, 0
        self.reload()

    def show_occurrences(self, filters: DependencyFilter) -> None:
        """List the rows behind a graph link (the graph and the table open the same evidence)."""
        self.filters, self.level, self.sort, self.offset = filters, "site", "path", 0
        self.level_box.blockSignals(True)
        self.level_box.setCurrentIndex(0)
        self.level_box.blockSignals(False)
        self.reload()

    # ------------------------------------------------------- navigation
    def activate(self, index: QModelIndex) -> None:
        row = self.model.rows[index.row()]
        if isinstance(row, DependencyGroup):  # list the occurrences under the aggregated row
            self.filters, self.level, self.sort, self.offset = row.occurrences, "site", "path", 0
            self.level_box.blockSignals(True)
            self.level_box.setCurrentIndex(0)
            self.level_box.blockSignals(False)
            self.reload()
            return
        self.open_row(row)

    def open_row(self, row: DependencyRow) -> None:
        if self.db is None:
            return
        self.source_requested.emit(row.caller_file, row.line)
        self.runner.submit(self.db, "dependency_evidence", lambda q: q.dependency_evidence(row), self._show_evidence,
                           self._error)

    def _show_evidence(self, evidence: DependencyEvidence) -> None:
        self.evidence = evidence
        r = evidence.row
        lines = [f"{r.caller_file}:{r.line}:{r.col}  {r.relationship}  {r.caller} -> "
                 f"{r.target or ' | '.join(r.candidates) or r.target_text}  [{r.resolution}]"]
        lines += [f"{k}: {_cell(v)}" for k, v in evidence.evidence.items() if v not in (None, "")]
        self.evidence_view.setPlainText("\n".join(lines))

    # ------------------------------------------------------------ export
    def choose_export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export the dependency table", "dependencies.csv",
                                                    "CSV (*.csv)")
        if path:
            self.export_to(Path(path))

    def export_to(self, path: Path) -> None:
        """Every row of the current filter (all pages), written as CSV in the background."""
        if self.db is None:
            return
        filters = self.filters

        def work(q: GraphQuery) -> int:
            count = 0
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(EXPORT_COLUMNS)
                offset = 0
                while True:
                    page = q.dependencies(filters, limit=5000, offset=offset)
                    for r in page.rows:
                        writer.writerow([_cell(getattr(r, c)) for c in EXPORT_COLUMNS])
                    count += len(page.rows)
                    offset += len(page.rows)
                    if not page.rows or offset >= page.total:
                        return count

        self.runner.submit(self.db, "dependency_export", work,
                           lambda n: self.evidence_view.setPlainText(f"{n} row(s) exported to {path}"), self._error)
