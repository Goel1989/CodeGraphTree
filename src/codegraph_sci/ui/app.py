"""Desktop application entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from codegraph_sci.core import netguard
from codegraph_sci.ui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    netguard.install()
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("CodeGraph-Sci")
    app.setOrganizationName("CodeGraph-Sci")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
