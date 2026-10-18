"""Qt models: the file explorer (repository tree, per file its language, routines and linked files)."""

from __future__ import annotations

import posixpath
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel

LANG_COLORS = {"fortran": "#B392F0", "python": "#79B8FF", "c": "#C0C6CC", "cpp": "#F0883E", None: "#9E9E9E"}


class FileTreeModel(QStandardItemModel):
    """Repository tree with, per file, its language, routines and linked files (dependents and dependencies)."""

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

