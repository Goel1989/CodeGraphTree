from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # the embedded 3D views (QtWebEngine) must be set up before pytest-qt creates the QApplication
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
except ImportError:  # pragma: no cover - PySide6 without QtWebEngine
    pass

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CGS_DATA_DIR", str(tmp_path_factory.mktemp("cgs-data")))


@pytest.fixture(scope="session", autouse=True)
def _delete_widgets_before_exit() -> Iterator[None]:
    """QtWebEngine pages must be destroyed while the QApplication still exists, or the process crashes at exit."""
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
