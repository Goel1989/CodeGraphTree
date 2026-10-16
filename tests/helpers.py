"""Shared helpers for fixture-based tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codegraph_sci.core.facts import FileFacts, SourceFile
from codegraph_sci.core.plugins import ExtractContext, LanguageAdapter, decode_bytes
from codegraph_sci.extract.context import make_include_resolver
from codegraph_sci.inventory.run import run_inventory

FIXTURES = Path(__file__).parent / "fixtures"


def load_expected(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name / "expected_graph.json").read_text(encoding="utf-8"))
    return data


def extract_fixture(name: str, adapter: LanguageAdapter, lang: str,
                    known_arrays: set[str] | None = None) -> dict[str, FileFacts]:
    root = FIXTURES / name / "src"
    inventory = run_inventory(root)
    expected = load_expected(name)
    arrays = set(expected.get("extract_options", {}).get("known_arrays", [])) | (known_arrays or set())
    ctx = ExtractContext(include_paths=inventory.include_paths, known_arrays=arrays,
                         resolve_include=make_include_resolver(root, inventory.include_paths))
    out = {}
    for entry in inventory.source_files():
        if entry.lang != lang:
            continue
        text, enc = decode_bytes((root / entry.path).read_bytes())
        out[entry.path] = adapter.extract(SourceFile(entry.path, lang, entry.variant, enc, text), ctx)
    return out


def facts_definitions(facts: dict[str, FileFacts]) -> list[dict[str, Any]]:
    return sorted(({"uid": d.uid, "kind": d.kind, "subtype": d.subtype, "file": f.path,
                    "line_start": d.span[0], "line_end": d.span[1]}
                   for f in facts.values() for d in f.definitions), key=lambda d: d["uid"])


def facts_references(facts: dict[str, FileFacts]) -> list[dict[str, Any]]:
    return sorted(({"src": r.src, "file": f.path, "line": r.line, "col": r.col, "ref_kind": r.kind,
                    "target_text": r.target_text, "condition": r.condition}
                   for f in facts.values() for r in f.references),
                  key=lambda r: (r["file"], r["line"], r["col"], r["target_text"]))


def expected_definitions(expected: dict[str, Any], files: set[str]) -> list[dict[str, Any]]:
    keys = ("uid", "kind", "subtype", "file", "line_start", "line_end")
    return sorted(({k: n[k] for k in keys} for n in expected["nodes"] if n.get("file") in files),
                  key=lambda d: d["uid"])


def expected_references(expected: dict[str, Any], files: set[str]) -> list[dict[str, Any]]:
    keys = ("src", "file", "line", "col", "ref_kind", "target_text")
    return sorted(({**{k: s[k] for k in keys}, "condition": s.get("condition")}
                   for s in expected["call_sites"] if s["file"] in files),
                  key=lambda r: (r["file"], r["line"], r["col"], r["target_text"]))


def scan_fixture(name: str, folder: Path, root: Path | None = None, expected_file: str = "expected_graph.json"
                 ) -> Any:
    """Scan a fixture (or a copy of it at ``root``) into ``folder``; returns the ScanResult."""
    from codegraph_sci.core.profile import Scope
    from codegraph_sci.core.project import open_project
    from codegraph_sci.inventory.profile_io import profile_from_inventory, save_profile
    from codegraph_sci.scan import ScanOptions, scan

    exp_path = FIXTURES / name / expected_file
    expected = json.loads(exp_path.read_text(encoding="utf-8")) if exp_path.is_file() else {}
    src = root or FIXTURES / name / "src"
    project = open_project(src, folder)
    if "profile" in expected and not project.profile_path.is_file():
        profile = profile_from_inventory(run_inventory(src))
        profile.scope = Scope(**expected["profile"]["scope"])
        save_profile(project.profile_path, profile)
    arrays = set(expected.get("extract_options", {}).get("known_arrays", []))
    bridges = expected.get("bridges", {})
    return scan(project, ScanOptions(extra_known_arrays=arrays, native_bridges=bridges.get("native", True),
                                     bridge_rules=list(bridges.get("rules", []))))


def graph_diff(export: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Differences between an exported database and an expected graph (empty list = identical)."""
    node_keys = ("uid", "kind", "subtype", "file", "line_start", "line_end")
    nodes = [{**{k: n[k] for k in node_keys}, "in_scope": n["in_scope"]}
             for n in export["nodes"] if n["kind"] != "file"]
    exp_nodes = [{**{k: n.get(k) for k in node_keys}, "in_scope": n.get("in_scope", True)}
                 for n in expected["nodes"]]
    site_keys = ("src", "file", "line", "col", "ref_kind", "target_text", "dst", "resolution", "confidence",
                 "origin")
    sites = [{**{k: s[k] for k in site_keys}, "condition": s["condition"], "candidates": s["candidates"]}
             for s in export["call_sites"]]
    exp_sites = [{**{k: s[k] for k in site_keys}, "condition": s.get("condition"),
                  "candidates": s.get("candidates", [])} for s in expected["call_sites"]]
    edges = [{k: e[k] for k in ("src", "dst", "kind", "site_count")} for e in export["edges"]
             if e["kind"] != "contains"]
    exp_edges = expected["edges"]
    partial = expected.get("partial", False)
    out = []
    for got, want, label in ((nodes, exp_nodes, "node"), (sites, exp_sites, "site"), (edges, exp_edges, "edge")):
        if not partial:
            out += [f"extra {label}: {x}" for x in got if x not in want]
        out += [f"missing {label}: {x}" for x in want if x not in got]
    return out
