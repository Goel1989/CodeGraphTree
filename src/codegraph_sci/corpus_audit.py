"""``cgs audit corpus``: a reproducible audit of a real-code corpus (corrective audit, P1 §5–6).

The manifest is authoritative: the analysis profile of the audit is rebuilt from the inventory of the sources and the
manifest alone (scope, packs) — a profile left by a user in the audit project is overwritten, never reused. Required
packs must load; the requested source revision is checked against Git when the sources are a Git checkout. The report
records the provenance of the result (hashes of the manifest, the expectations and the audit profile, source revision,
tool, adapter and pack versions).

Exit codes: 0 every required expectation PASS; 1 a required expectation FAIL; 2 configuration error (manifest,
expectations, sources, revision, packs); 3 internal audit error.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.audit.corpus import (
    FAIL,
    PASS,
    SKIP,
    ExpectationError,
    check_expectations,
    load_manifest,
    parse_items,
)
from codegraph_sci.core.paths import data_dir
from codegraph_sci.core.profile import Scope
from codegraph_sci.core.project import open_project
from codegraph_sci.core.versions import APP_VERSION
from codegraph_sci.enrich.packs import PackError, default_search_paths, load_packs
from codegraph_sci.inventory.profile_io import profile_from_inventory, profile_sha256, save_profile
from codegraph_sci.inventory.run import run_inventory

EXIT_PASS, EXIT_FAIL, EXIT_CONFIG, EXIT_INTERNAL = 0, 1, 2, 3


class AuditConfigError(Exception):
    """The audit cannot be run as configured (exit code 2)."""


@dataclass
class AuditOptions:
    manifest: Path
    project: Path | None = None
    scan: bool = True


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(source: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, timeout=30,
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def source_revision(source: Path, requested: str) -> dict[str, Any]:
    """Requested revision vs. the checkout: verified when it names the commit or one of its tags."""
    info: dict[str, Any] = {"requested": requested, "commit": None, "tags": [], "verified": False}
    if not (source / ".git").exists():
        info["note"] = "not a Git checkout: revision not verified"
        return info
    commit = _git(source, "rev-parse", "HEAD")
    if commit is None:
        info["note"] = "Git unavailable: revision not verified"
        return info
    tags = sorted((_git(source, "tag", "--points-at", "HEAD") or "").split())
    info.update(commit=commit, tags=tags)
    if not requested or requested.lower() == "none":
        info["note"] = "no revision requested by the manifest"
        return info
    if requested in tags or (len(requested) >= 7 and commit.startswith(requested)):
        info["verified"] = True
        return info
    raise AuditConfigError(f"source revision mismatch: the manifest requests '{requested}', the checkout is "
                           f"{commit[:12]} (tags: {', '.join(tags) or 'none'})")


def _scan_provenance(db: Path) -> dict[str, Any]:
    import sqlite3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT profile_sha256, plugins FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    if row is None:
        return {"profile_sha256": None, "adapters": {}, "packs": {}}
    plugins = json.loads(row[1] or "[]")
    return {"profile_sha256": row[0],
            "adapters": {p["name"]: p["version"] for p in plugins if p.get("type") == "adapter"},
            "packs": {p["name"]: p["version"] for p in plugins if p.get("type") == "pack"}}


def run_audit(options: AuditOptions) -> dict[str, Any]:
    """Run the audit and return its report; raises :class:`AuditConfigError` for configuration errors."""
    from codegraph_sci.scan import ScanOptions, scan

    manifest_path = options.manifest
    if not manifest_path.is_file():
        raise AuditConfigError(f"manifest not found: {manifest_path}")
    try:
        manifest = load_manifest(manifest_path)
    except ExpectationError as exc:
        raise AuditConfigError(str(exc)) from exc
    expectations_path = manifest_path.with_name("expectations.yaml")
    if not expectations_path.is_file():
        raise AuditConfigError(f"expectations file not found: {expectations_path}")
    try:
        expectations = yaml.safe_load(expectations_path.read_text(encoding="utf-8")) or {}
        if not isinstance(expectations, dict):
            raise ExpectationError(f"{expectations_path}: a mapping is expected")
        items = parse_items(expectations)
    except (yaml.YAMLError, ExpectationError) as exc:
        raise AuditConfigError(f"{expectations_path}: {exc}") from exc
    if not items and not (expectations.get("inventory") or {}):
        raise AuditConfigError(f"{expectations_path}: no expectation to check")

    source = Path(str(manifest["source"]["path"]))
    if not source.is_dir():
        raise AuditConfigError(f"corpus sources not found at {source} (edit source.path in {manifest_path})")
    revision = source_revision(source, str(manifest["source"].get("revision", "")))

    corpus = str(manifest["corpus"])
    project = open_project(source, options.project or data_dir() / "audits" / corpus)
    # Audit profile: the inventory of the sources plus the manifest, nothing else.
    profile = profile_from_inventory(run_inventory(source), None, by="cgs audit corpus")
    profile.scope = Scope(include=[s for s in manifest["scope"] if s not in (".", "./")], exclude=[])
    for name in manifest.get("packs", []):
        if name not in profile.packs:
            profile.packs.append(str(name))
    try:
        load_packs(profile.packs, default_search_paths(project.folder))
    except PackError as exc:
        raise AuditConfigError(f"required pack unavailable: {exc}") from exc
    project.folder.mkdir(parents=True, exist_ok=True)
    save_profile(project.profile_path, profile)
    audit_sha = profile_sha256(profile)

    if options.scan:
        scan(project, ScanOptions())
    elif not project.db_path.is_file():
        raise AuditConfigError("--no-scan: no existing analysis in the audit project")
    provenance = _scan_provenance(project.db_path)
    if provenance["profile_sha256"] != audit_sha:
        raise AuditConfigError("the analysis was not made with the audit profile (run without --no-scan)")

    results = check_expectations(project.db_path, expectations)
    summary = {s: sum(1 for r in results if r["status"] == s) for s in (PASS, FAIL, SKIP)}
    failed_required = [r for r in results if r["status"] == FAIL and r["required"]]
    return {
        "corpus": corpus,
        "exit_code": EXIT_FAIL if failed_required else EXIT_PASS,
        "summary": summary,
        "results": results,
        "manifest_sha256": _sha256_file(manifest_path),
        "expectations_sha256": _sha256_file(expectations_path),
        "audit_profile_sha256": audit_sha,
        "source_revision": revision,
        "tool_version": APP_VERSION,
        "adapters": provenance["adapters"],
        "packs": provenance["packs"],
        "project": str(project.folder),
    }


def print_report(report: dict[str, Any]) -> None:
    for r in report["results"]:
        extra = (f"  ({r['value']})" if "value" in r else "") + (f"  [{r['reason']}]" if "reason" in r else "")
        optional = "" if r["required"] else "  (optional)"
        print(f"[{r['status']:>6}] {r['item']}{extra}{optional}")
    rev = report["source_revision"]
    print(f"source revision: {rev['requested']} -> {rev['commit'] or '-'} "
          f"({'verified' if rev['verified'] else rev.get('note', 'not verified')})")
    print(f"manifest {report['manifest_sha256'][:12]}, expectations {report['expectations_sha256'][:12]}, "
          f"audit profile {report['audit_profile_sha256'][:12]}, CodeGraph-Sci {report['tool_version']}")
    s = report["summary"]
    print(f"corpus {report['corpus']}: {s[PASS]} PASS, {s[FAIL]} FAIL, {s[SKIP]} SKIP")
