"""Main window (§3.11): inventory, search, callers/callees, code inspector, file explorer, health."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from codegraph_sci.core.paths import data_dir
from codegraph_sci.core.project import Project, open_project
from codegraph_sci.core.versions import APP_VERSION
from codegraph_sci.query.types import CallerReport, Direction, NodeSummary, ScanHealth, SourceExcerpt
from codegraph_sci.ui.graph3d_view import Graph3DView
from codegraph_sci.ui.highlighter import CodeHighlighter
from codegraph_sci.ui.models import CallTreeModel, FileTreeModel
from codegraph_sci.ui.workers import CgsProcess, QueryRunner

ABOUT_TEXT = (
    f"<h3>CodeGraph-Sci {APP_VERSION}</h3>"
    "<p>Call-graph explorer for multi-language scientific code "
    "(Fortran, Python, C, C++).</p>"
    "<p>100% offline desktop application.</p>"
    "<p>Public source code under PolyForm Noncommercial 1.0.0 license; "
    "separate commercial license.</p>"
)
SITE_ROLE = Qt.ItemDataRole.UserRole + 1
UID_ROLE = Qt.ItemDataRole.UserRole + 2


class Inspector(QWidget):
    """Read-only source, coloured, call lines highlighted; banner when the file changed."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel("No file")
        self.banner = QWidget()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(6, 2, 6, 2)
        self.banner_label = QLabel("This file has changed since the last analysis.")
        self.reanalyse = QPushButton("Re-analyze")
        bl.addWidget(self.banner_label)
        bl.addStretch()
        bl.addWidget(self.reanalyse)
        self.banner.setStyleSheet("background:#fff3cd;color:#664d03;")
        self.banner.hide()
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.editor.mouseDoubleClickEvent = self._double_click  # type: ignore[method-assign]
        layout.addWidget(self.title)
        layout.addWidget(self.banner)
        layout.addWidget(self.editor)
        self.path: str | None = None
        self.sites: list[Any] = []
        self.highlighter: CodeHighlighter | None = None

    def show_source(self, excerpt: SourceExcerpt, lang: str | None, line: int | None, sites: list[Any]) -> None:
        self.path = excerpt.path
        self.sites = sites
        self.title.setText(f"{excerpt.path}" + (" (missing)" if excerpt.missing else ""))
        self.banner.setVisible(excerpt.stale)
        self.editor.setPlainText("\n".join(excerpt.lines))
        self.highlighter = CodeHighlighter(self.editor.document(), lang)
        self.highlighter.fixed_form = excerpt.path.lower().endswith((".f", ".for", ".f77", ".ftn"))
        self.highlighter.rehighlight()
        selections = []
        for s in sites:
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#e8f0fe") if s.resolution in ("resolved", "out_of_scope") else QColor("#fde8e8"))
            sel.format = fmt  # type: ignore[attr-defined]
            block = self.editor.document().findBlockByNumber(s.line - 1)
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + max(0, s.col - 1))
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(s.target_text))
            sel.cursor = cursor  # type: ignore[attr-defined]
            selections.append(sel)
        if line:
            block = self.editor.document().findBlockByNumber(line - 1)
            cursor = QTextCursor(block)
            sel = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#fff59d"))
            fmt.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            sel.format = fmt  # type: ignore[attr-defined]
            sel.cursor = cursor  # type: ignore[attr-defined]
            selections.insert(0, sel)
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()
        self.editor.setExtraSelections(selections)

    def site_at(self, line: int, col: int) -> Any | None:
        best = None
        for s in self.sites:
            if s.line == line and s.col <= col <= s.col + len(s.target_text):
                return s
            if s.line == line and best is None:
                best = s
        return best

    def _double_click(self, event: Any) -> None:
        cursor = self.editor.cursorForPosition(event.position().toPoint())
        site = self.site_at(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)
        if site is not None and site.dst:
            self.window.select_symbol(site.dst)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CodeGraph-Sci")
        self.resize(1400, 900)
        self.settings = QSettings(str(data_dir() / "settings.ini"), QSettings.Format.IniFormat)
        self.project: Project | None = None
        self.runner = QueryRunner(self)
        self.process = CgsProcess(self)
        self.process.event.connect(self._on_progress)
        self.process.finished.connect(self._on_process_finished)
        self.pending_scan = False
        self.current: NodeSummary | None = None
        self.tree_model: CallTreeModel | None = None
        self._from_graph = False
        self._build_ui()
        last = self.settings.value("last_project")
        if isinstance(last, str) and Path(last).is_dir():
            self.open_project_folder(Path(last))

    # ------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        act_open = QAction("Open folder…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.choose_folder)
        tb.addAction(act_open)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a routine, file, module…")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.run_search)
        self.search.setMinimumWidth(320)
        tb.addWidget(self.search)
        self.btn_scan = QPushButton("Analyze")
        self.btn_scan.clicked.connect(self.start_scan)
        tb.addWidget(self.btn_scan)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_scan)
        self.btn_cancel.setEnabled(False)
        tb.addWidget(self.btn_cancel)
        tb.addSeparator()
        self.hide_noise = QCheckBox("Hide utilities")
        self.hide_noise.setChecked(True)
        self.hide_noise.toggled.connect(self.refresh_symbol)
        tb.addWidget(self.hide_noise)
        self.min_conf = QComboBox()
        self.min_conf.addItems(["All confidences", "≥ heuristic", "≥ resolved", "exact"])
        self.min_conf.currentIndexChanged.connect(self.refresh_symbol)
        tb.addWidget(self.min_conf)
        self.hide_ai = QCheckBox("Hide AI links")
        self.hide_ai.toggled.connect(self.refresh_symbol)
        tb.addWidget(self.hide_ai)
        self.hide_amb = QCheckBox("Hide ambiguous sites")
        self.hide_amb.toggled.connect(self.refresh_symbol)
        tb.addWidget(self.hide_amb)

        help_menu = self.menuBar().addMenu("&Help")
        about = help_menu.addAction("&About CodeGraph-Sci")
        about.triggered.connect(self.show_about)

        # Left: file explorer.
        self.files_view = QTreeView()
        self.files_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_view.doubleClicked.connect(self._file_activated)
        dock = QDockWidget("Files", self)
        dock.setObjectName("files")
        dock.setWidget(self.files_view)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.results = QListWidget()
        self.results.itemActivated.connect(self._result_activated)
        self.results.itemClicked.connect(self._result_activated)
        rdock = QDockWidget("Search results", self)
        rdock.setObjectName("results")
        rdock.setWidget(self.results)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, rdock)

        # Centre: tabs.
        self.tabs = QTabWidget()
        self.inventory_table = QTableWidget(0, 5)
        self.inventory_table.setHorizontalHeaderLabels(["Language", "Files", "Lines", "Adapter", "Status"])
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.unknown_label = QLabel("")
        inv = QWidget()
        il = QVBoxLayout(inv)
        il.addWidget(self.inventory_table)
        il.addWidget(self.unknown_label)
        actions = QHBoxLayout()
        btn_force = QPushButton("Force language…")
        btn_force.clicked.connect(self.force_language)
        btn_ignore = QPushButton("Ignore extension…")
        btn_ignore.clicked.connect(self.ignore_extension)
        actions.addWidget(btn_force)
        actions.addWidget(btn_ignore)
        actions.addStretch()
        il.addLayout(actions)
        self.tabs.addTab(inv, "Inventory")
        tree_box = QWidget()
        tl = QVBoxLayout(tree_box)
        row = QHBoxLayout()
        self.tree_direction = QComboBox()
        self.tree_direction.addItems(["Callees", "Callers"])
        self.tree_direction.currentIndexChanged.connect(self._rebuild_tree)
        row.addWidget(QLabel("Direction:"))
        row.addWidget(self.tree_direction)
        row.addStretch()
        tl.addLayout(row)
        self.tree_view = QTreeView()
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.doubleClicked.connect(self._tree_activated)
        tl.addWidget(self.tree_view)
        self.tabs.addTab(tree_box, "Tree list")
        self.graph_functions = Graph3DView(self.runner, files=False)
        self.graph_functions.node_selected.connect(self._graph_node_selected)
        self.graph_functions.sites_requested.connect(self.show_link_sites)
        self.tabs.addTab(self.graph_functions, "Functions 3D")
        self.graph_files = Graph3DView(self.runner, files=True)
        self.graph_files.node_selected.connect(self._graph_node_selected)
        self.graph_files.sites_requested.connect(self.show_link_sites)
        self.tabs.addTab(self.graph_files, "Files 3D")
        self.health_view = QPlainTextEdit()
        self.health_view.setReadOnly(True)
        self.tabs.addTab(self.health_view, "Analysis health")

        # Right: inspector + callers/callees.
        self.inspector = Inspector(self)
        self.inspector.reanalyse.clicked.connect(self.start_scan)
        self.links_tabs = QTabWidget()
        self.callers_tree = self._links_tree()
        self.callees_tree = self._links_tree()
        self.links_tabs.addTab(self.callers_tree, "Callers")
        self.links_tabs.addTab(self.callees_tree, "Callees")
        self.summary = QLabel("Select a routine.")
        self.summary.setWordWrap(True)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rsplit = QSplitter(Qt.Orientation.Vertical)
        rsplit.addWidget(self.inspector)
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.summary)
        ll.addWidget(self.links_tabs)
        rsplit.addWidget(lw)
        rl.addWidget(rsplit)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.tabs)
        split.addWidget(right)
        split.setSizes([600, 700])
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.status_label = QLabel("No project open.")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    def _links_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(["Routine / site", "Location", "Confidence"])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.itemDoubleClicked.connect(self._link_activated)
        tree.setSortingEnabled(True)
        return tree

    # ------------------------------------------------------------ project
    def show_about(self) -> None:
        QMessageBox.about(self, "About CodeGraph-Sci", ABOUT_TEXT)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Source code folder")
        if folder:
            self.open_project_folder(Path(folder))

    @property
    def db(self) -> Path | None:
        if self.project is not None and self.project.db_path.is_file():
            return self.project.db_path
        return None

    def open_project_folder(self, root: Path, project_folder: Path | None = None) -> None:
        self.project = open_project(root, project_folder)
        self.settings.setValue("last_project", str(root))
        self.setWindowTitle(f"CodeGraph-Sci — {root}")
        if self.db is not None:
            self.load_project()
        else:
            self.status_label.setText("Language inventory…")
            self.pending_scan = True
            self._run_cgs(["inventory", str(root), "--project", str(self.project.folder), "--json"])

    def load_project(self) -> None:
        db = self.db
        if db is None:
            return
        self.runner.submit(db, "inventory", lambda q: q.inventory(), self._show_inventory)
        self.runner.submit(db, "files", lambda q: q.files(), self._show_files)
        self.runner.submit(db, "health", lambda q: (q.scan_health(), q.unresolved(include_ambiguous=True, limit=30)),
                           self._show_health)
        self.graph_functions.hide_noise = self.hide_noise.isChecked()
        self.graph_functions.load_from_main(db)
        self.graph_files.hide_noise = self.hide_noise.isChecked()
        self.graph_files.load_from_main(db)

    # ------------------------------------------------------------ analysis
    def _run_cgs(self, args: list[str]) -> None:
        self.btn_scan.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.process.start(args)

    def start_scan(self) -> None:
        if self.project is None or self.process.running():
            return
        self.status_label.setText("Analysis in progress…")
        self._run_cgs(["scan", str(self.project.root), "--project", str(self.project.folder), "--progress", "json"])

    def cancel_scan(self) -> None:
        self.pending_scan = False
        self.process.cancel()
        self.status_label.setText("Analysis cancelled.")

    def _on_progress(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "extract" and event.get("total"):
            self.progress.setRange(0, int(event["total"]))
            self.progress.setValue(int(event.get("done", 0)))
            self.status_label.setText(f"Extraction: {event.get('done')}/{event.get('total')} files")
        elif kind in ("link", "index", "write"):
            self.progress.setRange(0, 0)
            self.status_label.setText({"link": "Linking…", "index": "Indexing…", "write": "Writing…"}[str(kind)])
        elif kind == "done":
            self.status_label.setText(f"Analysis complete: {event.get('nodes')} symbols, "
                                      f"{event.get('call_sites')} sites, {event.get('seconds')} s")
        elif "files" in event and isinstance(event["files"], dict):  # cgs inventory --json
            self._show_raw_inventory(event)

    def _on_process_finished(self, code: int, stderr: str) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.hide()
        if code != 0:
            if self.pending_scan or "Traceback" in stderr:
                QMessageBox.warning(self, "Analysis", f"Command failed (code {code}).\n\n{stderr[-1500:]}")
            self.pending_scan = False
            return
        if self.pending_scan:
            self.pending_scan = False
            self.start_scan()
            return
        self.load_project()
        self.refresh_symbol()

    def force_language(self) -> None:
        if self.project is None:
            return
        glob, ok = QInputDialog.getText(self, "Force language", "Files (pattern, e.g. legacy/*.inc):")
        if not ok or not glob.strip():
            return
        lang, ok = QInputDialog.getItem(self, "Force language", "Language:", ["fortran", "c", "cpp", "python"],
                                        0, False)
        if ok:
            self._profile_change(["set-language", str(self.project.root), glob.strip(), lang])

    def ignore_extension(self) -> None:
        if self.project is None:
            return
        ext, ok = QInputDialog.getText(self, "Ignore extension", "Extension (e.g. .dat):")
        if ok and ext.strip():
            self._profile_change(["ignore", str(self.project.root), ext.strip()])

    def _profile_change(self, args: list[str]) -> None:
        """Written in the profile by ``cgs profile`` (new version), then re-analysed."""
        assert self.project is not None
        self.pending_scan = True
        self.status_label.setText("Updating analysis profile…")
        self._run_cgs(["profile", *args, "--project", str(self.project.folder)])

    # ------------------------------------------------------------- display
    def _show_raw_inventory(self, data: dict[str, Any]) -> None:
        cov = data.get("coverage", {})
        self.inventory_table.setRowCount(len(cov))
        for i, (lang, c) in enumerate(sorted(cov.items())):
            for j, v in enumerate([lang, c["files"], c["lines"], c["adapter"], ", ".join(c["variants"])]):
                self.inventory_table.setItem(i, j, QTableWidgetItem(str(v)))
        unknown = data.get("unknown_groups", {})
        self.unknown_label.setText("Unrecognized files: " + (", ".join(
            f"{k} ({v['files']})" for k, v in unknown.items()) or "none"))

    def _show_inventory(self, report: Any) -> None:
        self.inventory_table.setRowCount(len(report.languages))
        for i, line in enumerate(report.languages):
            states = ", ".join(f"{k} {v}" for k, v in line.statuses.items())
            for j, v in enumerate([line.lang, line.files, line.lines, line.adapter or "none", states]):
                self.inventory_table.setItem(i, j, QTableWidgetItem(str(v)))
        self.unknown_label.setText("Unrecognized files: " + (", ".join(
            f"{k} ({v})" for k, v in report.unknown_groups.items()) or "none"))

    def _show_files(self, files: list[dict[str, Any]]) -> None:
        self.files_model = FileTreeModel(files)
        self.files_view.setModel(self.files_model)
        self.files_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _show_health(self, data: tuple[ScanHealth, list[Any]]) -> None:
        health, groups = data
        lines = ["Files: " + ", ".join(f"{k} {v}" for k, v in health.files_by_status.items()),
                 "Call sites: " + ", ".join(f"{k} {v}" for k, v in health.sites_by_resolution.items()),
                 f"Unresolved rate: {health.unresolved_rate:.2%}    ambiguous sites: {health.ambiguous}", ""]
        last = health.last_scan
        if last:
            lines.append(f"Last analysis: {last['finished_at']} — profile v{last['profile_version']} — "
                         f"{last['stats'].get('seconds', '?')} s")
        lines += ["", "Unresolved or ambiguous sites, by pattern:"]
        lines += [f"  {g.count:>6}  {g.lang:<8} {g.resolution:<10} {g.pattern}" for g in groups]
        if health.failures:
            lines += ["", "Failed or fallback files:"]
            lines += [f"  {f['status']:<9} {f['path']}" for f in health.failures[:50]]
        self.health_view.setPlainText("\n".join(lines))
        self.status_label.setText(f"Project: {self.project.root if self.project else ''} — "
                                  f"unresolved {health.unresolved_rate:.1%}, ambiguous {health.ambiguous}")

    # -------------------------------------------------------------- search
    def run_search(self) -> None:
        text = self.search.text().strip()
        db = self.db
        if not text or db is None:
            return
        self.runner.submit(db, "search", lambda q: q.find(text, limit=100), self._show_results)

    def _show_results(self, results: list[NodeSummary]) -> None:
        self.results.clear()
        for r in results:
            item = QListWidgetItem(f"{r.display_name}   [{r.kind}, {r.lang or '-'}]   {r.file or ''}:{r.line or ''}")
            item.setData(UID_ROLE, r.uid)
            item.setToolTip(r.uid)
            self.results.addItem(item)
        if len(results) == 1 or (results and results[0].display_name.lower() == self.search.text().strip().lower()):
            self.select_symbol(results[0].uid)

    def _result_activated(self, item: QListWidgetItem) -> None:
        uid = item.data(UID_ROLE)
        if isinstance(uid, str) and uid.startswith("site:"):
            path, line = uid[5:].rsplit(":", 1)
            self.show_file(path, int(line))
        elif uid:
            self.select_symbol(str(uid))

    # -------------------------------------------------------- selection
    def select_symbol(self, uid: str) -> None:
        db = self.db
        if db is None:
            return
        if uid.startswith("file:"):
            path = uid[5:]
            self.show_file(path, None)
            if not self._from_graph:
                self.graph_files.set_root(db, uid)
            self._from_graph = False
            return
        hide = self.hide_noise.isChecked()

        def work(q: Any) -> tuple[Any, CallerReport, CallerReport]:
            return q.node(uid), q.callers(uid, hide_noise=hide), q.callees(uid, hide_noise=hide)

        self.runner.submit(db, "symbol", work, self._show_symbol, self._error)

    def refresh_symbol(self) -> None:
        if self.current is not None:
            self.select_symbol(self.current.uid)

    def _keep_site(self, site: Any) -> bool:
        level = self.min_conf.currentIndex()
        rank = {"exact": 3, "resolved": 2, "heuristic": 1, "ambiguous": 0}.get(site.confidence, 0)
        if rank < level:
            return False
        if self.hide_ai.isChecked() and ("@r-" in site.origin or site.origin.startswith("ai")):
            return False
        return not (self.hide_amb.isChecked() and site.resolution == "ambiguous")

    def _fill_links(self, tree: QTreeWidget, report: CallerReport) -> int:
        tree.clear()
        tree.setSortingEnabled(False)
        count = 0
        for item in report.items:
            sites = [s for s in item.sites if self._keep_site(s)]
            if not sites:
                continue
            count += 1
            n = item.node
            top = QTreeWidgetItem([f"{n.display_name}  ({len(sites)})", f"{n.file or n.uid}:{n.line or ''}",
                                   min((s.confidence for s in sites), key=lambda c: -["ambiguous", "heuristic",
                                                                                       "resolved", "exact"].index(c))])
            top.setData(0, UID_ROLE, n.uid)
            top.setToolTip(0, n.uid)
            for s in sites:
                label = s.target_text + (f"   if {s.condition}" if s.condition else "")
                child = QTreeWidgetItem([label, f"{s.file}:{s.line}:{s.col}", f"{s.confidence} · {s.origin}"])
                child.setData(0, SITE_ROLE, json.dumps({"file": s.file, "line": s.line}))
                top.addChild(child)
            tree.addTopLevelItem(top)
        tree.setSortingEnabled(True)
        tree.sortItems(0, Qt.SortOrder.AscendingOrder)
        return count

    def _show_symbol(self, data: tuple[Any, CallerReport, CallerReport]) -> None:
        node, callers, callees = data
        self.current = node
        n_callers = self._fill_links(self.callers_tree, callers)
        n_callees = self._fill_links(self.callees_tree, callees)
        self.links_tabs.setTabText(0, f"Callers ({n_callers})")
        self.links_tabs.setTabText(1, f"Callees ({n_callees})")
        hidden = f" (+{callers.hidden_noise} utilities hidden)" if callers.hidden_noise else ""
        self.summary.setText(f"<b>{node.display_name}</b> <span style='color:#666'>{node.uid}</span><br>"
                             f"Called by <b>{callers.count}</b> routine(s) in <b>{callers.file_count}</b> "
                             f"file(s){hidden} — calls {callees.count} routine(s) — "
                             f"impact: {node.impact_size} transitive caller(s)")
        if node.file:
            self.show_file(node.file, node.line, node.lang)
        self._rebuild_tree()
        if self.db is not None and not self._from_graph:
            self.graph_functions.hide_noise = self.hide_noise.isChecked()
            self.graph_functions.set_root(self.db, node.uid)
            if node.file:
                self.graph_files.set_root(self.db, f"file:{node.file}")
        self._from_graph = False

    def show_file(self, path: str, line: int | None, lang: str | None = None) -> None:
        db = self.db
        if db is None:
            return

        def work(q: Any) -> tuple[SourceExcerpt, list[Any], str | None]:
            excerpt = q.source(f"file:{path}", 1, 10**7)
            row = q.con.execute("SELECT lang FROM files WHERE path = ?", (path,)).fetchone()
            return excerpt, q.sites_in_file(path), row[0] if row else lang

        self.runner.submit(db, "source", work,
                           lambda d: self.inspector.show_source(d[0], d[2], line, d[1]), self._error)

    def _rebuild_tree(self) -> None:
        if self.current is None or self.db is None or self.current.kind == "file":
            return
        if self.tree_model is not None:
            self.tree_model.close()
        direction = Direction.CALLEES if self.tree_direction.currentIndex() == 0 else Direction.CALLERS
        self.tree_model = CallTreeModel(self.db, self.current.uid, direction, hide_noise=self.hide_noise.isChecked())
        self.tree_view.setModel(self.tree_model)
        self.tree_view.expand(self.tree_model.index(0, 0))
        self.tree_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _tree_activated(self, index: Any) -> None:
        if self.tree_model is None:
            return
        uid = self.tree_model.node_uid(index)
        if uid is None:
            self.tree_model.expand_more(index)
        elif uid != (self.current.uid if self.current else None):
            self.select_symbol(uid)

    def _link_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        site = item.data(0, SITE_ROLE)
        if site:
            s = json.loads(site)
            self.show_file(s["file"], s["line"])
            return
        uid = item.data(0, UID_ROLE)
        if uid:
            self.select_symbol(str(uid))

    def _file_activated(self, index: Any) -> None:
        path = index.siblingAtColumn(0).data(FileTreeModel.PATH_ROLE)
        if isinstance(path, str) and not path.startswith("dir:"):
            self.show_file(path, None)
            if self.db is not None:
                self.graph_files.set_root(self.db, f"file:{path}")

    # ------------------------------------------------------------ 3D graphs
    def _graph_node_selected(self, uid: str) -> None:
        self._from_graph = True  # keep the drawn graph: only the panels follow the selection
        self.select_symbol(uid)

    def show_link_sites(self, src: str, dst: str) -> None:
        """Detailed calls behind a drawn link (double-click on an edge: ``src`` calls ``dst``)."""
        db = self.db
        if db is None or src.startswith("dir:") or dst.startswith("dir:"):
            return
        self.runner.submit(db, "link-sites", lambda q: q.call_sites(src, dst), self._show_link_sites, self._error)

    def _show_link_sites(self, sites: list[Any]) -> None:
        self.results.clear()
        for s in sites:
            item = QListWidgetItem(f"{s.file}:{s.line}:{s.col}   {s.target_text}   [{s.confidence}, {s.origin}]")
            item.setData(UID_ROLE, f"site:{s.file}:{s.line}")
            self.results.addItem(item)
        self.status_label.setText(f"{len(sites)} call(s) behind this link — see 'Search results'")

    def _error(self, message: str) -> None:
        self.status_label.setText(message.splitlines()[0])

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self.runner.cancel_all()
        super().closeEvent(event)


