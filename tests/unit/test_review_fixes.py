"""Non-regression tests for the issues found by the external code review (2026-10)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codegraph_sci.query.api import GraphQuery

GENERIC_SAME_NAME = """module strings
  implicit none
  interface helper
    module procedure helper
  end interface helper
contains
  function helper(s) result(r)
    character(len=*), intent(in) :: s
    character(len=len(s)+1) :: r
    r = s // char(0)
  end function helper
end module strings

subroutine opener(path)
  use strings
  character(len=*), intent(in) :: path
  character(len=80) :: tmp
  integer :: t
  tmp = helper(path)
  call system_clock(t)
  call nowhere(t)
end subroutine opener
"""

USER_SYSTEM_CLOCK = """subroutine system_clock(t)
  integer :: t
  t = 0
end subroutine system_clock

subroutine timer()
  integer :: t
  call system_clock(t)
end subroutine timer
"""


def _scan(tmp_path: Path, files: dict[str, str]) -> Path:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    repo = tmp_path / "repo"
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    try:
        assert main(["scan", str(repo), "--project", str(tmp_path / "proj")]) == 0
    finally:
        netguard.uninstall()
    return tmp_path / "proj" / "project.sqlite"


def test_generic_interface_named_like_its_procedure(tmp_path: Path) -> None:
    db = _scan(tmp_path, {"m.f90": GENERIC_SAME_NAME})
    with GraphQuery(db) as q:
        report = q.callees("f:opener")
        routine = next(m for m in q.resolve("helper") if m.kind == "routine")
        callers = q.callers(routine.uid)
        patterns = {g.pattern for g in q.unresolved(include_ambiguous=True)}
        implements = q.con.execute(
            "SELECT count(*) FROM edges e JOIN nodes a ON a.id = e.src JOIN nodes b ON b.id = e.dst "
            "WHERE e.kind = 'implements' AND a.uid = 'f:strings::helper' AND b.uid = ?", (routine.uid,)).fetchone()[0]
    assert routine.uid in {i.node.uid for i in report.items}
    assert [i.node.uid for i in callers.items] == ["f:opener"]
    assert "helper" not in patterns
    assert implements == 1


def test_intrinsic_subroutine_called_with_call_is_external(tmp_path: Path) -> None:
    db = _scan(tmp_path, {"m.f90": GENERIC_SAME_NAME})
    with GraphQuery(db) as q:
        uids = {i.node.uid for i in q.callees("f:opener", hide_noise=False).items}  # intrinsics are utilities
        patterns = {g.pattern for g in q.unresolved(include_ambiguous=True)}
    assert "ext:intrinsic:system_clock" in uids
    assert not any(p.startswith("system") for p in patterns)


def test_a_routine_of_the_repository_wins_over_the_intrinsic(tmp_path: Path) -> None:
    db = _scan(tmp_path, {"t.f90": USER_SYSTEM_CLOCK})
    with GraphQuery(db) as q:
        uids = {i.node.uid for i in q.callees("f:timer").items}
    assert uids == {"f:system_clock"}


def test_counts_report_unresolved_and_ambiguous_sites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    db = _scan(tmp_path, {"m.f90": GENERIC_SAME_NAME})
    with GraphQuery(db) as q:
        report = q.callees("f:opener")
    assert report.unresolved_sites == 1 and report.ambiguous_sites == 0  # call nowhere(t)
    capsys.readouterr()
    try:
        assert main(["callees", "opener", "--db", str(db)]) == 0
    finally:
        netguard.uninstall()
    out = capsys.readouterr().out
    assert "1 unresolved call site(s)" in out


def test_broken_pipe_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``cgs find … | head``: the reader goes away, the command ends quietly."""
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    db = _scan(tmp_path, {"m.f90": GENERIC_SAME_NAME})

    class ClosedPipe:
        def write(self, _text: str) -> int:
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    try:
        assert main(["find", "e", "--db", str(db)]) == 0
    finally:
        netguard.uninstall()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reports a closed pipe as EINVAL")
def test_closed_pipe_on_windows_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    db = _scan(tmp_path, {"m.f90": GENERIC_SAME_NAME})

    class ClosedPipe:
        def write(self, _text: str) -> int:
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    try:
        assert main(["find", "e", "--db", str(db)]) == 0
    finally:
        netguard.uninstall()

