"""tools/prepare_corpus.py: a corpus is fetched at its exact revision, with its sparse folders (offline test)."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]


def _tool():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("prepare_corpus", ROOT / "tools" / "prepare_corpus.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def origin(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    for rel in ("keep/a.f90", "drop/b.f90"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("subroutine x\nend subroutine x\n", encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "c"], check=True)
    subprocess.run(git + ["tag", "v1"], check=True)
    return repo


def _manifest(tmp_path: Path, origin: Path, revision: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump({"corpus": "mini", "scope": ["."], "source": {
        "path": str(tmp_path / "sources"), "revision": revision, "repository": origin.as_uri(),
        "sparse": ["keep"]}}), encoding="utf-8")
    return path


def test_prepare_fetches_the_revision_and_the_sparse_folders(tmp_path: Path, origin: Path) -> None:
    target = _tool().prepare(_manifest(tmp_path, origin, "v1"))
    assert (target / "keep" / "a.f90").is_file() and not (target / "drop").exists()


def test_prepare_refuses_an_unknown_revision(tmp_path: Path, origin: Path) -> None:
    with pytest.raises(SystemExit):
        _tool().prepare(_manifest(tmp_path, origin, "v9"))
