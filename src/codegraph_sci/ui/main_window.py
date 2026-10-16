"""Main window."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox

from codegraph_sci.core.versions import APP_VERSION

ABOUT_TEXT = (
    f"<h3>CodeGraph-Sci {APP_VERSION}</h3>"
    "<p>Explorateur de graphes d'appels pour le code scientifique multi-langages "
    "(Fortran, Python, C, C++).</p>"
    "<p>Application 100 % hors ligne.</p>"
    "<p>Code source public sous licence PolyForm Noncommercial 1.0.0 ; "
    "licence commerciale distincte.</p>"
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CodeGraph-Sci")
        self.resize(1200, 800)
        self.setCentralWidget(QLabel("Aucun projet ouvert."))
        help_menu = self.menuBar().addMenu("&Aide")
        about = help_menu.addAction("À &propos de CodeGraph-Sci")
        about.triggered.connect(self.show_about)

    def show_about(self) -> None:
        QMessageBox.about(self, "À propos de CodeGraph-Sci", ABOUT_TEXT)
