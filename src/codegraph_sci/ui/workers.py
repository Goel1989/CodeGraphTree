"""Background work for the desktop app: queries in a thread pool, analysis in a sub-process (§3.11).

The main thread never runs a long query and never reads source files for the analysis.
Each query opens its own read-only SQLite connection.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QRunnable, QThreadPool, Signal

from codegraph_sci.query.api import GraphQuery


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class QueryTask(QRunnable):
    """Runs ``fn(GraphQuery)`` in the Qt thread pool, then emits the result."""

    def __init__(self, db_path: Path, fn: Callable[[GraphQuery], Any]) -> None:
        super().__init__()
        self.db_path = db_path
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            with GraphQuery(self.db_path) as q:
                result = self.fn(q)
        except Exception as exc:  # noqa: BLE001 - reported to the window
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
            return
        self.signals.done.emit(result)


class QueryRunner(QObject):
    """Keeps running tasks alive and drops results of superseded requests (same ``key``)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self.generation: dict[str, int] = {}
        self.tasks: set[QueryTask] = set()

    def cancel_all(self) -> None:
        """Drop every pending answer. Generations only grow: a request made after the cancellation can never
        accept an answer of a request made before it (UI audit, UI-02)."""
        for key in self.generation:
            self.generation[key] += 1

    def submit(self, db: Path, key: str, fn: Callable[[GraphQuery], Any], on_done: Callable[[Any], None],
               on_error: Callable[[str], None] | None = None) -> None:
        gen = self.generation.get(key, 0) + 1
        self.generation[key] = gen
        task = QueryTask(db, fn)
        self.tasks.add(task)

        def finished(result: Any) -> None:
            self.tasks.discard(task)
            if self.generation.get(key) == gen:
                try:
                    on_done(result)
                except RuntimeError:
                    pass

        def failed(message: str) -> None:
            self.tasks.discard(task)
            if on_error is not None and self.generation.get(key) == gen:
                try:
                    on_error(message)
                except RuntimeError:
                    pass

        task.signals.done.connect(finished)
        task.signals.failed.connect(failed)
        self.pool.start(task)


def cgs_command() -> tuple[str, list[str]]:
    """Program and base arguments to run the ``cgs`` command line (portable folder or development)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).with_name("cgs.exe" if sys.platform == "win32" else "cgs")
        return str(exe), []
    return sys.executable, ["-m", "codegraph_sci"]


def kill_tree(pid: int) -> None:
    """Kill a process and every process it started (the extraction workers of ``cgs scan``)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)  # the command runs in its own process group (see start)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


class CgsProcess(QObject):
    """``cgs inventory`` / ``cgs scan`` as a sub-process; one JSON progress event per line."""

    event = Signal(dict)
    finished = Signal(int, str)  # exit code, last error output

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self._buffer = ""
        self._stderr = ""

    def start(self, args: list[str]) -> None:
        program, base = cgs_command()
        self._buffer = ""
        self._stderr = ""
        if sys.platform != "win32" and hasattr(self.proc, "setChildProcessModifier"):
            self.proc.setChildProcessModifier(os.setsid)  # own process group: Cancel kills it with its workers
        self.proc.start(program, base + args)

    def running(self) -> bool:
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def cancel(self, *, wait: bool = False) -> None:
        """Kill the command; with ``wait``, return once it is finished (its ``finished`` signal already sent)."""
        if self.running():
            pid = int(self.proc.processId())
            if pid > 0:
                kill_tree(pid)  # the command and its extraction workers
            self.proc.kill()
            if wait:
                self.proc.waitForFinished(5000)

    def _read(self) -> None:
        self._buffer += bytes(self.proc.readAllStandardOutput().data()).decode("utf-8", errors="replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line.startswith("{"):
                try:
                    self.event.emit(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def _error(self, error: QProcess.ProcessError) -> None:
        """A command that cannot start never sends ``finished``: report it as a failure (the UI must not wait)."""
        if error == QProcess.ProcessError.FailedToStart:
            self.finished.emit(-1, f"the command could not start: {self.proc.errorString()}")

    def _finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        self._read()
        self._stderr = bytes(self.proc.readAllStandardError().data()).decode("utf-8", errors="replace")
        self.finished.emit(code, self._stderr[-4000:])
