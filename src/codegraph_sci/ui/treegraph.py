"""TreeGraph views (§1.2, §3.11, §3.12): calls of a routine or links of a file/directory, drawn as a tree.

Expanded node by node (double-click); pages of 50 children with a "+N" node; nodes already
shown elsewhere are marked "↺" and not expanded again; hubs hidden by default; at most
``max_nodes`` drawn; labels dropped when zoomed out; no antialiasing on large views.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QWheelEvent
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
from codegraph_sci.query.types import Direction, Level, Page, TreeItem
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
        self.setToolTip(uid if not more else f"{more} autres — double-cliquer pour afficher la suite")
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

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        self.view.activate(self)


class EdgeItem(QGraphicsLineItem):
    def __init__(self, src: NodeItem, dst: NodeItem, item: TreeItem | None, file_level: bool) -> None:
        start = src.pos() + QPointF(NODE_W, 0)
        end = dst.pos()
        super().__init__(start.x(), start.y(), end.x(), end.y())
        self.src, self.dst, self.item = src, dst, item
        width = 1.0
        if item is not None and file_level:
            width = min(8.0, 1.0 + item.count ** 0.5)
        pen = QPen(QColor("#718096"), width)
        if item is not None and (item.possible or item.edge_kind in ("bridges", "binds")):
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setColor(QColor("#c05621"))
        self.setPen(pen)
        self.setZValue(-1)
        if item is not None:
            self.setToolTip(f"{item.edge_kind} — {item.count} appel(s) — {item.confidence}")

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        view = self.src.view
        view.edge_activated(self)


class GraphView(QGraphicsView):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class TreeGraphView(QWidget):
    """One TreeGraph (functions or files); the main window gives the database and the root."""

    node_selected = Signal(str)
    sites_requested = Signal(str, str)  # (src uid, dst uid) for the detailed calls of a link

    def __init__(self, runner: QueryRunner, file_level: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runner = runner
        self.file_level = file_level
        self.db: Path | None = None
        self.root_uid: str | None = None
        self.hide_noise = True
        self.layout_engine = TreeLayout()
        self.items: dict[str, NodeItem] = {}
        self.scene = QGraphicsScene(self)
        self.view = GraphView(self.scene)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setFont(QFont("Segoe UI", 9))
        self.direction = QComboBox()
        self.direction.addItems(["Appelés", "Appelants"] if not file_level else ["Fichiers utilisés", "Utilisé par"])
        self.direction.currentIndexChanged.connect(self.rebuild)
        self.level = QComboBox()
        self.level.addItems(["Routine"] if not file_level else ["Fichier", "Répertoire"])
        self.level.currentIndexChanged.connect(self.rebuild)
        self.max_nodes = QSpinBox()
        self.max_nodes.setRange(50, 5000)
        self.max_nodes.setValue(300)
        self.info = QLabel("")
        fit = QPushButton("Ajuster")
        fit.clicked.connect(self.fit)
        top = QHBoxLayout()
        for w in (QLabel("Sens :"), self.direction, QLabel("Niveau :"), self.level, QLabel("Nœuds max :"),
                  self.max_nodes, fit):
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

    def set_root(self, db: Path, uid: str, label: str, lang: str | None) -> None:
        self.db = db
        self.root_uid = uid
        self.root_label = label
        self.root_lang = lang
        self.rebuild()

    def rebuild(self) -> None:
        self.scene.clear()
        self.items = {}
        if self.db is None or self.root_uid is None:
            return
        root = self.root_uid
        label = self.root_label
        if self.lvl is Level.DIRECTORY and root.startswith("file:"):
            path = root[5:]
            root = path.rsplit("/", 1)[0] if "/" in path else "."
            label = root
        self.layout_engine = TreeLayout()
        x, y = self.layout_engine.place_root(root)
        item = NodeItem(self, root, label, self.root_lang)
        item.setPos(x, y)
        self.scene.addItem(item)
        self.items[root] = item
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.expand(item)

    # ---------------------------------------------------------- expansion
    def activate(self, item: NodeItem) -> None:
        if item.more:
            parent = item.data(0)
            self.scene.removeItem(item)
            if isinstance(parent, NodeItem):
                self.expand(parent, parent.offset)
            return
        if not item.expanded and item.expandable:
            self.expand(item)
        if not self.file_level:
            self.node_selected.emit(item.uid)

    def expand(self, item: NodeItem, offset: int = 0, on_done: Callable[[], None] | None = None) -> None:
        if self.db is None:
            return
        uid, direction, level, hide = item.uid, self.dir, self.lvl, self.hide_noise

        def work(q: GraphQuery) -> Page:
            return q.children(uid, direction=direction, level=level, offset=offset, limit=PAGE, hide_noise=hide)

        def done(page: Page) -> None:
            self._add_children(item, page, offset)
            if on_done is not None:
                on_done()

        self.runner.submit(self.db, f"treegraph:{id(self)}:{uid}:{offset}", work, done)

    def _add_children(self, parent: NodeItem, page: Page, offset: int) -> None:
        parent.expanded = True
        parent.offset = offset + len(page.items)
        if len(self.items) + len(page.items) > self.max_nodes.value():
            self.info.setText(f"Plafond de {self.max_nodes.value()} nœuds atteint : passer au niveau fichier "
                              f"ou répertoire, ou augmenter le plafond.")
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
            self.scene.addItem(EdgeItem(parent, node, child, self.file_level))
        remaining = page.total - parent.offset
        if remaining > 0:
            more_key = f"+more:{parent.uid}:{parent.offset}"
            pos = self.layout_engine.place_children(parent.uid, [more_key])
            more = NodeItem(self, more_key, f"+{remaining} autres", None, more=remaining)
            more.setData(0, parent)
            more.setPos(*pos[more_key])
            self.scene.addItem(more)
        count = len(self.scene.items())
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, count <= 200)
        hidden = f", {page.hidden} utilitaire(s) masqué(s)" if page.hidden else ""
        self.info.setText(f"{len(self.items)} nœud(s){hidden}")

    def edge_activated(self, edge: EdgeItem) -> None:
        self.sites_requested.emit(edge.src.uid, edge.dst.uid)

    def fit(self) -> None:
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
