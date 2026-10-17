from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from tests.helpers import FIXTURES, graph_diff, load_expected

from codegraph_sci.ai.complete import Completion, set_rule_status
from codegraph_sci.ai.worker import AIClient
from codegraph_sci.core.project import open_project
from codegraph_sci.inventory.profile_io import load_profile
from codegraph_sci.scan import ScanOptions, scan
from codegraph_sci.store.export import export_dict, export_json

AI = Path(__file__).parents[1] / "ai"
GOOD = f"fake:{AI / 'responses.json'}"
BAD = f"fake:{AI / 'responses_bad_bridge.json'}"


def _project(name: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / name / "src", repo)
    project = open_project(repo, tmp_path / "proj")
    scan(project, ScanOptions())
    return project


def _sites(project) -> dict[str, dict[str, object]]:  # type: ignore[no-untyped-def]
    return {f"{s['file']}:{s['line']}": s for s in export_dict(project.db_path)["call_sites"]}


def test_unknown_extension_identified_and_adopted(tmp_path: Path) -> None:
    project = _project("unknown_extension", tmp_path)
    assert _sites(project)["main.f90:2"]["resolution"] == "unresolved"
    client = AIClient(GOOD, in_process=True)
    proposals = Completion(project, client, auto=True).run()
    assert [(p.kind, p.target, p.accepted) for p in proposals] == [("override", ".ftx", True)]
    profile = load_profile(project.profile_path)
    assert [(o.glob, o.language) for o in profile.file_overrides] == [("*.ftx", "fortran")]
    site = _sites(project)["main.f90:2"]
    assert site["dst"] == "f:solver_a" and site["resolution"] == "resolved"
    assert client.calls == 1


def test_bridge_rule_one_click_validation(tmp_path: Path) -> None:
    project = _project("bridge_unknown_prefix", tmp_path)
    before = _sites(project)
    assert before["cpp/caller.cpp:4"]["resolution"] == "unresolved"
    assert before["cpp/caller.cpp:8"]["dst"] == "cpp:FORT_CALL_LOCAL(int)"  # negative case, resolved natively
    proposals = Completion(project, AIClient(GOOD, in_process=True)).run()
    prop = next(p for p in proposals if p.kind == "bridge")
    assert prop.accepted and prop.checks["gain"] == 1.0 and prop.checks["regressions"] == 0
    assert prop.preview["added"] == 4 and prop.preview["removed"] == 0
    assert {e["dst"] for e in prop.preview["examples"]} == {"f:assemble", "f:solve", "f:export"}
    # Default mode: proposed only, the graph does not change until the user approves.
    Completion(project, AIClient(GOOD, in_process=True)).adopt([prop])
    rule = load_profile(project.profile_path).rules[0]
    assert (rule.id, rule.status, rule.source) == ("r-0001", "proposed", "ai")
    scan(project, ScanOptions())
    assert _sites(project)["cpp/caller.cpp:4"]["resolution"] == "unresolved"
    set_rule_status(project, "r-0001", "approved")
    scan(project, ScanOptions())
    after = _sites(project)
    assert after["cpp/caller.cpp:4"]["dst"] == "f:assemble"
    assert after["cpp/caller.cpp:4"]["origin"] == "bridge:prefix_calls@r-0001"
    assert after["cpp/caller.cpp:8"]["dst"] == "cpp:FORT_CALL_LOCAL(int)"  # never re-linked
    first = export_json(project.db_path)
    scan(project, ScanOptions(full=True))
    assert export_json(project.db_path) == first  # same profile, same graph


def test_wrong_rule_is_rejected_with_its_reason(tmp_path: Path) -> None:
    project = _project("bridge_unknown_prefix", tmp_path)
    proposals = Completion(project, AIClient(BAD, in_process=True), auto=True).run()
    prop = next(p for p in proposals if p.kind == "bridge")
    assert not prop.accepted and "gain 0%" in prop.reason
    assert load_profile(project.profile_path).rules == []


def test_keyword_profile_proposed_by_ai(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "keywords_language" / "src", repo)
    (repo / "manual.md").unlink()
    project = open_project(repo, tmp_path / "proj")
    scan(project, ScanOptions())
    proposals = Completion(project, AIClient(GOOD, in_process=True),
                           document=FIXTURES / "keywords_language" / "src" / "manual.md").run()
    prop = next(p for p in proposals if p.kind == "keywords")
    assert prop.accepted and prop.content["coverage"]["definitions_recall"] == 1.0
    assert load_profile(project.profile_path).languages["acme_script"].status == "proposed"
    set_rule_status(project, "acme_script", "approved")
    scan(project, ScanOptions())
    expected = load_expected("keywords_language")
    data = export_dict(project.db_path)
    want = {(e["src"], e["dst"]) for e in expected["edges"]}
    got = {(e["src"], e["dst"]) for e in data["edges"] if e["kind"] != "contains"}
    assert len(want & got) / len(want) >= 0.9
    assert graph_diff(data, {**expected, "partial": True}) == []


def test_worker_process_and_scan_never_runs_ai(tmp_path: Path) -> None:
    client = AIClient(GOOD)  # separate `cgs ai-worker` process, JSON over pipes
    try:
        answer = client.ask("identify", ".ftx", "prompt", {"type": "object"})
    finally:
        client.close()
    assert answer["use_adapter"] == "fortran"
    code = ("import sys; from pathlib import Path; from codegraph_sci.core.project import open_project;"
            "from codegraph_sci.scan import scan; "
            f"scan(open_project(Path(r'{FIXTURES / 'fortran_basic' / 'src'}'), Path(r'{tmp_path / 'p'}')));"
            "print(any(m.startswith('codegraph_sci.ai') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
