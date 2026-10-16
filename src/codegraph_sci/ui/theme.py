"""Dark & orange theme of the desktop application: colours, Qt palette, style sheet and painted icons."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

BG = "#181818"  # main background and details panel
PANEL = "#222222"  # secondary panels
PANEL_2 = "#2C2C2C"
RAIL = "#202020"  # icon rail
NAV = "#282828"  # secondary list buttons
POPOVER = "#2B2B2B"
HEADER = "#0A0A0A"  # header bands
BORDER = "#3A3A3A"
TEXT = "#FFFFFF"
MUTED = "#9E9E9E"
ACCENT = "#E06310"
GRAD_A = "#E87A24"  # orange gradient (title bar, active item, hero card)
GRAD_B = "#C85208"
GRADIENT = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {GRAD_A}, stop:1 {GRAD_B})"

# Code inspector on a dark background.
SITE_RESOLVED = "#1F3A5F"
SITE_UNRESOLVED = "#5A1F1F"
CURRENT_LINE = "#4A3410"

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 9pt; }}
QToolTip {{ background: {POPOVER}; color: {TEXT}; border: 1px solid {BORDER}; }}
#TitleBar {{ background: {GRADIENT}; }}
#TitleBar QLabel {{ background: transparent; font-weight: bold; }}
#TitleBar QToolButton {{ background: transparent; border: 0; color: {TEXT}; min-width: 40px; font-size: 10pt; }}
#TitleBar QToolButton:hover {{ background: rgba(0, 0, 0, 0.18); }}
#TitleBar QToolButton#CloseButton:hover {{ background: #B3261E; }}
#Rail {{ background: {RAIL}; border-right: 1px solid {BORDER}; }}
#Rail QToolButton {{ background: transparent; border: 2px solid transparent; border-radius: 4px; }}
#Rail QToolButton:hover {{ background: {PANEL_2}; }}
#Rail QToolButton:checked {{ border: 2px solid {ACCENT}; }}
#NavColumn {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
#NavColumn QLabel {{ background: transparent; color: {MUTED}; font-weight: bold; }}
QPushButton#NavButton {{ background: {NAV}; border: 1px solid {BORDER}; border-radius: 0; padding: 8px 10px;
                         text-align: left; color: {TEXT}; }}
QPushButton#NavButton:hover {{ border-color: {ACCENT}; }}
QPushButton#NavButton:checked {{ background: {GRADIENT}; font-weight: bold; border-color: {GRAD_B}; }}
#HeaderBand {{ background: {HEADER}; border-bottom: 1px solid {BORDER}; }}
#HeaderBand QLabel {{ background: transparent; font-size: 11pt; font-weight: bold; letter-spacing: 1px; }}
#HeroCard {{ background: {GRADIENT}; border-radius: 10px; }}
#HeroCard QLabel {{ background: transparent; }}
#HeroCard QLabel#HeroTitle {{ font-size: 15pt; font-weight: bold; }}
#HeroCard QToolButton {{ background: rgba(10, 10, 10, 0.82); border: 1px solid rgba(0, 0, 0, 0.5);
                         border-radius: 4px; color: {TEXT}; font-weight: bold; }}
#HeroCard QToolButton:hover {{ background: {HEADER}; border-color: {TEXT}; }}
#Popover {{ background: {POPOVER}; border: 1px solid {BORDER}; }}
#Popover QWidget {{ background: {POPOVER}; }}
#Popover QLabel {{ color: {MUTED}; font-weight: bold; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 3px; padding: 5px 10px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #666666; }}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: {PANEL}; border: 1px solid {BORDER};
    border-radius: 3px; padding: 3px 5px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {POPOVER}; selection-background-color: {ACCENT}; }}
QCheckBox {{ background: transparent; spacing: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER}; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTreeView, QListWidget, QTableWidget, QTreeWidget {{ background: {PANEL}; alternate-background-color: {PANEL_2};
    border: 1px solid {BORDER}; selection-background-color: {ACCENT}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: {HEADER}; color: {MUTED}; border: 0; border-right: 1px solid {BORDER};
    padding: 4px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {NAV}; color: {MUTED}; padding: 5px 12px; border: 1px solid {BORDER}; }}
QTabBar::tab:selected {{ background: {PANEL_2}; color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollBar {{ background: {BG}; width: 10px; height: 10px; }}
QScrollBar::handle {{ background: #4A4A4A; border-radius: 4px; min-height: 20px; min-width: 20px; }}
QScrollBar::handle:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QStatusBar {{ background: {HEADER}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; }}
QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QMessageBox, QInputDialog, QFileDialog {{ background: {PANEL}; }}
"""


def apply_palette(app: QApplication) -> None:
    """Fusion style and a dark palette, so that native parts (dialogs, menus) match the style sheet."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.ColorRole.Window, PANEL), (QPalette.ColorRole.WindowText, TEXT),
                        (QPalette.ColorRole.Base, PANEL), (QPalette.ColorRole.AlternateBase, PANEL_2),
                        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, PANEL_2),
                        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
                        (QPalette.ColorRole.HighlightedText, TEXT), (QPalette.ColorRole.ToolTipBase, POPOVER),
                        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, MUTED)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)


def icon(name: str, color: str = TEXT, size: int = 24) -> QIcon:
    """Small line icons drawn with QPainter (no image file, same look on every platform)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    s = size / 24.0
    p.scale(s, s)
    if name == "folder":
        path = QPainterPath()
        path.moveTo(3, 7)
        path.lineTo(3, 19)
        path.lineTo(21, 19)
        path.lineTo(21, 9)
        path.lineTo(11, 9)
        path.lineTo(9, 6)
        path.lineTo(3, 6)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "graph":
        pts = [QPointF(6, 6), QPointF(18, 8), QPointF(8, 18), QPointF(17, 17)]
        for a, b in ((0, 1), (0, 2), (1, 3), (2, 3), (0, 3)):
            p.drawLine(pts[a], pts[b])
        p.setBrush(QColor(color))
        for pt in pts:
            p.drawEllipse(pt, 2.4, 2.4)
    elif name == "project":
        for y in (6, 12, 18):
            p.drawLine(QPointF(9, y), QPointF(20, y))
            p.drawRect(QRectF(3.5, y - 1.5, 3, 3))
    elif name == "info":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        p.drawLine(QPointF(12, 11), QPointF(12, 17))
        p.drawPoint(QPointF(12, 7.5))
    elif name == "filter":
        path = QPainterPath()
        path.moveTo(4, 5)
        path.lineTo(20, 5)
        path.lineTo(14, 12)
        path.lineTo(14, 19)
        path.lineTo(10, 17)
        path.lineTo(10, 12)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "play":
        path = QPainterPath()
        path.moveTo(8, 5)
        path.lineTo(19, 12)
        path.lineTo(8, 19)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "cube":
        path = QPainterPath()
        for a, b in (((12, 3), (20, 7.5)), ((20, 7.5), (20, 16.5)), ((20, 16.5), (12, 21)), ((12, 21), (4, 16.5)),
                     ((4, 16.5), (4, 7.5)), ((4, 7.5), (12, 3)), ((4, 7.5), (12, 12)), ((12, 12), (20, 7.5)),
                     ((12, 12), (12, 21))):
            path.moveTo(*a)
            path.lineTo(*b)
        p.drawPath(path)
    p.end()
    return QIcon(pix)
