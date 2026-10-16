# PyInstaller spec: two executables (desktop app + CLI) sharing one _internal/ folder.
# "onedir" mode only: one-file mode unpacks at every start, too slow from a USB key.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
datas = collect_data_files("codegraph_sci", includes=["**/*.yaml", "**/*.json", "**/*.sql"])
binaries = []
hidden = ["tree_sitter", "tree_sitter_fortran", "tree_sitter_python", "tree_sitter_c", "tree_sitter_cpp"]
for mod in hidden[1:]:
    binaries += collect_dynamic_libs(mod)
excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtNetwork"]

cli_a = Analysis([str(ROOT / "packaging/entry/cgs_entry.py")], pathex=[str(SRC)], datas=datas,
                 binaries=binaries, hiddenimports=hidden, excludes=excludes)
gui_a = Analysis([str(ROOT / "packaging/entry/gui_entry.py")], pathex=[str(SRC)], datas=datas,
                 binaries=binaries, hiddenimports=hidden, excludes=excludes)

cli_pyz = PYZ(cli_a.pure)
gui_pyz = PYZ(gui_a.pure)
cli_exe = EXE(cli_pyz, cli_a.scripts, [], exclude_binaries=True, name="cgs", console=True)
gui_exe = EXE(gui_pyz, gui_a.scripts, [], exclude_binaries=True, name="CodeGraph-Sci", console=False)

COLLECT(gui_exe, gui_a.binaries, gui_a.datas, cli_exe, cli_a.binaries, cli_a.datas,
        name="CodeGraph-Sci")
