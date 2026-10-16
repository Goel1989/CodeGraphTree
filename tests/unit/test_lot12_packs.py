from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.helpers import FIXTURES, load_expected

from codegraph_sci.core.graph import EdgeRecord, NodeRecord
from codegraph_sci.core.project import open_project
from codegraph_sci.enrich.noise import hidden, noise_map
from codegraph_sci.enrich.packs import PackError, PackRules, load_pack_file
from codegraph_sci.extract.keywords import KeywordProfileError, load_keyword_profile
from codegraph_sci.inventory.profile_io import profile_from_inventory, save_profile
from codegraph_sci.inventory.run import run_inventory
from codegraph_sci.query.api import GraphQuery
from codegraph_sci.scan import ScanOptions, scan
from codegraph_sci.store.export import export_dict

ROOT = Path(__file__).parents[2]


def _scan_with_packs(name: str, folder: Path, packs: list[str]) -> Path:
    src = FIXTURES / name / "src"
    project = open_project(src, folder)
    profile = profile_from_inventory(run_inventory(src))
    profile.packs = packs
    save_profile(project.profile_path, profile)
    return scan(project, ScanOptions()).db_path


def test_generic_fortran_data_accesses(tmp_path: Path) -> None:
    expected = load_expected("fortran_data")["with_pack"]
    data = export_dict(_scan_with_packs("fortran_data", tmp_path / "p", ["generic_fortran"]))
    nodes = sorted(({k: n[k] for k in ("uid", "kind", "subtype")} for n in data["nodes"] if n["kind"] == "data"),
                   key=lambda n: n["uid"])
    assert nodes == sorted(expected["data_nodes"], key=lambda n: n["uid"])
    got = sorted((a["src"], a["data"], a["mode"], a["key_kind"], a["line"]) for a in data["data_accesses"])
    want = sorted((a["src"], a["data"], a["mode"], a["key_kind"], a["line"]) for a in expected["data_accesses"])
    assert got == want
    assert {a["origin"] for a in data["data_accesses"]} == {"pack:generic_fortran"}
    edges = {(e["src"], e["dst"], e["kind"]): e["site_count"] for e in data["edges"] if e["kind"] in ("reads", "writes")}
    assert edges[("f:advance", "data:module:state::temperature", "writes")] == 1
    with GraphQuery(tmp_path / "p" / "project.sqlite") as q:
        accesses = q.data_accesses("f:report_state")
        assert [(a.data, a.mode) for a in accesses] == [("data:module:state::temperature", "reads")]


def test_without_pack_no_data_nodes(tmp_path: Path) -> None:
    data = export_dict(_scan_with_packs("fortran_data", tmp_path / "p", []))
    assert not [n for n in data["nodes"] if n["kind"] == "data"] and data["data_accesses"] == []


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_pack_strict_loading(tmp_path: Path) -> None:
    good = "pack: demo\nversion: '1.0'\nformat_version: 1\nidentifiers: [demo_call]\nnoise: {hide: [log_*]}\n"
    assert load_pack_file(_write(tmp_path, good)).name == "demo"
    with pytest.raises(PackError, match="unknown_key"):
        load_pack_file(_write(tmp_path, good + "unknown_key: 1\n"))
    with pytest.raises(PackError, match="noise/hide"):
        load_pack_file(_write(tmp_path, good.replace("[log_*]", "log_*")))
    with pytest.raises(PackError, match="format_version"):
        load_pack_file(_write(tmp_path, good.replace("format_version: 1", "format_version: 7")))
    with pytest.raises(PackError, match="invalid YAML"):
        load_pack_file(_write(tmp_path, good + "glossary: !!python/object/apply:os.system ['echo hacked']\n"))
    with pytest.raises(PackError, match="regular expression"):
        load_pack_file(_write(tmp_path, good + "bridges: [{from: cpp, to: fortran, declaration_patterns: ['(']}]\n"))


def test_keyword_profile_strict_loading(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("language: x\nversion: 1\nformat_version: 1\nextensions: ['.x']\n"
                    "definitions: [{keywords: [def], name: after_keyword}]\nbogus: 1\n", encoding="utf-8")
    with pytest.raises(KeywordProfileError, match="bogus"):
        load_keyword_profile(path)


def test_noise_rules_and_hubs() -> None:
    nodes = [NodeRecord(f"f:{n}", n, "routine") for n in ("log_msg", "check", "hub", "a", "b", "c")]
    nodes.append(NodeRecord("ext:intrinsic:sin", "sin", "external", "intrinsic"))
    edges = [EdgeRecord(f"f:{s}", "f:hub", "calls", 1, "exact", [], []) for s in ("a", "b", "c")]
    pack = PackRules("demo", "1.0", "-", {"noise": {"hide": ["log_*"], "optional": ["check"],
                                                    "auto_detect_hubs": {"min_fan_in": 3, "max_fan_out": 0}}})
    reasons = noise_map(nodes, edges, [pack])
    assert reasons["f:log_msg"] == "pack:demo" and reasons["f:check"] == "optional:demo"
    assert reasons["f:hub"].startswith("hub:demo") and reasons["ext:intrinsic:sin"] == "intrinsic"
    assert "f:check" not in hidden(reasons)


def test_keyword_coverage_is_measured(tmp_path: Path) -> None:
    from tests.helpers import scan_fixture

    expected = load_expected("keywords_language")
    data = export_dict(scan_fixture("keywords_language", tmp_path / "p").db_path)
    want_defs = {n["uid"] for n in expected["nodes"]}
    got_defs = {n["uid"] for n in data["nodes"] if n["uid"].startswith("kw:")}
    want_links = {(s["src"], s["dst"]) for s in expected["call_sites"] if s["ref_kind"] != "use"}
    got_links = {(s["src"], s["dst"]) for s in data["call_sites"] if s["dst"] and s["ref_kind"] != "use"}
    recall = len(want_defs & got_defs) / len(want_defs)
    precision = len(want_links & got_links) / len(got_links)
    assert recall == 1.0 and precision == 1.0


def test_isolation_no_pack_identifier_in_core() -> None:
    """§6.4: identifiers declared by code packs never appear in the core."""
    identifiers: set[str] = set()
    for rules in list((ROOT / "src" / "codegraph_sci_pro").rglob("rules.yaml")) + list(
            (ROOT / "tests").rglob("packs/*/rules.yaml")):
        identifiers |= set(load_pack_file(rules).identifiers)
    identifiers |= {"jeveux", "jemarq", "jedema", "utmess", "CALLO_", "code_aster", "zk24", "mmalgo"}
    core = ROOT / "src" / "codegraph_sci"
    offenders = []
    for path in core.rglob("*"):
        if path.suffix not in (".py", ".yaml", ".json", ".sql") or "generic_" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        for ident in identifiers:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(ident)}(?![A-Za-z0-9])", text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}: {ident}")
    assert offenders == []
