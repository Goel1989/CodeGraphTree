"""Qt models: lazy call tree (pages of 50 children, "+N more", "↺ already shown") and file explorer.

The call tree holds no database connection: each page is loaded by the query runner in a background thread and
inserted when it arrives ("loading…" until then), so expanding a node never blocks the window (UI audit).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel

from codegraph_sci.query.api import GraphQuery
from codegraph_sci.query.types import Direction, Level, Page, TreeItem
from codegraph_sci.ui.workers import QueryRunner

PAGE = 50
LANG_COLORS = {"fortran": "#B392F0", "python": "#79B8FF", "c": "#C0C6CC", "cpp": "#F0883E", None: "#9E9E9E"}
Index = QModelIndex | QPersistentModelIndex


@dataclass
class _Node:
    uid: str
    label: str
    parent: _Node | None
    item: TreeItem | None = None
    children: list[_Node] = field(default_factory=list)
    total: int | None = None  # number of children known after the first page
    loaded: int = 0
    seen: bool = False  # already shown elsewhere in the tree: not expanded again
    more: bool = False  # the "+N more" placeholder row
    loading: bool = False  # a page of its children is being loaded

    def row(self) -> int:
        return self.parent.children.index(self) if self.parent else 0


class CallTreeModel(QAbstractItemModel):
    """Text version of the TreeGraph: callees or callers of a routine, expanded node by node."""

    def __init__(self, runner: QueryRunner, db: Path, root_uid: str, root_label: str, direction: Direction, *,
                 hide_noise: bool = True, level: Level = Level.ROUTINE) -> None:
        super().__init__()
        self.runner = runner
        self.db = db
        self.direction = direction
        self.hide_noise = hide_noise
        self.level = level
        self.closed = False
        self.root = _Node("", "", None)
        top = _Node(root_uid, root_label, self.root)
        self.root.children = [top]
        self.shown: set[str] = {root_uid}

    def close(self) -> None:
        """Pages that arrive afterwards are ignored (the model was replaced)."""
        self.closed = True

    # --------------------------------------------------------------- tree
    def _node(self, index: Index) -> _Node:
        if index.isValid():
            node = index.internalPointer()
            assert isinstance(node, _Node)
            return node
        return self.root

    def index(self, row: int, column: int, parent: Index = QModelIndex()) -> QModelIndex:  # noqa: B008
        node = self._node(parent)
        if 0 <= row < len(node.children):
            return self.createIndex(row, column, node.children[row])
        return QModelIndex()

    def parent(self, index: Index = QModelIndex()) -> QModelIndex:  # type: ignore[override]  # noqa: B008
        if not index.isValid():
            return QModelIndex()
        node = self._node(index)
        if node.parent is None or node.parent is self.root:
            return QModelIndex()
        return self.createIndex(node.parent.row(), 0, node.parent)

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008
        return len(self._node(parent).children)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008
        return 3

    def hasChildren(self, parent: Index = QModelIndex()) -> bool:  # noqa: N802, B008
        node = self._node(parent)
        if node is self.root:
            return True
        if node.seen or node.more:
            return False
        if node.total is not None:
            return bool(node.children)
        return node.item is None or node.item.has_children

    def canFetchMore(self, parent: Index) -> bool:  # noqa: N802
        node = self._node(parent)
        if node is self.root or node.seen or node.more or node.loading:
            return False
        return node.total is None

    def fetchMore(self, parent: Index) -> None:  # noqa: N802
        node = self._node(parent)
        self._load(parent, node, 0)

    def _load(self, parent_index: Index, node: _Node, offset: int) -> None:
        """Ask the runner for a page of children; they are inserted by ``_insert`` when the page arrives."""
        if node.loading or self.closed:
            return
        node.loading = True
        persistent = QPersistentModelIndex(parent_index)
        uid, direction, level, hide = node.uid, self.direction, self.level, self.hide_noise

        def work(q: GraphQuery) -> Page[TreeItem]:
            return q.children(uid, direction=direction, level=level, offset=offset, limit=PAGE, hide_noise=hide)

        def failed(_message: str) -> None:
            node.loading = False

        self.runner.submit(self.db, f"tree:{id(self)}:{uid}:{offset}", work,
                           lambda page: self._insert(persistent, node, offset, page), failed)

    def _insert(self, parent_index: QPersistentModelIndex, node: _Node, offset: int, page: Page[TreeItem]) -> None:
        node.loading = False
        if self.closed:
            return
        if not parent_index.isValid():
            return  # the row disappeared meanwhile (its parent was collapsed into a new model)
        index = QModelIndex(parent_index)
        new: list[_Node] = []
        for item in page.items:
            child = _Node(item.uid, item.label, node, item)
            if item.uid in self.shown:
                child.seen = True
            else:
                self.shown.add(item.uid)
            new.append(child)
        remaining = page.total - offset - len(page.items)
        if remaining > 0:
            new.append(_Node(f"+more:{node.uid}:{offset + PAGE}", f"+{remaining} more", node, more=True))
        start = len(node.children)
        if new:
            self.beginInsertRows(index, start, start + len(new) - 1)
        node.children.extend(new)
        node.total = page.total
        node.loaded = offset + len(page.items)
        if new:
            self.endInsertRows()
        else:
            self.dataChanged.emit(index, index)  # no child: the expander disappears

    def expand_more(self, index: QModelIndex) -> None:
        """Replace a "+N more" row by the next page."""
        node = self._node(index)
        if not node.more or node.parent is None:
            return
        parent = node.parent
        parent_index = self.parent(index)
        row = node.row()
        self.beginRemoveRows(parent_index, row, row)
        parent.children.pop(row)
        self.endRemoveRows()
        self._load(parent_index, parent, parent.loaded)

    def node_uid(self, index: QModelIndex) -> str | None:
        node = self._node(index)
        return None if node.more or node is self.root else node.uid

    # --------------------------------------------------------------- data
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("Routine", "Calls", "File")[section]
        return None

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node = self._node(index)
        item = node.item
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                label = node.label
                if node.loading:
                    label += "  (loading…)"
                if node.seen:
                    label += "  ↺ already shown"
                if item is not None and item.possible:
                    label += "  (possible)"
                return label
            if col == 1:
                return "" if item is None else f"{item.count} ({item.edge_kind})"
            if col == 2:
                return "" if item is None else (item.file or "")
        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            if node.more or node.seen:
                return QBrush(QColor("#888888"))
            return QBrush(QColor(LANG_COLORS.get(item.lang if item else None, "#FFFFFF")))
        if role == Qt.ItemDataRole.ToolTipRole:
            return node.uid if not node.more else "Double-click to show more"
        return None


class FileTreeModel(QStandardItemModel):
    """Repository tree with, per file, its language, routines and linked files."""

    PATH_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, files: list[dict[str, Any]]) -> None:
        super().__init__()
        self.setHorizontalHeaderLabels(["File", "Language", "Routines", "Links"])
        dirs: dict[str, QStandardItem] = {}
        root = self.invisibleRootItem()

        def folder(path: str) -> QStandardItem:
            if not path:
                return root
            if path not in dirs:
                parent = folder(posixpath.dirname(path))
                item = QStandardItem(posixpath.basename(path))
                item.setEditable(False)
                item.setData(f"dir:{path}", self.PATH_ROLE)
                parent.appendRow([item, QStandardItem(""), QStandardItem(""), QStandardItem("")])
                dirs[path] = item
            return dirs[path]

        for f in files:
            parent = folder(posixpath.dirname(f["path"]))
            name = QStandardItem(posixpath.basename(f["path"]))
            name.setData(f["path"], self.PATH_ROLE)
            name.setForeground(QBrush(QColor(LANG_COLORS.get(f["lang"], "#FFFFFF"))))
            if f["status"] in ("failed", "fallback"):
                name.setToolTip(f"Analysis: {f['status']}")
            row = [name, QStandardItem(f["lang"] or "-"), QStandardItem(str(f["routines"] or "")),
                   QStandardItem(str(f["links"] or ""))]
            for it in row:
                it.setEditable(False)
            parent.appendRow(row)

