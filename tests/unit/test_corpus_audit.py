"""`cgs audit corpus`: PASS/FAIL/SKIP states, exit codes, authoritative manifest and provenance (audit P1 §5–6)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from tests.helpers import FIXTURES

GOOD = {"expect": [{"node": "f:main"}, {"node": "f:mesh_mod::refine"}]}


def _corpus(tmp_path: Path, expectations: dict | None, manifest_extra: dict | None = None,
            git_tag: str | None = None) -> Path:
    src = tmp_path / "src"
    shutil.copytree(FIXTURES / "fortran_basic" / "src", src)
    if git_tag:
        git = ["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "c"], check=True)
        subprocess.run(git + ["tag", git_tag], check=True)
    folder = tmp_path / "corpus"
    folder.mkdir()
    manifest = {"corpus": "mini", "source": {"path": str(src), "revision": git_tag or "none"}, "scope": ["."],
                "packs": [], **(manifest_extra or {})}
    (folder / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if expectations is not None:
        (folder / "expectations.yaml").write_text(yaml.safe_dump(expectations), encoding="utf-8")
    return folder / "manifest.yaml"


def _run(manifest: Path, tmp_path: Path, *extra: str) -> int:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    try:
        return main(["audit", "corpus", str(manifest), "--project", str(tmp_path / "proj"), *extra])
    finally:
        netguard.uninstall()


def test_all_required_pass_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(_corpus(tmp_path, GOOD), tmp_path) == 0
    out = capsys.readouterr().out
    assert "[  PASS] node: f:main" in out and "2 PASS, 0 FAIL, 0 SKIP" in out


def test_required_failure_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exp = {"expect": [{"node": "f:main"}, {"node": "f:does_not_exist"}]}
    assert _run(_corpus(tmp_path, exp), tmp_path) == 1
    assert "[  FAIL] node: f:does_not_exist" in capsys.readouterr().out


def test_unsupported_required_expectation_fails_optional_one_is_skipped(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exp = {"expect": [{"node": "f:main"}, {"catalog_links": {"min": 1}, "required": False}]}
    assert _run(_corpus(tmp_path, exp), tmp_path) == 0
    assert "[  SKIP] catalog_links" in capsys.readouterr().out
    exp = {"expect": [{"node": "f:main"}, {"catalog_links": {"min": 1}}]}  # required by default
    assert _run(_corpus(tmp_path / "b", exp), tmp_path / "b") == 1


@pytest.mark.parametrize("case", ["no_sources", "unknown_pack", "no_expectations", "empty", "bad_item",
                                  "bad_revision"])
def test_configuration_errors_exit_2(tmp_path: Path, case: str) -> None:
    if case == "no_sources":
        manifest = _corpus(tmp_path, GOOD)
        shutil.rmtree(tmp_path / "src")
    elif case == "unknown_pack":
        manifest = _corpus(tmp_path, GOOD, {"packs": ["no_such_pack"]})
    elif case == "no_expectations":
        manifest = _corpus(tmp_path, None)
    elif case == "empty":
        manifest = _corpus(tmp_path, {"expect": []})
    elif case == "bad_item":
        manifest = _corpus(tmp_path, {"expect": [{"node": "f:main", "edge": {"src": "a"}}]})
    else:
        manifest = _corpus(tmp_path, GOOD, git_tag="v1")
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        data["source"]["revision"] = "v2"
        manifest.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert _run(manifest, tmp_path) == 2


def test_internal_error_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import codegraph_sci.corpus_audit as corpus_audit

    def boom(*_a: object, **_k: object) -> list[dict[str, object]]:
        raise RuntimeError("bug")

    monkeypatch.setattr(corpus_audit, "check_expectations", boom)
    assert _run(_corpus(tmp_path, GOOD), tmp_path) == 3


def test_manifest_is_authoritative_and_provenance_is_reported(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = _corpus(tmp_path, GOOD, git_tag="v1")
    assert _run(manifest, tmp_path, "--json") == 0
    first = json.loads(capsys.readouterr().out)
    # A user profile left in the audit project must not change the audit (scope, packs, overrides).
    profile = tmp_path / "proj" / "analysis_profile.yaml"
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    data["scope"] = {"include": ["nowhere/"], "exclude": []}
    data["file_overrides"] = [{"glob": "*.f90", "language": "python", "reason": "user"}]
    data["profile_version"] += 1
    profile.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert _run(manifest, tmp_path, "--json") == 0
    second = json.loads(capsys.readouterr().out)
    assert first["audit_profile_sha256"] == second["audit_profile_sha256"]
    assert second["summary"] == {"PASS": 2, "FAIL": 0, "SKIP": 0}
    prov = second
    assert len(prov["manifest_sha256"]) == 64 and len(prov["expectations_sha256"]) == 64
    assert prov["source_revision"]["requested"] == "v1" and prov["source_revision"]["verified"] is True
    assert len(prov["source_revision"]["commit"]) == 40
    assert prov["tool_version"] and "fortran" in prov["adapters"] and "generic_noise" in prov["packs"]
    assert {r["status"] for r in prov["results"]} == {"PASS"}
