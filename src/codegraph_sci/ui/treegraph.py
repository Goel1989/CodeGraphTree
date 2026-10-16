"""TreeGraph views (§1.2, §3.11, §3.12): calls of a routine or links of a file/directory, drawn as a tree.

Starts from the detected ``main`` entry point with the first ``N`` nodes; clicking a node opens all
its connected callers and callees with directed arrows (caller -> callee); optional filter shows only
the path(s) from ``main`` to the selected node (or the shortest path when too many exist).
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from codegraph_sci.layout.tree import TreeLayout
from codegraph_sci.query.api import GraphQuery
from codegraph_sci.query.types import (
    Direction,
    Level,
    MainPathReport,
    NeighborsReport,
    Page,
    SubgraphReport,
    TreeItem,
)
from codegraph_sci.ui.models import LANG_COLORS
from codegraph_sci.ui.workers import QueryRunner

NODE_W, NODE_H = 210.0, 24.0
PAGE = 50


class NodeItem(QGraphicsItem):
    def __init__(self, view: TreeGraphView, uid: str, label: str, lang: str | None, *, seen: bool = False,
                 more: int = 0, expandable: bool = True, possible: bool = False) -> None:
        super().__init__()
        self.view = view
        self.uid = uid
        self.label = label
        self.lang = lang
        self.seen = seen
        self.more = more
        self.expandable = expandable and not seen
        self.possible = possible
        self.expanded = False
        self.offset = 0
        self.setCacheMode(QGraphicsItem.CacheMode.ItemCoordinateCache)
        self.setAcceptHoverEvents(True)
        self.setToolTip(uid if not more else f"{more} more — click to show more")
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return QRectF(0, -NODE_H / 2, NODE_W, NODE_H)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        color = QColor("#a0aec0") if self.more or self.seen else QColor(LANG_COLORS.get(self.lang, "#718096"))
        fill = QColor(color)
        fill.setAlpha(40 if not self.isSelected() else 110)
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine if self.possible or self.more else Qt.PenStyle.SolidLine))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(self.boundingRect(), 5, 5)
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        if lod < 0.45:
            return  # zoomed out: plain rectangles only
        painter.setPen(QPen(QColor("#1a202c")))
        text = self.label
        if self.seen:
            text += "  ↺"
        if self.expandable and not self.expanded and not self.more:
            text += "  ▸"
        painter.drawText(self.boundingRect().adjusted(6, 0, -4, 0),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, int(NODE_W - 10)))

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.view.on_node_clicked(self)

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self.view.activate(self)


class EdgeItem(QGraphicsLineItem):
    """Directed link from ``src`` (caller / using file) to ``dst`` (callee / used file) with an arrowhead at ``dst``."""

    def __init__(self, src: NodeItem, dst: NodeItem, item: TreeItem | None, file_level: bool) -> None:
        if src.pos().x() <= dst.pos().x():
            start = src.pos() + QPointF(NODE_W, 0)
            end = dst.pos()
        else:
            start = src.pos()
            end = dst.pos() + QPointF(NODE_W, 0)
        super().__init__(start.x(), start.y(), end.x(), end.y())
        self.src, self.dst, self.item = src, dst, item
        width = 1.2
        if item is not None and file_level:
            width = min(8.0, 1.0 + item.count ** 0.5)
        self.edge_color = QColor("#718096")
        pen = QPen(self.edge_color, width)
        if item is not None and (item.possible or item.edge_kind in ("bridges", "binds")):
            pen.setStyle(Qt.PenStyle.DashLine)
            self.edge_color = QColor("#c05621")
            pen.setColor(self.edge_color)
        self.setPen(pen)
        self.setZValue(-1)
        self.arrow_polygon = self._compute_arrow(start, end)
        if item is not None:
            self.setToolTip(
                f"{src.label} → {dst.label} ({item.edge_kind} — {item.count} call(s) — {item.confidence})"
            )
        else:
            self.setToolTip(f"{src.label} → {dst.label}")

    @staticmethod
    def _compute_arrow(start: QPointF, end: QPointF) -> QPolygonF:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length <= 1e-3:
            return QPolygonF([end, end + QPointF(-6.0, -3.5), end + QPointF(-6.0, 3.5)])
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        arrow_len = 8.0
        half_w = 4.0
        bx = end.x() - ux * arrow_len
        by = end.y() - uy * arrow_len
        return QPolygonF([
            end,
            QPointF(bx + px * half_w, by + py * half_w),
            QPointF(bx - px * half_w, by - py * half_w),
        ])

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return super().boundingRect().united(self.arrow_polygon.boundingRect()).adjusted(-4, -4, 4, 4)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        super().paint(painter, option, widget)
        painter.save()
        painter.setPen(QPen(self.edge_color, 1.0, Qt.PenStyle.SolidLine))
        painter.setBrush(QBrush(self.edge_color))
        painter.drawPolygon(self.arrow_polygon)
        painter.restore()

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        view = self.src.view
        view.edge_activated(self)


class GraphView(QGraphicsView):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class TreeGraphView(QWidget):
    """One TreeGraph (functions or files); starts at ``main`` and expands connected nodes on click."""

    node_selected = Signal(str)
    sites_requested = Signal(str, str)  # (caller uid, callee uid) for the detailed calls of a link

    def __init__(self, runner: QueryRunner, file_level: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runner = runner
        self.file_level = file_level
        self.db: Path | None = None
        self.root_uid: str | None = None
        self.root_label: str = ""
        self.root_lang: str | None = None
        self.main_uid: str | None = None
        self.main_label: str = ""
        self.main_lang: str | None = None
        self.selected_uid: str | None = None
        self.hide_noise = True
        self._gen = 0
        self.layout_engine = TreeLayout()
        self.items: dict[str, NodeItem] = {}
        self.drawn_edges: set[tuple[str, str]] = set()
        self.scene = QGraphicsScene(self)
        self.view = GraphView(self.scene)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setFont(QFont("Segoe UI", 9))
        self.direction = QComboBox()
        self.direction.addItems(["Callees", "Callers"] if not file_level else ["Used files", "Used by"])
        self.direction.currentIndexChanged.connect(self.rebuild)
        self.level = QComboBox()
        self.level.addItems(["Routine"] if not file_level else ["File", "Directory"])
        self.level.currentIndexChanged.connect(self.rebuild)
        self.initial_nodes = QSpinBox()
        self.initial_nodes.setRange(1, 500)
        self.initial_nodes.setValue(25)
        self.initial_nodes.setToolTip("Number of initial nodes displayed starting from main")
        self.initial_nodes.valueChanged.connect(self._on_initial_nodes_changed)
        self.max_nodes = QSpinBox()
        self.max_nodes.setRange(50, 5000)
        self.max_nodes.setValue(300)
        self.btn_from_main = QPushButton("From main")
        self.btn_from_main.setToolTip("Detect the main entry point and display the first N nodes")
        self.btn_from_main.clicked.connect(self._reset_to_main)
        self.btn_to_main = QPushButton("Paths to main")
        self.btn_to_main.setCheckable(True)
        self.btn_to_main.setToolTip(
            "Display only links between main and the selected node "
            "(shortest path if too many paths)"
        )
        self.btn_to_main.toggled.connect(self._on_to_main_toggled)
        self.info = QLabel("")
        fit = QPushButton("Fit")
        fit.clicked.connect(self.fit)
        top = QHBoxLayout()
        for w in (
            self.btn_from_main,
            QLabel("First N:"),
            self.initial_nodes,
            self.btn_to_main,
            QLabel("Direction:"),
            self.direction,
            QLabel("Level:"),
            self.level,
            QLabel("Max nodes:"),
            self.max_nodes,
            fit,
        ):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.info)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.view)

    # -------------------------------------------------------------- state
    @property
    def dir(self) -> Direction:
        return Direction.CALLEES if self.direction.currentIndex() == 0 else Direction.CALLERS

    @property
    def lvl(self) -> Level:
        if not self.file_level:
            return Level.ROUTINE
        return Level.FILE if self.level.currentIndex() == 0 else Level.DIRECTORY

    def _clear_graph(self) -> int:
        self._gen += 1
        self.scene.clear()
        self.items = {}
        self.drawn_edges = set()
        self.layout_engine = TreeLayout()
        return self._gen

    def _add_directed_edge(
        self, caller: NodeItem, callee: NodeItem, item: TreeItem | None = None
    ) -> EdgeItem | None:
        key = (caller.uid, callee.uid)
        if key in self.drawn_edges:
            return None
        self.drawn_edges.add(key)
        edge = EdgeItem(caller, callee, item, self.file_level)
        self.scene.addItem(edge)
        return edge

    def load_from_main(self, db: Path, *, max_nodes: int | None = None) -> None:
        """Detect ``main`` and display the first ``N`` nodes starting from it."""
        self.db = db
        gen = self._clear_graph()
        level = self.lvl
        limit = max_nodes if max_nodes is not None else self.initial_nodes.value()
        hide = self.hide_noise

        def work(q: GraphQuery) -> SubgraphReport:
            return q.initial_subgraph(None, level=level, max_nodes=limit, hide_noise=hide)

        def done(report: SubgraphReport) -> None:
            if gen != self._gen:
                return
            self._render_subgraph(report)

        self.runner.submit(
            db, f"treegraph:init:{id(self)}:{gen}", work, done, lambda msg: self.info.setText(msg.splitlines()[0])
        )

    def _render_subgraph(self, report: SubgraphReport) -> None:
        self.main_uid = report.root.uid
        self.main_label = report.root.label
        self.main_lang = report.root.lang
        self.root_uid = report.root.uid
        self.root_label = report.root.label
        self.root_lang = report.root.lang
        self.selected_uid = report.root.uid
        x, y = self.layout_engine.place_root(report.root.uid)
        root_node = NodeItem(
            self, report.root.uid, report.root.label, report.root.lang, expandable=report.root.has_children
        )
        root_node.setPos(x, y)
        self.scene.addItem(root_node)
        self.items[report.root.uid] = root_node

        children_by_src: dict[str, list[TreeItem]] = defaultdict(list)
        for edge in report.edges:
            children_by_src[edge.src].append(edge.item)

        queue: deque[str] = deque([report.root.uid])
        visited: set[str] = {report.root.uid}
        while queue:
            src_uid = queue.popleft()
            if src_uid not in self.items:
                continue
            src_node = self.items[src_uid]
            kids = children_by_src.get(src_uid, [])
            if not kids:
                continue
            src_node.expanded = True
            new_uids = [c.uid for c in kids if c.uid not in self.items]
            positions = self.layout_engine.place_children(src_uid, new_uids)
            for child in kids:
                if child.uid not in self.items and child.uid in positions:
                    node = NodeItem(
                        self,
                        child.uid,
                        child.label,
                        child.lang,
                        expandable=child.has_children,
                        possible=child.possible,
                    )
                    node.setPos(*positions[child.uid])
                    self.scene.addItem(node)
                    self.items[child.uid] = node
                if child.uid in self.items:
                    self._add_directed_edge(src_node, self.items[child.uid], child)
                if child.uid not in visited:
                    visited.add(child.uid)
                    queue.append(child.uid)

        count = len(self.scene.items())
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, count <= 200)
        trunc = f" (first {len(self.items)} nodes)" if report.truncated else ""
        hidden = f", {report.hidden_noise} utility(ies) hidden" if report.hidden_noise else ""
        self.info.setText(
            f"Main entry: {report.root.label} — {len(self.items)} node(s), "
            f"{len(self.drawn_edges)} link(s){trunc}{hidden}"
        )

    def _reset_to_main(self) -> None:
        if self.btn_to_main.isChecked():
            self.btn_to_main.blockSignals(True)
            self.btn_to_main.setChecked(False)
            self.btn_to_main.blockSignals(False)
        if self.db is not None:
            self.load_from_main(self.db)

    def _on_initial_nodes_changed(self, _value: int) -> None:
        if self.db is not None and not self.btn_to_main.isChecked():
            self.load_from_main(self.db)

    def _on_to_main_toggled(self, checked: bool) -> None:
        if self.db is None:
            return
        if checked:
            target = self.selected_uid or self.root_uid
            if target is not None:
                self.show_paths_from_main(target)
        else:
            if self.root_uid is not None and self.root_uid != self.main_uid:
                self.rebuild()
            else:
                self.load_from_main(self.db)

    def set_root(self, db: Path, uid: str, label: str, lang: str | None) -> None:
        self.db = db
        self.root_uid = uid
        self.root_label = label
        self.root_lang = lang
        self.selected_uid = uid
        if self.btn_to_main.isChecked():
            self.show_paths_from_main(uid)
        else:
            self.rebuild()

    def rebuild(self) -> None:
        gen = self._clear_graph()
        if self.db is None:
            return
        if self.root_uid is None:
            self.load_from_main(self.db)
            return
        root = self.root_uid
        label = self.root_label
        if self.lvl is Level.DIRECTORY and root.startswith("file:"):
            path = root[5:]
            root = path.rsplit("/", 1)[0] if "/" in path else "."
            label = root
        x, y = self.layout_engine.place_root(root)
        item = NodeItem(self, root, label, self.root_lang)
        item.setPos(x, y)
        self.scene.addItem(item)
        self.items[root] = item
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.expand(item, gen=gen)

    # ---------------------------------------------------------- expansion
    def on_node_clicked(self, item: NodeItem) -> None:
        if item.more:
            self.activate(item)
            return
        self.selected_uid = item.uid
        self.node_selected.emit(item.uid)
        if self.btn_to_main.isChecked():
            self.show_paths_from_main(item.uid)
        else:
            self.expand_connected(item)

    def activate(self, item: NodeItem) -> None:
        if item.more:
            parent = item.data(0)
            self.scene.removeItem(item)
            if isinstance(parent, NodeItem):
                self.expand(parent, parent.offset)
            return
        self.on_node_clicked(item)

    def expand_connected(self, item: NodeItem) -> None:
        """Open all links and connected nodes (both callers and callees) of ``item``."""
        if self.db is None:
            return
        uid, level, hide, gen = item.uid, self.lvl, self.hide_noise, self._gen

        def work(q: GraphQuery) -> NeighborsReport:
            return q.connected_neighbors(uid, level=level, limit=PAGE, hide_noise=hide)

        def done(report: NeighborsReport) -> None:
            if gen != self._gen:
                return
            self._add_connected(item, report)

        self.runner.submit(self.db, f"treegraph:conn:{id(self)}:{uid}:{gen}", work, done)

    def _add_connected(self, center: NodeItem, report: NeighborsReport) -> None:
        center.expanded = True
        total_new = sum(1 for c in report.callers + report.callees if c.uid not in self.items)
        if len(self.items) + total_new > self.max_nodes.value():
            self.info.setText(
                f"Limit of {self.max_nodes.value()} nodes reached: switch to file "
                f"or directory level, or increase the limit."
            )
            return

        new_callers = [c for c in report.callers if c.uid not in self.items]
        caller_pos = self.layout_engine.place_parents(center.uid, [c.uid for c in new_callers])
        for caller in report.callers:
            if caller.uid not in self.items and caller.uid in caller_pos:
                node = NodeItem(
                    self,
                    caller.uid,
                    caller.label,
                    caller.lang,
                    expandable=caller.has_children,
                    possible=caller.possible,
                )
                node.setPos(*caller_pos[caller.uid])
                self.scene.addItem(node)
                self.items[caller.uid] = node
            if caller.uid in self.items:
                self._add_directed_edge(self.items[caller.uid], center, caller)

        new_callees = [c for c in report.callees if c.uid not in self.items]
        callee_pos = self.layout_engine.place_children(center.uid, [c.uid for c in new_callees])
        for callee in report.callees:
            if callee.uid not in self.items and callee.uid in callee_pos:
                node = NodeItem(
                    self,
                    callee.uid,
                    callee.label,
                    callee.lang,
                    expandable=callee.has_children,
                    possible=callee.possible,
                )
                node.setPos(*callee_pos[callee.uid])
                self.scene.addItem(node)
                self.items[callee.uid] = node
            if callee.uid in self.items:
                self._add_directed_edge(center, self.items[callee.uid], callee)

        count = len(self.scene.items())
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, count <= 200)
        hidden = f", {report.hidden_noise} utility(ies) hidden" if report.hidden_noise else ""
        self.info.setText(
            f"{center.label}: {len(report.callers)} caller(s), {len(report.callees)} callee(s) — "
            f"{len(self.items)} node(s){hidden}"
        )

    def show_paths_from_main(self, target_uid: str) -> None:
        """Display only the path(s) from ``main`` to ``target_uid`` (shortest path if too many exist)."""
        if self.db is None:
            return
        gen = self._clear_graph()
        level = self.lvl
        main_uid = self.main_uid

        def work(q: GraphQuery) -> tuple[MainPathReport, dict[str, TreeItem]]:
            rep = q.paths_from_main(target_uid, root_uid=main_uid, level=level, max_paths=3, max_len=15)
            meta: dict[str, TreeItem] = {}
            for p in rep.paths:
                for step in p.steps:
                    if step.uid not in meta:
                        meta[step.uid] = q._tree_item_for(step.uid, level)
            if target_uid not in meta:
                try:
                    meta[target_uid] = q._tree_item_for(target_uid, level)
                except Exception:
                    pass
            return rep, meta

        def done(data: tuple[MainPathReport, dict[str, TreeItem]]) -> None:
            if gen != self._gen:
                return
            self._render_main_paths(data[0], data[1])

        self.runner.submit(self.db, f"treegraph:tomain:{id(self)}:{target_uid}:{gen}", work, done)

    def _render_main_paths(self, report: MainPathReport, meta: dict[str, TreeItem]) -> None:
        self.selected_uid = report.target_uid
        if not report.paths:
            t_item = meta.get(report.target_uid)
            label = t_item.label if t_item else report.target_uid
            lang = t_item.lang if t_item else None
            x, y = self.layout_engine.place_root(report.target_uid)
            node = NodeItem(self, report.target_uid, label, lang)
            node.setPos(x, y)
            self.scene.addItem(node)
            self.items[report.target_uid] = node
            self.info.setText(f"No path found from main ({report.root_uid}) to {label}")
            return

        root_uid = report.paths[0].steps[0].uid
        r_meta = meta.get(root_uid)
        r_label = r_meta.label if r_meta else root_uid
        x, y = self.layout_engine.place_root(root_uid)
        root_node = NodeItem(self, root_uid, r_label, r_meta.lang if r_meta else None, expandable=True)
        root_node.expanded = True
        root_node.setPos(x, y)
        self.scene.addItem(root_node)
        self.items[root_uid] = root_node

        for path in report.paths:
            for i in range(len(path.steps) - 1):
                u_step = path.steps[i]
                v_step = path.steps[i + 1]
                v_meta = meta.get(v_step.uid)
                v_label = v_meta.label if v_meta else v_step.uid
                v_lang = v_meta.lang if v_meta else None
                if v_step.uid not in self.items:
                    pos = self.layout_engine.place_children(u_step.uid, [v_step.uid])
                    v_node = NodeItem(
                        self, v_step.uid, v_label, v_lang, expandable=True, possible=v_step.possible
                    )
                    v_node.expanded = True
                    v_node.setPos(*pos[v_step.uid])
                    self.scene.addItem(v_node)
                    self.items[v_step.uid] = v_node
                edge_item = TreeItem(
                    v_step.uid,
                    v_label,
                    v_meta.kind if v_meta else "routine",
                    v_lang,
                    v_meta.file if v_meta else None,
                    v_step.edge_kind or "calls",
                    1,
                    v_step.confidence or "exact",
                    v_step.possible,
                    True,
                )
                self._add_directed_edge(self.items[u_step.uid], self.items[v_step.uid], edge_item)

        if report.showing_shortest_only:
            hops = max(0, len(report.paths[0].steps) - 1)
            self.info.setText(
                f"Multiple paths possible ({report.total_found}+ found) — "
                f"shortest path shown from main ({r_label}, {hops} link(s))"
            )
        elif report.multiple_possible:
            self.info.setText(
                f"Multiple paths possible ({report.total_found} paths shown from main {r_label})"
            )
        else:
            hops = max(0, len(report.paths[0].steps) - 1)
            self.info.setText(f"Paths to main ({r_label}) — unique path ({hops} link(s))")

    def expand(
        self,
        item: NodeItem,
        offset: int = 0,
        on_done: Callable[[], None] | None = None,
        *,
        gen: int | None = None,
    ) -> None:
        if self.db is None:
            return
        uid, direction, level, hide = item.uid, self.dir, self.lvl, self.hide_noise
        expected_gen = self._gen if gen is None else gen

        def work(q: GraphQuery) -> Page:
            return q.children(uid, direction=direction, level=level, offset=offset, limit=PAGE, hide_noise=hide)

        def done(page: Page) -> None:
            if expected_gen != self._gen:
                return
            self._add_children(item, page, offset)
            if on_done is not None:
                on_done()

        self.runner.submit(self.db, f"treegraph:{id(self)}:{uid}:{offset}:{expected_gen}", work, done)

    def _add_children(self, parent: NodeItem, page: Page, offset: int) -> None:
        parent.expanded = True
        parent.offset = offset + len(page.items)
        if len(self.items) + len(page.items) > self.max_nodes.value():
            self.info.setText(f"Limit of {self.max_nodes.value()} nodes reached: switch to file "
                              f"or directory level, or increase the limit.")
            return
        ids = []
        for child in page.items:
            seen = child.uid in self.items
            key = child.uid if not seen else f"{child.uid}@{parent.uid}"
            ids.append((key, child, seen))
        positions = self.layout_engine.place_children(parent.uid, [k for k, _c, _s in ids])
        for key, child, seen in ids:
            if key not in positions:
                continue
            node = NodeItem(self, child.uid, child.label, child.lang, seen=seen, expandable=child.has_children,
                            possible=child.possible)
            node.setPos(*positions[key])
            self.scene.addItem(node)
            if not seen:
                self.items[child.uid] = node
            caller_node, callee_node = (parent, node) if self.dir is Direction.CALLEES else (node, parent)
            if seen:
                self.scene.addItem(EdgeItem(caller_node, callee_node, child, self.file_level))
            else:
                self._add_directed_edge(caller_node, callee_node, child)
        remaining = page.total - parent.offset
        if remaining > 0:
            more_key = f"+more:{parent.uid}:{parent.offset}"
            pos = self.layout_engine.place_children(parent.uid, [more_key])
            more = NodeItem(self, more_key, f"+{remaining} more", None, more=remaining)
            more.setData(0, parent)
            more.setPos(*pos[more_key])
            self.scene.addItem(more)
        count = len(self.scene.items())
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, count <= 200)
        hidden = f", {page.hidden} utility(ies) hidden" if page.hidden else ""
        self.info.setText(f"{len(self.items)} node(s){hidden}")

    def edge_activated(self, edge: EdgeItem) -> None:
        self.sites_requested.emit(edge.src.uid, edge.dst.uid)

    def fit(self) -> None:
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)


