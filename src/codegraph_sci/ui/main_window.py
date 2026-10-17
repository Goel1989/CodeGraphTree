"""Main window (§3.11): inventory, search, callers/callees, code inspector, file explorer, health."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QSettings, QSize, Qt
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
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
from codegraph_sci.ui import theme
from codegraph_sci.ui.graph3d_view import Graph3DView
from codegraph_sci.ui.highlighter import CodeHighlighter
from codegraph_sci.ui.models import CallTreeModel, FileTreeModel
from codegraph_sci.ui.shell import HeroCard, Popover, ResizeFrame, TitleBar
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
        self.banner.setStyleSheet(f"background:{theme.CURRENT_LINE};color:#FFB26B;")
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
            fmt.setBackground(QColor(theme.SITE_RESOLVED) if s.resolution in ("resolved", "out_of_scope")
                              else QColor(theme.SITE_UNRESOLVED))
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
            fmt.setBackground(QColor(theme.CURRENT_LINE))
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
        """Frameless shell: title bar; icon rail + view list; header band, hero card and details panel."""
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setStyleSheet(theme.STYLE)
        act_open = QAction("Open folder…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.choose_folder)
        self.addAction(act_open)

        # Widgets shared by several places (filters and analysis live in the hero card popovers).
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a routine, file, module…")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.run_search)
        self.btn_scan = QPushButton("Analyze")
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_scan)
        self.btn_cancel.setEnabled(False)
        self.hide_noise = QCheckBox("Hide utilities")
        self.hide_noise.setChecked(True)
        self.hide_noise.toggled.connect(self.refresh_symbol)
        self.min_conf = QComboBox()
        self.min_conf.addItems(["All confidences", "≥ heuristic", "≥ resolved", "exact"])
        self.min_conf.currentIndexChanged.connect(self.refresh_symbol)
        self.hide_ai = QCheckBox("Hide AI links")
        self.hide_ai.toggled.connect(self.refresh_symbol)
        self.hide_amb = QCheckBox("Hide ambiguous sites")
        self.hide_amb.toggled.connect(self.refresh_symbol)

        # Views of the details panel.
        self.inventory_table = QTableWidget(0, 5)
        self.inventory_table.setHorizontalHeaderLabels(["Language", "Files", "Lines", "Adapter", "Status"])
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.inventory_table.verticalHeader().hide()
        self.unknown_label = QLabel("")
        inv = QWidget()
        il = QVBoxLayout(inv)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(self.inventory_table)
        il.addWidget(self.unknown_label)
        self.all_subfolders = QCheckBox("Analyze all subfolders (ignore .gitignore and default exclusions such as "
                                        "build, .venv, node_modules)")
        self.all_subfolders.setToolTip("Version-control folders (.git, .hg, .svn) are never analyzed")
        self.all_subfolders.toggled.connect(self._on_all_subfolders)
        il.addWidget(self.all_subfolders)
        self.skipped_label = QLabel("")
        self.skipped_label.setWordWrap(True)
        self.skipped_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        il.addWidget(self.skipped_label)
        actions = QHBoxLayout()
        btn_force = QPushButton("Force language…")
        btn_force.clicked.connect(self.force_language)
        btn_ignore = QPushButton("Ignore extension…")
        btn_ignore.clicked.connect(self.ignore_extension)
        actions.addWidget(btn_force)
        actions.addWidget(btn_ignore)
        actions.addStretch()
        il.addLayout(actions)
        self.inventory_view = inv
        self.tree_box = QWidget()
        tl = QVBoxLayout(self.tree_box)
        tl.setContentsMargins(0, 0, 0, 0)
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
        self.graph_functions = Graph3DView(self.runner, files=False)
        self.graph_functions.node_selected.connect(self._graph_node_selected)
        self.graph_functions.sites_requested.connect(self.show_link_sites)
        self.graph_files = Graph3DView(self.runner, files=True)
        self.graph_files.node_selected.connect(self._graph_node_selected)
        self.graph_files.sites_requested.connect(self.show_link_sites)
        self.health_view = QPlainTextEdit()
        self.health_view.setReadOnly(True)
        self.groups: dict[str, tuple[str, str, list[tuple[str, QWidget]]]] = {
            "explore": ("Explore", "graph", [("Functions 3D", self.graph_functions), ("Files 3D", self.graph_files),
                                             ("Tree list", self.tree_box)]),
            "project": ("Project", "project", [("Inventory", inv), ("Analysis health", self.health_view)]),
        }
        self.views = QStackedWidget()
        for _label, _icon, items in self.groups.values():
            for _name, widget in items:
                self.views.addWidget(widget)

        # Title bar and resize frame.
        frame = ResizeFrame(self)
        self.resize_frame = frame
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # Left 1: icon rail.
        self.rail = QFrame()
        self.rail.setObjectName("Rail")
        self.rail.setFixedWidth(50)
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(5, 8, 5, 8)
        rl.setSpacing(6)
        self.rail_group = QButtonGroup(self)
        self.rail_group.setExclusive(True)
        self.rail_buttons: dict[str, QToolButton] = {}
        btn_open = self._rail_button("folder", "Open a source folder (Ctrl+O)")
        btn_open.clicked.connect(self.choose_folder)
        rl.addWidget(btn_open)
        for key, (label, icon_name, _items) in self.groups.items():
            b = self._rail_button(icon_name, label)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self.show_group(k))
            self.rail_group.addButton(b)
            self.rail_buttons[key] = b
            rl.addWidget(b)
        rl.addStretch()
        btn_about = self._rail_button("info", "About CodeGraph-Sci")
        btn_about.clicked.connect(self.show_about)
        rl.addWidget(btn_about)
        body.addWidget(self.rail)

        # Left 2: view list, search, files.
        nav = QFrame()
        nav.setObjectName("NavColumn")
        nav.setFixedWidth(270)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 10, 0, 0)
        nl.setSpacing(0)
        self.nav_title = QLabel("")
        self.nav_title.setContentsMargins(12, 0, 0, 6)
        nl.addWidget(self.nav_title)
        self.nav_box = QVBoxLayout()
        self.nav_box.setSpacing(0)
        nl.addLayout(self.nav_box)
        self.nav_buttons: list[QPushButton] = []
        search_box = QWidget()
        sl = QVBoxLayout(search_box)
        sl.setContentsMargins(8, 14, 8, 4)
        sl.addWidget(QLabel("SEARCH"))
        sl.addWidget(self.search)
        self.results = QListWidget()
        self.results.itemActivated.connect(self._result_activated)
        self.results.itemClicked.connect(self._result_activated)
        sl.addWidget(self.results)
        files_box = QWidget()
        fl = QVBoxLayout(files_box)
        fl.setContentsMargins(8, 8, 8, 8)
        fl.addWidget(QLabel("FILES"))
        self.files_view = QTreeView()
        self.files_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_view.doubleClicked.connect(self._file_activated)
        fl.addWidget(self.files_view)
        nav_split = QSplitter(Qt.Orientation.Vertical)
        nav_split.addWidget(search_box)
        nav_split.addWidget(files_box)
        nav_split.setSizes([260, 420])
        nl.addWidget(nav_split, 1)
        body.addWidget(nav)

        # Centre: header band, hero card, details panel.
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        header = QFrame()
        header.setObjectName("HeaderBand")
        header.setFixedHeight(40)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        self.header_title = QLabel("")
        self.header_info = QLabel("No project open.")
        self.header_info.setStyleSheet(f"color: {theme.MUTED}; font-size: 9pt; font-weight: normal;")
        hl.addWidget(self.header_title)
        hl.addStretch()
        hl.addWidget(self.header_info)
        cl.addWidget(header)
        hero_box = QWidget()
        hbl = QVBoxLayout(hero_box)
        hbl.setContentsMargins(12, 12, 12, 10)
        self.hero = HeroCard()
        self.summary = self.hero.summary
        hbl.addWidget(self.hero)
        cl.addWidget(hero_box)

        self.inspector = Inspector(self)
        self.inspector.reanalyse.clicked.connect(self.start_scan)
        self.links_tabs = QTabWidget()
        self.callers_tree = self._links_tree()
        self.callees_tree = self._links_tree()
        self.links_tabs.addTab(self.callers_tree, "Callers")
        self.links_tabs.addTab(self.callees_tree, "Callees")
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.inspector)
        right.addWidget(self.links_tabs)
        right.setSizes([480, 300])
        details = QSplitter(Qt.Orientation.Horizontal)
        details.addWidget(self.views)
        details.addWidget(right)
        details.setSizes([820, 560])
        details_box = QWidget()
        dl = QVBoxLayout(details_box)
        dl.setContentsMargins(12, 0, 12, 12)
        dl.addWidget(details)
        cl.addWidget(details_box, 1)
        body.addWidget(centre, 1)
        self.setCentralWidget(frame)

        self._build_popovers()
        self.hero.badge_callers.clicked.connect(lambda: self.links_tabs.setCurrentIndex(0))
        self.hero.badge_callees.clicked.connect(lambda: self.links_tabs.setCurrentIndex(1))
        self.hero.btn_filters.clicked.connect(lambda: self.filters_popover.show_under(self.hero.btn_filters))
        self.hero.btn_analysis.clicked.connect(lambda: self.analysis_popover.show_under(self.hero.btn_analysis))
        self.hero.btn_view.clicked.connect(lambda: self.view_popover.show_under(self.hero.btn_view))

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.status_label = QLabel("No project open.")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.show_view(self.graph_functions)

    def _rail_button(self, icon_name: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setIcon(theme.icon(icon_name))
        b.setIconSize(QSize(22, 22))
        b.setFixedSize(40, 40)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return b

    def _build_popovers(self) -> None:
        self.filters_popover = Popover(self, "Filters", columns=2)
        for w in (self.hide_noise, self.hide_ai, self.hide_amb, self.min_conf):
            self.filters_popover.add(w)
        self.analysis_popover = Popover(self, "Analysis", columns=2)
        btn_force = QPushButton("Force language…")
        btn_force.clicked.connect(self.force_language)
        btn_ignore = QPushButton("Ignore extension…")
        btn_ignore.clicked.connect(self.ignore_extension)
        btn_open = QPushButton("Open folder…")
        btn_open.clicked.connect(self.choose_folder)
        for w in (self.btn_scan, self.btn_cancel, btn_force, btn_ignore, btn_open):
            self.analysis_popover.add(w)
        self.view_popover = Popover(self, "Show in", columns=3)
        for label, widget in self.groups["explore"][2]:
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, w=widget: self._show_from_popover(w))
            self.view_popover.add(b)

    def _show_from_popover(self, widget: QWidget) -> None:
        self.view_popover.close()
        self.show_view(widget)

    def show_group(self, key: str, current: QWidget | None = None) -> None:
        """Select a rail group: rebuild the view list, show ``current`` (or the group's first view)."""
        label, _icon, items = self.groups[key]
        self.rail_buttons[key].setChecked(True)
        self.nav_title.setText(label.upper())
        for b in self.nav_buttons:
            self.nav_box.removeWidget(b)
            b.deleteLater()
        self.nav_buttons = []
        for name, widget in items:
            b = QPushButton(name)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, w=widget: self.show_view(w))
            self.nav_box.addWidget(b)
            self.nav_buttons.append(b)
        self._activate_view(key, current if current is not None else items[0][1])

    def show_view(self, widget: QWidget) -> None:
        """Show one view of the details panel; the rail and the view list follow."""
        for key, (_label, _icon, items) in self.groups.items():
            if any(w is widget for _n, w in items):
                if self.rail_buttons[key].isChecked() and self.nav_buttons:
                    self._activate_view(key, widget)
                else:
                    self.show_group(key, widget)
                return

    def _activate_view(self, key: str, widget: QWidget) -> None:
        for b, (name, w) in zip(self.nav_buttons, self.groups[key][2], strict=True):
            b.setChecked(w is widget)
            if w is widget:
                self.header_title.setText(name.upper())
        self.views.setCurrentWidget(widget)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "resize_frame"):
            self.resize_frame.update_margins()
            self.title_bar.btn_max.setText("❐" if self.isMaximized() else "□")
        super().changeEvent(event)

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
        if self.process.running():  # the inventory or analysis of the previous project is not wanted any more
            self.pending_scan = False
            self.process.cancel(wait=True)
        self.project = open_project(root, project_folder)
        self.settings.setValue("last_project", str(root))
        self.setWindowTitle(f"CodeGraph-Sci — {root}")
        self.title_bar.title.setText(f"CodeGraph-Sci — {root}")
        self.header_info.setText(str(root))
        self.hero.title.setText(root.name or str(root))
        self.hero.subtitle.setText("Select a routine: search, file explorer or a click in a graph.")
        self.hero.summary.setText("")
        self.hero.set_counts(None, None)
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
        self.graph_functions.load_overview(db)
        self.graph_files.hide_noise = self.hide_noise.isChecked()
        self.graph_files.load_overview(db)

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
    def _on_all_subfolders(self, checked: bool) -> None:
        if self.project is None:
            return
        self.status_label.setText("Analyzing every sub-folder…" if checked else "Applying folder exclusions…")
        self._profile_change(["all-subfolders", str(self.project.root), "on" if checked else "off"])

    def _show_skipped(self, skipped: list[dict[str, Any]], all_subfolders: bool,
                      total: dict[str, Any] | None = None) -> None:
        """Folders left out of the analysis (largest first) and the state of the option."""
        self.all_subfolders.blockSignals(True)
        self.all_subfolders.setChecked(all_subfolders)
        self.all_subfolders.blockSignals(False)
        if not skipped:
            self.skipped_label.setText("No folder skipped: every sub-folder is analyzed.")
            return
        entries = int(total["entries"]) if total else len(skipped)
        files = int(total["files"]) if total else sum(int(s["files"]) for s in skipped)
        lines = [f"Skipped: {entries} folder(s) or file(s), {files} file(s) in all —"]
        lines += [f"{s['path']} ({s['reason']}, {s['files']} file(s))" for s in skipped[:12]]
        if entries > 12:
            lines.append(f"… and {entries - 12} more")
        self.skipped_label.setText("  ".join(lines[:1]) + " " + " · ".join(lines[1:]))

    def _show_raw_inventory(self, data: dict[str, Any]) -> None:
        cov = data.get("coverage", {})
        self.inventory_table.setRowCount(len(cov))
        for i, (lang, c) in enumerate(sorted(cov.items())):
            for j, v in enumerate([lang, c["files"], c["lines"], c["adapter"], ", ".join(c["variants"])]):
                self.inventory_table.setItem(i, j, QTableWidgetItem(str(v)))
        unknown = data.get("unknown_groups", {})
        self.unknown_label.setText("Unrecognized files: " + (", ".join(
            f"{k} ({v['files']})" for k, v in unknown.items()) or "none"))
        self._show_skipped(list(data.get("skipped_dirs", [])), self.all_subfolders.isChecked())

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
        header = self.files_view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.files_view.setColumnHidden(1, True)  # the language is the colour of the name (narrow column)

    def _show_health(self, data: tuple[ScanHealth, list[Any]]) -> None:
        health, groups = data
        lines = ["Files: " + ", ".join(f"{k} {v}" for k, v in health.files_by_status.items()),
                 "Call sites: " + ", ".join(f"{k} {v}" for k, v in health.sites_by_resolution.items()),
                 f"Unresolved rate: {health.unresolved_rate:.2%}    ambiguous sites: {health.ambiguous}", ""]
        last = health.last_scan
        if last:
            lines.append(f"Last analysis: {last['finished_at']} — profile v{last['profile_version']} — "
                         f"{last['stats'].get('seconds', '?')} s")
            stats = last["stats"]
            self._show_skipped(list(stats.get("skipped_dirs", [])), bool(stats.get("all_subfolders", False)),
                               stats.get("skipped_total"))
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
        open_sites = [f"{n} {what}" for n, what in ((callees.unresolved_sites, "unresolved"),
                                                    (callees.ambiguous_sites, "ambiguous")) if n]
        not_counted = f" — not counted: {', '.join(open_sites)} call site(s)" if open_sites else ""
        where = f"{node.file}:{node.line}" if node.file else "outside the repository"
        self.hero.title.setText(node.display_name)
        self.hero.subtitle.setText(f"{node.kind} · {node.lang or '-'} · {node.uid} · {where}")
        self.hero.set_counts(callers.count, callees.count)
        self.summary.setText(f"Called by <b>{callers.count}</b> routine(s) in <b>{callers.file_count}</b> "
                             f"file(s){hidden} — calls {callees.count} routine(s) — "
                             f"impact: {node.impact_size} transitive caller(s){not_counted}")
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


