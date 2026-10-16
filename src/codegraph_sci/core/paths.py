"""Location of the user data directory (projects, settings)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "CodeGraph-Sci"


def install_dir() -> Path:
    """Directory of the running application (portable folder when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def is_portable_mode() -> bool:
    """Portable mode: data is written in ``data/`` next to the application."""
    if os.environ.get("CGS_PORTABLE") == "1":
        return True
    return (install_dir() / "data" / "portable.flag").is_file()


def data_dir() -> Path:
    """User data directory; created on demand."""
    override = os.environ.get("CGS_DATA_DIR")
    if override:
        path = Path(override)
    elif is_portable_mode():
        path = install_dir() / "data"
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_DIR_NAME
    else:
        path = Path.home() / ".codegraph-sci"
    path.mkdir(parents=True, exist_ok=True)
    return path
