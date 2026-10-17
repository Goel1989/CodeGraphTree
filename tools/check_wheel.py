"""Build the wheel offline and check the installed artifact outside the checkout (requirements plan phase 10).

1. ``pip wheel --no-deps --no-build-isolation`` (no network): the wheel of ``codegraph_sci``.
2. Every data file of the package source (schemas, YAML, SQL, templates, web assets) is in the wheel.
3. The wheel is unpacked in a temporary folder and a smoke test runs from another temporary folder, with that
   folder first on ``PYTHONPATH``: imports come from the wheel, never from the checkout. It analyzes a small
   mixed-language repository, loads the built-in language packages, creates and tests a rule from its template,
   and builds the 3D page.

Usage: python tools/check_wheel.py   (exit code 0: the installed artifact works)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "codegraph_sci"

SMOKE = r'''
import sys
from pathlib import Path

import codegraph_sci
from codegraph_sci.core.project import open_project
from codegraph_sci.extract.registry import load_registry
from codegraph_sci.query.api import GraphQuery
from codegraph_sci.rules import new_rule, run_rule_tests
from codegraph_sci.scan import ScanOptions, scan

if __name__ == "__main__":
    unpacked = Path(sys.argv[1]).resolve()
    assert Path(codegraph_sci.__file__).resolve().is_relative_to(unpacked), codegraph_sci.__file__
    work = Path(sys.argv[2])
    repo = work / "repo"
    (repo / "csrc").mkdir(parents=True)
    (repo / "fsrc").mkdir()
    (repo / "csrc" / "main.c").write_text("void run(void) { solve_(); }\n", encoding="utf-8")
    (repo / "fsrc" / "solve.f90").write_text("subroutine solve\nend subroutine solve\n", encoding="utf-8")
    (repo / "app.py").write_text("def main():\n    helper()\n\n\ndef helper():\n    pass\n", encoding="utf-8")
    project = open_project(repo, work / "proj")
    scan(project, ScanOptions(jobs=1))
    with GraphQuery(project.db_path) as q:
        assert [i.node.uid for i in q.callees("c:run").items] == ["f:solve"]
        assert [i.node.uid for i in q.callees("py:app.main").items] == ["py:app.helper"]
        assert q.dependencies(limit=10).total >= 2
    assert sorted(load_registry().packages) == ["c", "cpp", "fortran", "python"]
    rule = new_rule("language", "tiny", project, extension=".tny")
    assert all(r.passed for r in run_rule_tests(rule))
    from codegraph_sci.query.types import Graph3D
    from codegraph_sci.ui.view3d.html import build_html
    assert "ForceGraph3D" in build_html(Graph3D("", "functions", [], []), "smoke", host="qt")
    print("smoke test passed from", unpacked)
'''


def data_files() -> list[str]:
    """Non-Python files of the package source, as wheel paths."""
    out = []
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.suffix not in (".py", ".pyc") and "__pycache__" not in path.parts:
            out.append("codegraph_sci/" + path.relative_to(PACKAGE).as_posix())
    return out


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cgs-wheel-", ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        build = subprocess.run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--no-build-isolation",
                                "-w", str(tmp_path / "dist"), "-q"], capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stdout + build.stderr)
            print("check_wheel: FAILED (wheel build)")
            return 1
        wheel = next((tmp_path / "dist").glob("codegraph_sci-*.whl"))
        names = set(zipfile.ZipFile(wheel).namelist())
        missing = [name for name in data_files() if name not in names]
        if missing:
            print("missing from the wheel:\n  " + "\n  ".join(missing))
            print("check_wheel: FAILED (resources)")
            return 1
        unpacked = tmp_path / "site"
        zipfile.ZipFile(wheel).extractall(unpacked)
        work = tmp_path / "work"
        work.mkdir()
        script = work / "smoke.py"
        script.write_text(SMOKE, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(unpacked), "CGS_DATA_DIR": str(work / "data")}
        smoke = subprocess.run([sys.executable, str(script), str(unpacked), str(work)], cwd=work, env=env,
                               capture_output=True, text=True)
        print(smoke.stdout.strip())
        if smoke.returncode != 0:
            print(smoke.stderr)
            print("check_wheel: FAILED (installed artifact)")
            return 1
        print(f"check_wheel: OK ({wheel.name}, {len(names)} files, {len(data_files())} data files)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
