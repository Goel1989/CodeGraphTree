"""Desktop application entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from codegraph_sci.core import netguard
from codegraph_sci.ui.main_window import MainWindow  # imports QtWebEngine before the QApplication exists


def main(argv: Sequence[str] | None = None) -> int:
    netguard.install()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)  # required by the 3D views
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("CodeGraph-Sci")
    app.setOrganizationName("CodeGraph-Sci")
    window = MainWindow()
    window.show()
    code = app.exec()
    del window  # the 3D pages (QtWebEngine) must be destroyed before the QApplication
    return code


if __name__ == "__main__":
    sys.exit(main())
