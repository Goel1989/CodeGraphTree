"""Dependency locks (corrective audit §8): exact pins that cover pyproject.toml and match the environment."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).parents[2]


def _tool():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("lock_dependencies", ROOT / "tools" / "lock_dependencies.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_locks_pin_every_declared_dependency_within_its_constraint() -> None:
    tool = _tool()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    runtime = tool.read_lock(tool.RUNTIME_LOCK)
    dev = tool.read_lock(tool.DEV_LOCK)
    for raw in project["dependencies"] + project["optional-dependencies"]["view3d"]:
        req = Requirement(raw)
        version, _marker = runtime[tool._canonical(req.name)]
        assert req.specifier.contains(version), (req, version)
    for raw in project["optional-dependencies"]["dev"] + ["pyinstaller"]:
        req = Requirement(raw)
        name = tool._canonical(req.name)
        assert name in dev or name in runtime, req


def test_environment_matches_the_locks() -> None:
    tool = _tool()
    assert tool.check([tool.RUNTIME_LOCK, tool.DEV_LOCK]) == []
