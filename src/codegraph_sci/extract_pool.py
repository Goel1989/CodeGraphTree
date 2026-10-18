"""Extraction in worker processes with a deadline per file (rule 12, corrective audit P1 §4).

Each task records its id, file, start time, deadline, worker process and status. A task past its deadline
kills only its own worker, which is replaced; the other tasks keep running. The clock of a task starts when an
initialized worker receives it, so worker start-up (imports, grammars) is never charged to a file. A crash in
an extractor is reported for its file; a worker that dies is replaced. Results arrive through ``on_done`` in
completion order; callers sort what they keep (determinism). A worker exits as soon as its parent process is gone
(killed by a cancellation, crashed), even in the middle of a file: no extraction outlives the analysis.
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from typing import Any

TIMEOUT_PREFIX = "timeout after"
STARTUP_TIMEOUT_S = 120.0  # a worker that cannot even start (imports) is an internal error
POLL_S = 0.25  # cancellation is checked at least this often

Job = Callable[..., tuple[str, bytes | None, str | None]]
OnDone = Callable[[str, bytes | None, str | None], None]


@dataclass
class Task:
    task_id: int
    path: str
    args: tuple[Any, ...]
    started_at: float = 0.0
    deadline: float = 0.0
    pid: int | None = None
    status: str = "pending"  # pending, assigned, running, done, timeout, crashed
    finished_at: float = 0.0


class WorkerStartError(RuntimeError):
    """A worker process did not start within STARTUP_TIMEOUT_S."""


def _exit_with_parent() -> None:
    """Watch the parent process from a daemon thread and leave at once when it disappears."""
    parent = mp.parent_process()
    if parent is None:
        return

    def watch() -> None:
        wait([parent.sentinel])
        os._exit(1)  # noqa: SLF001 - the job may be stuck in C code: no clean-up is possible nor needed

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


def _worker_main(conn: Connection, init: Callable[..., None] | None, init_args: tuple[Any, ...], job: Job) -> None:
    _exit_with_parent()
    if init is not None:
        init(*init_args)
    conn.send(("ready", None))
    while True:
        message = conn.recv()
        if message is None:
            break
        task_id, args = message
        conn.send(("started", (task_id, time.perf_counter())))
        try:
            result = job(*args)
        except Exception as exc:  # noqa: BLE001 - an extractor bug fails its file, never the pool
            result = (args[0], None, f"{type(exc).__name__}: {exc}")
        conn.send((task_id, (time.perf_counter(), result)))


@dataclass
class _Worker:
    process: BaseProcess
    conn: Any  # Connection, or PipeConnection on Windows (not a Connection subclass for the type checker)
    ready: bool = False
    task: Task | None = None
    spawned_at: float = 0.0


def run_tasks(jobs: Sequence[tuple[Any, ...]], *, workers: int, timeout_s: float, on_done: OnDone, job: Job,
              init: Callable[..., None] | None = None, init_args: tuple[Any, ...] = (),
              check: Callable[[], None] | None = None) -> list[Task]:
    """Run ``job(*args)`` for every args tuple (``args[0]`` is the file path) with a deadline per task.

    ``check`` is called regularly and may raise to cancel (the workers are then stopped).
    """
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be finite and greater than zero")
    if not jobs:
        return []
    ctx = mp.get_context("spawn")
    pending: deque[Task] = deque(Task(i, str(args[0]), tuple(args)) for i, args in enumerate(jobs))
    tasks = list(pending)
    pool: list[_Worker] = []

    def spawn() -> _Worker:
        parent, child = ctx.Pipe()
        process = ctx.Process(target=_worker_main, args=(child, init, init_args, job), daemon=True)
        process.start()
        child.close()
        return _Worker(process, parent, spawned_at=time.perf_counter())

    def assign(worker: _Worker) -> None:
        if pending and worker.ready and worker.task is None:
            task = pending.popleft()
            task.deadline = time.perf_counter() + STARTUP_TIMEOUT_S
            task.pid, task.status = worker.process.pid, "assigned"
            worker.task = task
            worker.conn.send((task.task_id, task.args))

    def stop(worker: _Worker) -> None:
        if worker.process.is_alive():
            worker.process.kill()
        worker.process.join(5)
        worker.conn.close()

    def replace(worker: _Worker) -> None:
        stop(worker)
        pool[pool.index(worker)] = spawn()

    try:
        for _ in range(max(1, min(workers, len(tasks)))):
            pool.append(spawn())
        while pending or any(w.task is not None for w in pool):
            if check is not None:
                check()
            now = time.perf_counter()
            limits = [w.task.deadline for w in pool if w.task is not None]
            limits += [w.spawned_at + STARTUP_TIMEOUT_S for w in pool if not w.ready]
            delay = max(0.0, min([POLL_S] + [t - now for t in limits]))
            ready = set(wait([w.conn for w in pool] + [w.process.sentinel for w in pool], delay))
            for worker in list(pool):
                task = worker.task
                if worker.conn in ready or (worker.process.sentinel not in ready and worker.conn.poll()):
                    try:
                        tag, payload = worker.conn.recv()
                    except (EOFError, OSError):
                        tag, payload = None, None
                    if tag == "ready":
                        worker.ready = True
                    elif tag == "started" and task is not None and payload[0] == task.task_id:
                        task.started_at = payload[1]
                        task.deadline = task.started_at + timeout_s
                        task.status = "running"
                    elif task is not None and tag == task.task_id:
                        task.finished_at, result = payload
                        late = task.finished_at > task.deadline
                        task.status = "timeout" if late else "done"
                        worker.task = None
                        if late:
                            on_done(task.path, None, f"{TIMEOUT_PREFIX} {timeout_s:g} s")
                            replace(worker)
                            continue
                        on_done(*result)
                    elif tag is None:  # the worker died while answering
                        if not worker.ready:
                            raise WorkerStartError("extraction worker failed during initialization")
                        if task is not None:
                            task.status, task.finished_at = "crashed", time.perf_counter()
                            on_done(task.path, None, "worker process ended unexpectedly")
                        replace(worker)
                        continue
                    assign(worker)
                elif not worker.process.is_alive():
                    if not worker.ready:
                        raise WorkerStartError("extraction worker failed during initialization")
                    if task is not None:
                        task.status, task.finished_at = "crashed", time.perf_counter()
                        on_done(task.path, None, "worker process ended unexpectedly")
                    replace(worker)
                elif task is not None and time.perf_counter() >= task.deadline:
                    if task.status == "assigned":
                        raise WorkerStartError("extraction worker did not acknowledge its task")
                    task.status, task.finished_at = "timeout", time.perf_counter()
                    on_done(task.path, None, f"{TIMEOUT_PREFIX} {timeout_s:g} s")
                    replace(worker)  # only this worker: the other tasks continue
                elif not worker.ready and time.perf_counter() >= worker.spawned_at + STARTUP_TIMEOUT_S:
                    raise WorkerStartError(f"extraction worker did not start within {STARTUP_TIMEOUT_S:g} s")
            for worker in pool:
                if worker.task is None:
                    assign(worker)
    finally:
        for worker in pool:
            try:
                if worker.process.is_alive() and worker.task is None:
                    worker.conn.send(None)
            except (OSError, ValueError):
                pass
            if worker.task is None:
                worker.process.join(1)
            stop(worker)
    return tasks
