"""Main window (§3.11): files and their dependencies, folders, dependency table, inventory, code inspector, health.

Files are the units of navigation (D40): the side panel shows the files depending on the selected file (Dependents),
the files it depends on (Dependencies) and the files a change may affect (Impact).
"""

from __future__ import annotations

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
from codegraph_sci.query.types import (
    RELATIONSHIPS,
    FileDependency,
    FileImpact,
    FileRelation,
    NodeSummary,
    ScanHealth,
    SourceExcerpt,
)
from codegraph_sci.ui import theme
from codegraph_sci.ui.deps_view import DependencyView
from codegraph_sci.ui.graph3d_view import Graph3DView
from codegraph_sci.ui.highlighter import CodeHighlighter
from codegraph_sci.ui.models import FileTreeModel
from codegraph_sci.ui.shell import HeroCard, Popover, ResizeFrame, TitleBar, elastic
from codegraph_sci.ui.workers import CgsProcess, QueryRunner

ABOUT_TEXT = (
    f"<h3>CodeGraph-Sci {APP_VERSION}</h3>"
    "<p>Dependency explorer for multi-language scientific code "
    "(Fortran, Python, C, C++): which files depend on which, and why.</p>"
    "<p>Offline desktop application: no cloud service is needed and analysed source code is never sent to a "
    "remote service.</p>"
    "<p>Open source software under the GNU GPL, version 3 or later (no warranty); "
    "a commercial license is also available.</p>"
)
PATH_ROLE = Qt.ItemDataRole.UserRole + 1  # a file of the panel: double click selects it
FILTER_ROLE = Qt.ItemDataRole.UserRole + 2  # a relationship of the panel: double click lists its occurrences
LINE_ROLE = Qt.ItemDataRole.UserRole + 3
RESOLUTION_FILTERS = ["All resolutions", "confirmed", "possible"]
MAX_CYCLES_SHOWN = 50


class Inspector(QWidget):
    """Read-only source, coloured, reference lines highlighted; banner when the file changed."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = elastic(QLabel("No file"), wrap=False)
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

    def clear(self) -> None:
        self.path = None
        self.sites = []
        self.title.setText("No file")
        self.banner.hide()
        self.editor.clear()
        self.editor.setExtraSelections([])

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
        """A reference in the source: open the file that defines its target."""
        cursor = self.editor.cursorForPosition(event.position().toPoint())
        site = self.site_at(cursor.blockNumber() + 1, cursor.positionInBlock() + 1)
        if site is not None and site.dst:
            self.window.open_target(site.dst)


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
        self._cancelled = False
        self._running = ""  # what the running command does (for its failure message)
        self.current_file: str | None = None
        self.relations: tuple[list[FileRelation], list[FileRelation], FileImpact] | None = None
        self.relations_loaded = False
        self.file_cycles: list[list[str]] | None = None
        self.file_langs: dict[str, str | None] = {}
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
        for text, shortcut, slot in (("Search", "Ctrl+F", self._focus_search), ("Analyze", "F5", self.start_scan),
                                     ("Filters", "Ctrl+Shift+F",
                                      lambda: self.filters_popover.show_under(self.hero.btn_filters)),
                                     ("Cancel the analysis", "Shift+F5", self.cancel_scan),
                                     ("Explore views", "Alt+1", lambda: self.show_group("explore")),
                                     ("Project views", "Alt+2", lambda: self.show_group("project"))):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)

        # Widgets shared by several places (filters and analysis live in the hero card popovers).
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a file, routine, module…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search (Ctrl+F)")
        self.search.returnPressed.connect(self.run_search)
        self.btn_scan = QPushButton("Analyze")
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.cancel_scan)
        self.btn_cancel.setEnabled(False)
        # Filters of the Dependents / Dependencies / Impact panel: path, language, relationship, resolution.
        self.filter_path = QLineEdit()
        self.filter_path.setPlaceholderText("Path starts with…")
        self.filter_path.setAccessibleName("Path filter of the panel")
        self.filter_path.textChanged.connect(lambda _t: self._fill_relations())
        self.filter_language = QComboBox()
        self.filter_language.addItems(["All languages"])
        self.filter_language.setAccessibleName("Language filter of the panel")
        self.filter_relationship = QComboBox()
        self.filter_relationship.addItems(["All relationships", *RELATIONSHIPS])
        self.filter_relationship.setAccessibleName("Relationship filter of the panel")
        self.filter_resolution = QComboBox()
        self.filter_resolution.addItems(RESOLUTION_FILTERS)
        self.filter_resolution.setAccessibleName("Resolution filter of the panel: confirmed or possible")
        for box in (self.filter_language, self.filter_relationship, self.filter_resolution):
            box.currentIndexChanged.connect(lambda _i: self._fill_relations())
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(9)

        # Views of the details panel.
        self.inventory_table = QTableWidget(0, 5)
        self.inventory_table.setHorizontalHeaderLabels(["Language", "Files", "Lines", "Adapter", "Status"])
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.inventory_table.verticalHeader().hide()
        self.unknown_label = elastic(QLabel(""))
        inv = QWidget()
        il = QVBoxLayout(inv)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(self.inventory_table)
        il.addWidget(self.unknown_label)
        self.all_subfolders = QCheckBox("Analyze all subfolders")
        self.all_subfolders.setToolTip("Ignore .gitignore and the default exclusions such as build, .venv, "
                                       "node_modules. Version-control folders (.git, .hg, .svn) are never analyzed.")
        self.all_subfolders.toggled.connect(self._on_all_subfolders)
        il.addWidget(self.all_subfolders)
        self.skipped_label = elastic(QLabel(""))
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
        self.graph_files = Graph3DView(self.runner)
        self.graph_files.node_selected.connect(self._graph_node_selected)
        self.graph_dirs = Graph3DView(self.runner, directories=True)
        self.health_view = QPlainTextEdit()
        self.health_view.setReadOnly(True)
        self.deps_view = DependencyView(self.runner)
        self.deps_view.source_requested.connect(lambda path, line: self.show_file(path, line))
        self._evidence_from: QWidget | None = None
        for graph in (self.graph_files, self.graph_dirs):
            graph.evidence_requested.connect(self._show_link_evidence)
        self.deps_view.back_requested.connect(self._back_from_evidence)
        self.groups: dict[str, tuple[str, str, list[tuple[str, QWidget]]]] = {
            "explore": ("Explore", "graph", [("Files", self.graph_files), ("Folders", self.graph_dirs),
                                             ("Dependencies", self.deps_view)]),
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
        self.header_info = elastic(QLabel("No project open."), wrap=False)
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
        self.links_tabs.setUsesScrollButtons(True)  # the tab titles never widen the window (UI audit)
        self.links_tabs.tabBar().setExpanding(False)
        self.dependents_tree = self._relations_tree(["File", "Relationships", "Status"])
        self.dependencies_tree = self._relations_tree(["File", "Relationships", "Status"])
        self.impact_tree = self._relations_tree(["File", "Distance", "Certainty"])
        self.links_tabs.addTab(self.dependents_tree, "Dependents")
        self.links_tabs.addTab(self.dependencies_tree, "Dependencies")
        self.links_tabs.addTab(self.impact_tree, "Impact")
        self.links_tabs.setTabToolTip(0, "Files depending on the selected file. Double-click a file to select it, "
                                         "a relationship to list its occurrences.")
        self.links_tabs.setTabToolTip(1, "Files the selected file depends on. Double-click a file to select it, "
                                         "a relationship to list its occurrences.")
        self.links_tabs.setTabToolTip(2, "Files a change of the selected file may affect (its dependents, directly "
                                         "or not); possible when reached through a possible dependency.")
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
        self.hero.badge_dependents.clicked.connect(lambda: self.links_tabs.setCurrentIndex(0))
        self.hero.badge_dependencies.clicked.connect(lambda: self.links_tabs.setCurrentIndex(1))
        self.hero.btn_filters.clicked.connect(lambda: self.filters_popover.show_under(self.hero.btn_filters))
        self.hero.btn_analysis.clicked.connect(lambda: self.analysis_popover.show_under(self.hero.btn_analysis))
        self.hero.btn_view.clicked.connect(lambda: self.view_popover.show_under(self.hero.btn_view))

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.status_label = elastic(QLabel("No project open."), wrap=False)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.show_view(self.graph_files)  # Files is the opening view (D40)

    def _focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _rail_button(self, icon_name: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setIcon(theme.icon(icon_name))
        b.setIconSize(QSize(22, 22))
        b.setFixedSize(40, 40)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # reachable with Tab, activated with Space
        return b

    def _build_popovers(self) -> None:
        self.filters_popover = Popover(self, "Filters of the Dependents / Dependencies panel", columns=2)
        for w in (self.filter_path, self.filter_language, self.filter_relationship, self.filter_resolution):
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

    def _relations_tree(self, headers: list[str]) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.itemDoubleClicked.connect(self._relation_activated)
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
            self._cancelled = True  # a cancellation, not a failure: no error dialog
            self.process.cancel(wait=True)
        self._clear_project_state()
        self.project = open_project(root, project_folder)
        self.settings.setValue("last_project", str(root))
        self.setWindowTitle(f"CodeGraph-Sci — {root}")
        self.title_bar.title.setText(f"CodeGraph-Sci — {root}")
        self.header_info.setText(str(root))
        self.hero.title.setText(root.name or str(root))
        self.hero.subtitle.setText("Select a file: file explorer, search or a click in a graph.")
        self.hero.summary.setText("")
        self.hero.set_counts(None, None)
        if self.db is not None:
            self.load_project()
        else:
            self.status_label.setText("Language inventory…")
            self.pending_scan = True
            self._run_cgs(["inventory", str(root), "--project", str(self.project.folder), "--json"])

    def _clear_project_state(self) -> None:
        """Forget everything shown for the previous project; late answers of its queries are dropped."""
        self.runner.cancel_all()
        self.current_file = None
        self.relations = None
        self.relations_loaded = False
        self.file_cycles = None
        self.file_langs = {}
        self.inspector.clear()
        for tree in (self.dependents_tree, self.dependencies_tree, self.impact_tree):
            tree.clear()
        for i, name in enumerate(("Dependents", "Dependencies", "Impact")):
            self.links_tabs.setTabText(i, name)
        self.hero.set_counts(None, None)
        self.summary.setText("")
        self.results.clear()
        self.files_view.setModel(None)
        for graph in (self.graph_files, self.graph_dirs):
            graph.clear()
        self.deps_view.set_db(None)
        self.inventory_table.setRowCount(0)
        self.unknown_label.setText("")
        self.skipped_label.setText("")
        self.health_view.clear()

    def load_project(self) -> None:
        db = self.db
        if db is None:
            return
        self.runner.submit(db, "inventory", lambda q: q.inventory(), self._show_inventory, self._error)
        self.runner.submit(db, "files", lambda q: q.files(), self._show_files, self._error)
        self.runner.submit(db, "health", lambda q: (q.scan_health(), q.unresolved(include_ambiguous=True, limit=30),
                                                    q.file_cycles()),
                           self._show_health, self._error)
        self.graph_files.load_overview(db)
        self.graph_dirs.load_overview(db)
        self.deps_view.set_db(db)

    # ------------------------------------------------------------ analysis
    def _run_cgs(self, args: list[str]) -> None:
        self._cancelled = False
        self._running = {"scan": "Analysis", "inventory": "Language inventory", "profile": "Profile update"}.get(
            args[0], "Command")
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
        self._cancelled = True
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
            self.pending_scan = False
            if self._cancelled:
                self.status_label.setText(f"{self._running} cancelled.")
                return
            lines = [line for line in stderr.strip().splitlines() if line.strip()]
            reason = lines[-1] if lines else f"exit code {code}"
            self.status_label.setText(f"{self._running} failed: {reason}")
            QMessageBox.warning(self, self._running, f"{self._running} failed (code {code}).\n\n{stderr[-1500:]}")
            return
        if self.pending_scan:
            self.pending_scan = False
            self.start_scan()
            return
        self.file_cycles = None  # computed again from the new analysis
        self.load_project()
        self.refresh_file()

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
        self.file_langs = {str(f["path"]): f["lang"] for f in files}
        languages = sorted({str(lang) for lang in self.file_langs.values() if lang})
        current = self.filter_language.currentText()
        self.filter_language.blockSignals(True)
        self.filter_language.clear()
        self.filter_language.addItems(["All languages", *languages])
        self.filter_language.setCurrentText(current if current in languages else "All languages")
        self.filter_language.blockSignals(False)
        self.deps_view.set_languages(languages)
        self.files_model = FileTreeModel(files)
        self.files_view.setModel(self.files_model)
        header = self.files_view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.files_view.setColumnHidden(1, True)  # the language is the colour of the name (narrow column)

    def _show_health(self, data: tuple[ScanHealth, list[Any], list[list[str]]]) -> None:
        health, groups, cycles = data
        self.file_cycles = cycles
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
        lines += ["", f"File cycles: {len(cycles)} (files depending on each other, possible dependencies included)"]
        lines += [f"  {len(c):>4} files  {', '.join(c)}" for c in cycles[:MAX_CYCLES_SHOWN]]
        if len(cycles) > MAX_CYCLES_SHOWN:
            lines.append(f"  … and {len(cycles) - MAX_CYCLES_SHOWN} more")
        lines += ["", "Unresolved or ambiguous sites, by pattern:"]
        lines += [f"  {g.count:>6}  {g.lang:<8} {g.resolution:<10} {g.pattern}" for g in groups]
        if health.failures:
            lines += ["", "Failed or fallback files:"]
            lines += [f"  {f['status']:<9} {f['path']}" for f in health.failures[:50]]
        self.health_view.setPlainText("\n".join(lines))
        self.status_label.setText(f"Project: {self.project.root if self.project else ''} — "
                                  f"unresolved {health.unresolved_rate:.1%}, ambiguous {health.ambiguous}, "
                                  f"{len(cycles)} file cycle(s)")
        if self.relations is not None:
            self._fill_relations()  # the summary names the cycle of the selected file

    # -------------------------------------------------------------- search
    def run_search(self) -> None:
        text = self.search.text().strip()
        db = self.db
        if not text or db is None:
            return
        self.runner.submit(db, "search", lambda q: q.find(text, limit=100), self._show_results)

    def _show_results(self, results: list[NodeSummary]) -> None:
        """Files and the symbols they define; activating one opens its file (at the definition line)."""
        self.results.clear()
        for r in results:
            if not r.file:
                continue
            item = QListWidgetItem(f"{r.file}   [{r.display_name}, {r.kind}, {r.lang or '-'}]")
            item.setData(PATH_ROLE, r.file)
            item.setData(LINE_ROLE, r.line or 0)
            item.setToolTip(r.uid)
            self.results.addItem(item)
        text = self.search.text().strip().lower()
        exact = [r for r in results if r.file and (r.display_name.lower() == text or r.file.lower() == text)]
        if exact or len([r for r in results if r.file]) == 1:
            r = exact[0] if exact else next(r for r in results if r.file)
            assert r.file is not None
            self.select_file(r.file, r.line if r.kind != "file" else None)

    def _result_activated(self, item: QListWidgetItem) -> None:
        path = item.data(PATH_ROLE)
        if isinstance(path, str):
            line = item.data(LINE_ROLE)
            self.select_file(path, int(line) if line else None)

    # -------------------------------------------------------- selection
    def select_file(self, path: str, line: int | None = None) -> None:
        """Select a file: its source, its dependents, dependencies and impact; the Files graph centres on it."""
        db = self.db
        if db is None:
            return
        self.current_file = path
        self.relations_loaded = False
        self.show_file(path, line)
        if not self._from_graph:
            self.graph_files.set_root(db, f"file:{path}")
        self._from_graph = False

        def work(q: Any) -> tuple[list[FileRelation], list[FileRelation], FileImpact]:
            return q.file_relations(path, incoming=True), q.file_relations(path, incoming=False), q.file_impact(path)

        self.runner.submit(db, "file", work, lambda data: self._show_relations(path, data), self._error)

    def open_target(self, uid: str) -> None:
        """The file defining ``uid`` (a reference target), at its definition line."""
        db = self.db
        if db is None:
            return

        def opened(node: Any) -> None:
            if node.file:
                self.select_file(node.file, node.line)
            else:
                self.status_label.setText(f"{uid} is defined outside the analysed files")

        self.runner.submit(db, "target", lambda q: q.node(uid), opened, self._error)

    def refresh_file(self) -> None:
        if self.current_file is not None:
            self.select_file(self.current_file)

    def _show_relations(self, path: str, data: tuple[list[FileRelation], list[FileRelation], FileImpact]) -> None:
        if path != self.current_file:
            return  # an earlier selection
        self.relations = data
        self.relations_loaded = True
        lang = self.file_langs.get(path)
        self.hero.title.setText(path.rsplit("/", 1)[-1])
        self.hero.subtitle.setText(f"file · {lang or '-'} · {path}")
        self._fill_relations()

    def _keep(self, path: str, dep: FileDependency | None) -> bool:
        """The panel filters: path prefix and language of the other file, relationship and resolution."""
        prefix = self.filter_path.text().strip()
        if prefix and not path.startswith(prefix):
            return False
        if self.filter_language.currentIndex() > 0 and self.file_langs.get(path) != self.filter_language.currentText():
            return False
        if dep is None:
            return True
        if self.filter_relationship.currentIndex() > 0 and dep.relationship != self.filter_relationship.currentText():
            return False
        wanted = self.filter_resolution.currentText()
        return wanted not in ("confirmed", "possible") or dep.confirmed == (wanted == "confirmed")

    def _fill_relation_tree(self, tree: QTreeWidget, relations: list[FileRelation]) -> int:
        tree.clear()
        shown = 0
        for rel in relations:
            details = [d for d in rel.details if self._keep(rel.path, d)]
            if not details:
                continue
            shown += 1
            counts: dict[str, int] = {}
            for d in details:
                counts[d.relationship] = counts.get(d.relationship, 0) + d.count
            confirmed = any(d.confirmed for d in details)
            top = QTreeWidgetItem([rel.path, ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
                                   "confirmed" if confirmed else "possible"])
            top.setData(0, PATH_ROLE, rel.path)
            top.setToolTip(0, f"{rel.path} — double-click to select this file")
            for d in details:
                child = QTreeWidgetItem([d.relationship, str(d.count), d.resolution])
                child.setData(0, FILTER_ROLE, d.occurrences)
                child.setToolTip(0, "Double-click to list the occurrences and their source locations")
                top.addChild(child)
            tree.addTopLevelItem(top)
        return shown

    def _fill_impact(self, impact: FileImpact) -> int:
        self.impact_tree.clear()
        wanted = self.filter_resolution.currentText()
        rows = [(impact.depth[f], f, "confirmed") for f in impact.confirmed]
        rows += [(impact.depth[f], f, "possible") for f in impact.possible]
        shown = 0
        for depth, path, certainty in sorted(rows):
            if not self._keep(path, None) or (wanted in ("confirmed", "possible") and certainty != wanted):
                continue
            item = QTreeWidgetItem([path, str(depth), certainty])
            item.setData(0, PATH_ROLE, path)
            item.setToolTip(0, f"{path} — double-click to select this file")
            self.impact_tree.addTopLevelItem(item)
            shown += 1
        return shown

    def _fill_relations(self) -> None:
        """Fill the panel from the loaded relations through the filters; badges, tabs and summary agree."""
        if self.relations is None or self.current_file is None:
            return
        dependents, dependencies, impact = self.relations
        n_in = self._fill_relation_tree(self.dependents_tree, dependents)
        n_out = self._fill_relation_tree(self.dependencies_tree, dependencies)
        n_impact = self._fill_impact(impact)
        self.links_tabs.setTabText(0, f"Dependents ({n_in})")
        self.links_tabs.setTabText(1, f"Dependencies ({n_out})")
        self.links_tabs.setTabText(2, f"Impact ({n_impact})")
        self.hero.set_counts(n_in, n_out)

        def counted(shown: int, total: int) -> str:
            return f"<b>{shown}</b>" + (f" (of {total} before the filters)" if shown != total else "")

        cycle = next((c for c in self.file_cycles or [] if self.current_file in c), None)
        in_cycle = f" — in a cycle with {len(cycle) - 1} other file(s)" if cycle else ""
        self.summary.setText(f"Used by {counted(n_in, len(dependents))} file(s) — depends on "
                             f"{counted(n_out, len(dependencies))} file(s) — impact: {len(impact.confirmed)} "
                             f"confirmed, {len(impact.possible)} possible file(s){in_cycle}")

    def _relation_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        occurrences = item.data(0, FILTER_ROLE)
        if occurrences is not None:  # a relationship: its occurrences and source locations
            self._show_link_evidence(occurrences)
            return
        path = item.data(0, PATH_ROLE)
        if isinstance(path, str):
            self.select_file(path)

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

    def _file_activated(self, index: Any) -> None:
        path = index.siblingAtColumn(0).data(FileTreeModel.PATH_ROLE)
        if isinstance(path, str) and path.startswith("dir:"):  # a folder: the folder tree from it
            self.graph_dirs.set_folder_root(path[4:])
            self.show_view(self.graph_dirs)
            return
        if isinstance(path, str):
            self.select_file(path)

    # ------------------------------------------------------------ 3D graphs
    def _graph_node_selected(self, uid: str) -> None:
        if uid.startswith("file:"):
            self._from_graph = True  # keep the drawn graph: only the panels follow the selection
            self.select_file(uid[5:])

    def _show_link_evidence(self, filters: Any) -> None:
        """A link (graph or panel): its occurrences and evidence in the Dependencies view, shown (UI audit)."""
        current = self.views.currentWidget()
        self._evidence_from = current if current is not self.deps_view else self._evidence_from
        self.deps_view.show_occurrences(filters, back=self._evidence_from is not None)
        self.show_view(self.deps_view)

    def _back_from_evidence(self) -> None:
        if self._evidence_from is not None:
            self.show_view(self._evidence_from)

    def _error(self, message: str) -> None:
        self.status_label.setText(message.splitlines()[0])

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        if self.process.running():  # no analysis outlives the window (UI audit, UI-03)
            self.pending_scan = False
            self._cancelled = True
            self.process.cancel(wait=True)
        self.runner.cancel_all()
        super().closeEvent(event)
