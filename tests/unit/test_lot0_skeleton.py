from __future__ import annotations

import socket
import subprocess
import sys

import pytest

from codegraph_sci.cli import main
from codegraph_sci.core import netguard
from codegraph_sci.core.versions import APP_VERSION


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert APP_VERSION in capsys.readouterr().out


def test_selftest_passes(capsys: pytest.CaptureFixture[str]) -> None:
    try:
        assert main(["selftest"]) == 0
    finally:
        netguard.uninstall()
    assert "selftest: PASSED" in capsys.readouterr().out


def test_netguard_blocks_inet() -> None:
    netguard.install()
    try:
        with pytest.raises(netguard.NetworkAccessError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    finally:
        netguard.uninstall()


def test_cli_runs_as_module() -> None:
    out = subprocess.run([sys.executable, "-m", "codegraph_sci", "--version"],
                         capture_output=True, text=True, check=True)
    assert APP_VERSION in out.stdout


def test_main_window_about(qtbot) -> None:  # type: ignore[no-untyped-def]
    from codegraph_sci.ui.main_window import ABOUT_TEXT, MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    assert win.windowTitle() == "CodeGraph-Sci"
    assert APP_VERSION in ABOUT_TEXT
