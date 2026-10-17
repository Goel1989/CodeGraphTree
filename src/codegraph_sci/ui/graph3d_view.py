"""3D graph of functions or files embedded in the main window (§3.11, decision D21).

The page is the vendored 3d-force-graph view (``ui/web``) shown in a ``QWebEngineView``. It is written once to a
temporary file and receives its data from Python (``cgs.load`` / ``cgs.merge``); it talks back through console
messages ``CGS:<json>`` (select, expand, link). Offline by construction: the page has a CSP without any network
source, the profile is off the record (Qt default) and a request interceptor blocks every scheme other than file, data and blob.
"""

from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, Qt, QUrl, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from codegraph_sci.query.api import GraphQuery
from codegraph_sci.query.types import Graph3D, MainPathReport
from codegraph_sci.ui.view3d.html import build_html, empty_graph, graph_dict, safe_json
from codegraph_sci.ui.workers import QueryRunner

ALLOWED_SCHEMES = frozenset({"file", "data", "blob", "about"})
EXPAND_MAX_NODES = 150  # one right-click adds at most this many nodes (C4)
GROUP_PREFIXES = ("group:", "isolated:", "more:")  # overview nodes that open a group, not symbols

_page_file: Path | None = None
_interceptor: OfflineInterceptor | None = None


def page_path() -> Path:
    """The 3D page (same for every view), written once per process in a private temporary folder."""
    global _page_file
    if _page_file is None or not _page_file.is_file():
        folder = Path(tempfile.mkdtemp(prefix="cgs-3d-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        _page_file = folder / "view3d.html"
        _page_file.write_text(build_html(empty_graph("functions"), "3D", host="qt"), encoding="utf-8")
    return _page_file


class OfflineInterceptor(QWebEngineUrlRequestInterceptor):
    """Blocks any request that could leave the machine (constraint C2)."""

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802 - Qt API
        if info.requestUrl().scheme() not in ALLOWED_SCHEMES:
            info.block(True)


def offline_profile() -> QWebEngineProfile:
    """Qt's default profile (off the record since Qt 6: no disk cache, no cookies kept) with the offline interceptor.

    Owned by Qt, so it outlives every page; a profile of our own crashed at exit when deleted before its pages.
    """
    global _interceptor
    profile = QWebEngineProfile.defaultProfile()
    if _interceptor is None:
        _interceptor = OfflineInterceptor(QCoreApplication.instance())
        profile.setUrlRequestInterceptor(_interceptor)
    return profile


class _Page(QWebEnginePage):
    def __init__(self, owner: Graph3DView) -> None:
        super().__init__(offline_profile(), owner)
        self.owner = owner
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)

    def javaScriptConsoleMessage(  # noqa: N802 - Qt API
        self, level: QWebEnginePage.JavaScriptConsoleMessageLevel, message: str, line: int, source: str
    ) -> None:
        if message.startswith("CGS:"):
            try:
                event = json.loads(message[4:])
            except json.JSONDecodeError:
                return
            if isinstance(event, dict):
                self.owner.handle_event(event)
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.owner.js_errors.append(f"{line}: {message}")

    def acceptNavigationRequest(  # noqa: N802 - Qt API
        self, url: QUrl | str, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        return QUrl(url).scheme() in ALLOWED_SCHEMES


class Graph3DView(QWidget):
    """One 3D graph (functions or files).

    Starts with the overview of the whole project (every node and link, or one sphere per group when it does not fit);
    a click on a sphere opens its group; follows the selection of the other panels; expands on right-click.
    """

    node_selected = Signal(str)
    sites_requested = Signal(str, str)  # (caller uid, callee uid) for the detailed calls of a link
    evidence_requested = Signal(object)  # DependencyFilter of the rows behind a clicked link (same as the table)

    def __init__(self, runner: QueryRunner, *, files: bool, directories: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runner = runner
        self.files = files or directories
        self.directories = directories  # directory level (D34): folders and the links between them
        self.db: Path | None = None
        self.root_uid: str | None = None
        self.main_uid: str | None = None
        self.selected_uid: str | None = None
        self.overview = False  # showing the overview of every group
        self.group_id: str | None = None  # showing one group of the overview
        self.hide_noise = True
        self.node_ids: set[str] = set()
        self.link_keys: set[tuple[str, str, str]] = set()
        self.page_ready = False
        self.webgl: bool | None = None
        self.js_nodes = 0
        self.js_errors: list[str] = []
        self._pending: list[str] = []
        self._gen = 0

        self.btn_groups = QPushButton("All groups")
        self.btn_groups.setToolTip("Overview of the whole project: separate groups are separate (or parallel) programs")
        self.btn_groups.clicked.connect(self._reset_to_groups)
        self.btn_from_main = QPushButton("From main")
        self.btn_from_main.setToolTip("Detect the main entry point and show its neighbourhood")
        self.btn_from_main.clicked.connect(self._reset_to_main)
        self.btn_to_main = QPushButton("Paths to main")
        self.btn_to_main.setCheckable(True)
        self.btn_to_main.setToolTip("Show only the paths between main and the selected node "
                                    "(shortest path if there are too many)")
        self.btn_to_main.toggled.connect(self._on_to_main_toggled)
        self.depth = QSpinBox()
        self.depth.setRange(1, 6)
        self.depth.setValue(2)
        self.depth.setToolTip("Levels of callers and callees around the root")
        self.depth.valueChanged.connect(lambda _v: self.rebuild())
        self.max_nodes = QSpinBox()
        self.max_nodes.setRange(50, 2000)
        self.max_nodes.setValue(300)
        self.max_nodes.setToolTip("Maximum number of drawn nodes")
        self.max_nodes.valueChanged.connect(lambda _v: self.rebuild())
        self.with_files = QCheckBox("Defining files")
        self.with_files.setToolTip("Also show the files that define the routines, and the links between them")
        self.with_files.toggled.connect(lambda _v: self.rebuild())
        self.with_files.setVisible(not self.files)
        for w in (self.btn_from_main, self.btn_to_main, self.depth):
            w.setVisible(not directories)
        self.info = QLabel("")
        top = QHBoxLayout()
        for w in (self.btn_groups, self.btn_from_main, self.btn_to_main, QLabel("Depth:"), self.depth, QLabel("Max nodes:"),
                  self.max_nodes, self.with_files):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.info)

        self.web = QWebEngineView(self)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # right-click expands a node
        self.page = _Page(self)
        self.web.setPage(self.page)
        self.web.load(QUrl.fromLocalFile(str(page_path())))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.web, 1)

    # -------------------------------------------------------------- state
    @property
    def mode(self) -> str:
        if self.directories:
            return "directories"
        if self.files:
            return "files"
        return "both" if self.with_files.isChecked() else "functions"

    def _key(self, what: str) -> str:
        return f"graph3d:{id(self)}:{what}"

    def _next_gen(self) -> int:
        self._gen += 1
        return self._gen

    # ------------------------------------------------------------ loading
    def load_overview(self, db: Path) -> None:
        """The whole project: every node and link if it fits, else one sphere per group (and ``main`` detected)."""
        self.db = db
        gen = self._next_gen()
        mode, limit, hide, files = self.mode, self.max_nodes.value(), self.hide_noise, self.files
        if self.directories:
            def show_dirs(graph: Graph3D) -> None:
                if gen == self._gen:
                    self.overview, self.group_id, self.root_uid = True, None, None
                    self._show(graph)

            self.runner.submit(db, self._key("load"), lambda q: q.graph3d_directories(max_nodes=limit), show_dirs,
                               self._error)
            return

        def work(q: GraphQuery) -> tuple[str | None, Graph3D]:
            roots = q.default_roots(hide_noise=hide)
            main = roots.main_file if files else roots.main_routine
            return (main.uid if main else None,
                    q.graph3d_overview(mode=mode, max_nodes=limit, hide_noise=hide, include_noncode=files))

        def done(data: tuple[str | None, Graph3D]) -> None:
            if gen != self._gen:
                return
            self.main_uid = data[0]
            self.overview, self.group_id, self.root_uid = True, None, None
            self._show(data[1])

        self.runner.submit(db, self._key("load"), work, done, self._error)

    def open_group(self, group_id: str) -> None:
        """Content of an overview sphere: a group with all its links, the isolated nodes, or the next groups."""
        if self.db is None:
            return
        gen = self._next_gen()
        mode, limit, hide = self.mode, self.max_nodes.value(), self.hide_noise

        def done(graph: Graph3D) -> None:
            if gen != self._gen:
                return
            self.overview, self.group_id = False, group_id
            self._show(graph)

        self.runner.submit(self.db, self._key("load"),
                           lambda q: q.graph3d_group(group_id, mode=mode, max_nodes=limit, hide_noise=hide),
                           done, self._error)

    def _reset_to_groups(self) -> None:
        if self.btn_to_main.isChecked():
            self.btn_to_main.blockSignals(True)
            self.btn_to_main.setChecked(False)
            self.btn_to_main.blockSignals(False)
        if self.db is not None:
            self.load_overview(self.db)

    def load_from_main(self, db: Path) -> None:
        """Detect ``main`` (routine or file) and show its neighbourhood."""
        self.db = db
        gen = self._next_gen()
        mode, depth, limit, hide, files = self.mode, self.depth.value(), self.max_nodes.value(), self.hide_noise, \
            self.files

        def work(q: GraphQuery) -> tuple[str, Graph3D]:
            roots = q.default_roots(hide_noise=hide)
            main = roots.main_file if files else roots.main_routine
            if main is None:
                raise ValueError("no main entry point in this analysis")
            return main.uid, q.graph3d(main.uid, mode=mode, depth=depth, max_nodes=limit, hide_noise=hide)

        def done(data: tuple[str, Graph3D]) -> None:
            if gen != self._gen:
                return
            self.main_uid = self.root_uid = self.selected_uid = data[0]
            self.overview, self.group_id = False, None
            self._show(data[1])

        self.runner.submit(db, self._key("load"), work, done, self._error)

    def set_root(self, db: Path, uid: str) -> None:
        self.db = db
        self.overview, self.group_id = False, None
        self.root_uid = uid
        self.selected_uid = uid
        if self.btn_to_main.isChecked():
            self.show_paths_from_main(uid)
        else:
            self.rebuild()

    def rebuild(self) -> None:
        if self.db is None:
            return
        if self.overview:
            self.load_overview(self.db)
            return
        if self.group_id is not None:
            self.open_group(self.group_id)
            return
        if self.root_uid is None:
            self.load_from_main(self.db)
            return
        if self.btn_to_main.isChecked() and self.selected_uid is not None:
            self.show_paths_from_main(self.selected_uid)
            return
        gen = self._next_gen()
        root, mode, depth, limit, hide = self.root_uid, self.mode, self.depth.value(), self.max_nodes.value(), \
            self.hide_noise

        def done(graph: Graph3D) -> None:
            if gen == self._gen:
                self.overview, self.group_id = False, None
                self._show(graph)

        self.runner.submit(self.db, self._key("load"),
                           lambda q: q.graph3d(root, mode=mode, depth=depth, max_nodes=limit, hide_noise=hide),
                           done, self._error)

    def show_paths_from_main(self, target_uid: str) -> None:
        """Only the path(s) from ``main`` to ``target_uid`` (the shortest one when there are too many)."""
        if self.db is None:
            return
        gen = self._next_gen()
        mode = self.mode

        def done(data: tuple[Graph3D, MainPathReport]) -> None:
            if gen != self._gen:
                return
            graph, report = data
            self.overview, self.group_id = False, None
            self._show(graph)
            if not report.paths:
                self.info.setText(f"No path found from main ({report.root_uid}) to {report.target_uid}")
            else:
                note = " — shortest path only, many exist" if report.showing_shortest_only else ""
                self.info.setText(f"{len(report.paths)} path(s) from main ({report.root_uid}){note}")

        self.runner.submit(self.db, self._key("load"), lambda q: q.graph3d_main_paths(target_uid, mode=mode),
                           done, self._error)

    def expand(self, uid: str) -> None:
        """Add the direct callers and callees of ``uid`` to the drawn graph."""
        if self.db is None or uid.startswith("dir:"):
            return
        gen = self._gen
        mode = "files" if uid.startswith("file:") else self.mode
        hide = self.hide_noise

        def done(graph: Graph3D) -> None:
            if gen != self._gen:
                return
            new = {n.id for n in graph.nodes} - self.node_ids
            if len(self.node_ids) + len(new) > self.max_nodes.value():
                self.info.setText(f"Limit of {self.max_nodes.value()} nodes reached: raise it, or pick another root.")
                return
            self._show(graph, merge=True)

        self.runner.submit(self.db, self._key(f"expand:{uid}"),
                           lambda q: q.graph3d(uid, mode=mode, depth=1, max_nodes=EXPAND_MAX_NODES, hide_noise=hide),
                           done, self._error)

    def _show(self, graph: Graph3D, *, merge: bool = False) -> None:
        if not merge:
            self.node_ids = set()
            self.link_keys = set()
        self.node_ids |= {n.id for n in graph.nodes}
        self.link_keys |= {(lk.source, lk.target, lk.kind) for lk in graph.links if
                           lk.source in self.node_ids and lk.target in self.node_ids}
        self._run_js(f"window.cgs.{'merge' if merge else 'load'}({safe_json(graph_dict(graph))});")
        hidden = f", {graph.hidden_noise} utility item(s) hidden" if graph.hidden_noise else ""
        limit = " — limit reached" if graph.truncated else ""
        spheres = sum(1 for n in graph.nodes if n.kind == "group")
        where = (f"Overview, {spheres} group sphere(s): click one to open it — " if spheres
                 else "Overview of the whole project — " if self.overview
                 else f"Group {self.group_id.split(':', 1)[1]} — " if self.group_id else "")
        crossing = sum(1 for lk in graph.links if lk.cross_dir)
        self.info.setText(f"{where}{len(self.node_ids)} node(s), {len(self.link_keys)} link(s), "
                          f"{crossing} between folders{hidden}{limit}")

    def query_js(self, script: str, callback: Any) -> None:
        """Evaluate a JavaScript expression in the page and pass its value to ``callback`` (tests, diagnostics)."""
        self.page.runJavaScript(script, 0, callback)

    def _run_js(self, script: str) -> None:
        if self.page_ready:
            self.page.runJavaScript(script)
        else:
            self._pending.append(script)

    def _reset_to_main(self) -> None:
        if self.btn_to_main.isChecked():
            self.btn_to_main.blockSignals(True)
            self.btn_to_main.setChecked(False)
            self.btn_to_main.blockSignals(False)
        if self.db is not None:
            self.load_from_main(self.db)

    def _on_to_main_toggled(self, checked: bool) -> None:
        if self.db is None:
            return
        if checked and (self.selected_uid or self.root_uid):
            self.show_paths_from_main(str(self.selected_uid or self.root_uid))
        else:
            self.rebuild()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._run_js("window.cgs.shown();")  # size and fit a graph loaded while the tab was hidden

    def _error(self, message: str) -> None:
        self.info.setText(message.splitlines()[0] if message else "error")

    # ------------------------------------------------------- page events
    def handle_event(self, event: dict[str, Any]) -> None:
        """Message from the page (``CGS:<json>`` console line)."""
        kind = event.get("event")
        if kind == "ready":
            self.page_ready = True
            self.webgl = bool(event.get("webgl"))
            pending, self._pending = self._pending, []
            for script in pending:
                self.page.runJavaScript(script)
        elif kind == "loaded" and isinstance(event.get("nodes"), int):
            self.js_nodes = event["nodes"]
        elif kind in ("select", "expand") and isinstance(event.get("uid"), str) \
                and event["uid"].startswith(GROUP_PREFIXES):
            self.open_group(event["uid"])
        elif kind in ("select", "expand") and isinstance(event.get("uid"), str) and event["uid"].startswith("noncode:"):
            return  # not analyzed code: nothing to select or expand
        elif kind == "select" and isinstance(event.get("uid"), str):
            self.selected_uid = event["uid"]
            self.node_selected.emit(event["uid"])
            if self.btn_to_main.isChecked():
                self.show_paths_from_main(event["uid"])
        elif kind == "expand" and isinstance(event.get("uid"), str):
            self.expand(event["uid"])
        elif kind == "link" and isinstance(event.get("source"), str) and isinstance(event.get("target"), str):
            src, dst = event["source"], event["target"]
            if src.startswith(GROUP_PREFIXES) or dst.startswith(GROUP_PREFIXES):
                return
            self.evidence_requested.emit(GraphQuery.link_evidence(src, dst))  # the rows of the dependency table
            if not src.startswith(("file:", "dir:")) and not dst.startswith(("file:", "dir:")):
                self.sites_requested.emit(src, dst)
        elif kind == "error" and isinstance(event.get("message"), str):
            self.js_errors.append(event["message"])
