"""Per-task extraction deadlines (rule 12, corrective audit P1 §4): a blocked file never fails healthy ones."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from tests.helpers import FIXTURES

from codegraph_sci.extract_pool import TIMEOUT_PREFIX, run_tasks


def job(path: str, kind: str, _variant: str | None) -> tuple[str, bytes | None, str | None]:
    """Runs in a worker process; module-level so that it can be sent to the worker."""
    if kind == "block":
        time.sleep(3600)
    elif kind == "slow":
        time.sleep(1.0)
    elif kind == "crash":
        raise ValueError("adapter bug")
    return path, path.encode(), None


def blocking_extract(path: str, lang: str, variant: str | None) -> tuple[str, bytes | None, str | None]:
    """The real extraction, except for one file that never ends."""
    from codegraph_sci.scan import _extract_job

    if path.endswith("solve.f90"):
        time.sleep(3600)
    return _extract_job(path, lang, variant)


def _run(jobs: list[tuple[str, str, None]], workers: int, timeout_s: float) -> tuple[dict, list, float]:
    done: dict[str, tuple[bytes | None, str | None]] = {}
    t0 = time.monotonic()
    tasks = run_tasks(jobs, workers=workers, timeout_s=timeout_s, job=job,
                      on_done=lambda p, b, e: done.__setitem__(p, (b, e)))
    return done, tasks, time.monotonic() - t0


def test_blocked_slow_and_fast_tasks() -> None:
    jobs = [("blocked.f90", "block", None), ("slow.f90", "slow", None)] + [
        (f"f{i}.f90", "fast", None) for i in range(10)]
    done, tasks, elapsed = _run(jobs, workers=3, timeout_s=3.0)
    assert done["blocked.f90"][0] is None and done["blocked.f90"][1].startswith(TIMEOUT_PREFIX)
    assert done["slow.f90"] == (b"slow.f90", None)  # slow but within its deadline
    assert all(done[f"f{i}.f90"] == (f"f{i}.f90".encode(), None) for i in range(10))
    assert [t.path for t in tasks if t.status == "timeout"] == ["blocked.f90"]  # one targeted diagnostic
    assert all(t.pid and t.deadline - t.started_at == 3.0 for t in tasks)
    assert elapsed < 30


def test_two_simultaneous_blocked_tasks_only_they_time_out() -> None:
    jobs = [("b1.f90", "block", None), ("b2.f90", "block", None)] + [(f"f{i}.f90", "fast", None) for i in range(6)]
    done, tasks, _ = _run(jobs, workers=2, timeout_s=2.0)  # both workers blocked at the same time
    assert sorted(t.path for t in tasks if t.status == "timeout") == ["b1.f90", "b2.f90"]
    assert all(done[f"f{i}.f90"][1] is None for i in range(6))


def test_a_crashing_extractor_is_a_failed_file_not_a_timeout() -> None:
    done, tasks, _ = _run([("bad.f90", "crash", None), ("ok.f90", "fast", None)], workers=1, timeout_s=5.0)
    assert done["bad.f90"][1] is not None and "adapter bug" in done["bad.f90"][1]
    assert done["ok.f90"] == (b"ok.f90", None)
    assert {t.path: t.status for t in tasks} == {"bad.f90": "done", "ok.f90": "done"}


def test_scan_records_timeout_status_and_continues(tmp_path: Path) -> None:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.query.api import GraphQuery
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "fortran_basic" / "src", repo)
    result = scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1, timeout_s=3.0,
                                                                     extract_job=blocking_extract))
    with GraphQuery(result.db_path) as q:
        status = {f["path"]: f["status"] for f in q.files()}
        health = q.scan_health()
        assert q.resolve("main")  # the other files were analysed
    assert status["solve.f90"] == "timeout" and status["main.f90"] == "ok"
    assert health.files_by_status.get("timeout") == 1
