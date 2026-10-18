"""Window chrome of the main window: frameless title bar, resize margins, popovers and the hero card."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from codegraph_sci.ui.theme import icon

RESIZE_MARGIN = 5


def elastic(label: QLabel, *, wrap: bool = True) -> QLabel:
    """A label whose text never widens the window: it wraps (or is clipped) to the space it gets."""
    label.setWordWrap(wrap)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label
BADGE_SIZE = 48


class TitleBar(QFrame):
    """28 px orange title bar: title on the left, minimise / maximise / close on the right; drag moves the window."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.setObjectName("TitleBar")
        self.window_ = window
        self.setFixedHeight(28)
        self.title = elastic(QLabel("CodeGraph-Sci"), wrap=False)  # a long project path never widens the window
        self.btn_min = self._button("—", "Minimize", window.showMinimized)
        self.btn_max = self._button("□", "Maximize", self.toggle_maximized)
        self.btn_close = self._button("✕", "Close", window.close)
        self.btn_close.setObjectName("CloseButton")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title, 1)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(b)

    def _button(self, text: str, tip: str, slot: Any) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setFixedHeight(28)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(slot)
        return b

    def toggle_maximized(self) -> None:
        if self.window_.isMaximized():
            self.window_.showNormal()
        else:
            self.window_.showMaximized()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        handle = self.window_.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()


class ResizeFrame(QWidget):
    """Central widget of a frameless window: its thin outer margin resizes the window (system resize)."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window_ = window
        self.setMouseTracking(True)
        self.setContentsMargins(RESIZE_MARGIN, 0, RESIZE_MARGIN, RESIZE_MARGIN)

    def update_margins(self) -> None:
        m = 0 if self.window_.isMaximized() else RESIZE_MARGIN
        self.setContentsMargins(m, 0, m, m)

    def _edges(self, pos: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        if self.window_.isMaximized():
            return edges
        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() >= self.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        edges = self._edges(event.position().toPoint())
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & Qt.Edge.BottomEdge)
        if horizontal and vertical:
            left = bool(edges & Qt.Edge.LeftEdge)
            self.setCursor(Qt.CursorShape.SizeBDiagCursor if left else Qt.CursorShape.SizeFDiagCursor)
        elif horizontal:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif vertical:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        edges = self._edges(event.position().toPoint())
        handle = self.window_.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and edges != Qt.Edge(0) and handle is not None:
            handle.startSystemResize(edges)
            return
        super().mousePressEvent(event)


class Popover(QFrame):
    """Floating dark grid of options, opened under the square button that owns it."""

    def __init__(self, parent: QWidget, title: str, columns: int = 2) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popover")
        self.columns = columns
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.addWidget(QLabel(title.upper()))
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(8)
        outer.addLayout(self.grid)
        self._count = 0

    def add(self, widget: QWidget, span: int = 1) -> None:
        if self._count % self.columns + span > self.columns:
            self._count += self.columns - self._count % self.columns
        self.grid.addWidget(widget, self._count // self.columns, self._count % self.columns, 1, span)
        self._count += span

    def show_under(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        self.move(pos)
        self.show()


class HeroCard(QFrame):
    """Rounded orange banner showing the selected entity, with 48 x 48 dark badges and buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self.title = elastic(QLabel("CodeGraph-Sci"), wrap=False)
        self.title.setObjectName("HeroTitle")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle = elastic(QLabel("Select a routine: search, file explorer or a click in a graph."))
        self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary = elastic(QLabel(""))
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        text.addWidget(self.summary)
        self.badge_callers = self._square("—\ncallers", "Callers of the selection (show the list)")
        self.badge_callees = self._square("—\ncallees", "Callees of the selection (show the list)")
        self.btn_view = self._square("", "Show the selection in a view", "cube")
        self.btn_filters = self._square("", "Filters of the Callers / Callees panel (Ctrl+Shift+F)", "filter")
        self.btn_analysis = self._square("", "Analysis and analysis profile", "play")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(text, 1)
        for b in (self.badge_callers, self.badge_callees, self.btn_view, self.btn_filters, self.btn_analysis):
            layout.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)

    def _square(self, text: str, tip: str, icon_name: str | None = None) -> QToolButton:
        b = QToolButton(self)
        b.setFixedSize(BADGE_SIZE, BADGE_SIZE)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # reachable with Tab (UI audit)
        if icon_name:
            b.setIcon(icon(icon_name))
            b.setIconSize(QSize(22, 22))
        else:
            b.setText(text)
        return b

    def set_counts(self, callers: int | None, callees: int | None) -> None:
        self.badge_callers.setText(f"{'—' if callers is None else callers}\ncallers")
        self.badge_callees.setText(f"{'—' if callees is None else callees}\ncallees")
