"""Run every quality gate: ruff, mypy (strict), import-linter, pytest (network blocked).

Usage: python tools/check.py [--fast]   (--fast skips tests marked slow)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(title: str, cmd: list[str]) -> bool:
    print(f"==> {title}: {' '.join(cmd)}", flush=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), QT_QPA_PLATFORM="offscreen")
    ok = subprocess.call(cmd, cwd=ROOT, env=env) == 0
    print(f"<== {title}: {'OK' if ok else 'FAILED'}\n", flush=True)
    return ok


def main() -> int:
    py = sys.executable
    pytest_cmd = [py, "-m", "pytest", "-q"]
    if "--fast" in sys.argv:
        pytest_cmd += ["-m", "not slow"]
    steps = [
        ("ruff", [py, "-m", "ruff", "check", "src", "tests", "tools"]),
        ("mypy", [py, "-m", "mypy"]),
        ("import-linter", [py, "-c", "import sys; from importlinter.cli import lint_imports_command;"
                                    " sys.exit(lint_imports_command())"]),
        ("pytest", pytest_cmd),
    ]
    results = [run(title, cmd) for title, cmd in steps]
    if all(results):
        print("check: ALL PASSED")
        return 0
    print("check: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
