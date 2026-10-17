"""Lifecycle of AI proposals (requirements plan phase 9): ``draft -> validated -> approved``, or ``rejected``.

One lifecycle for language overrides, language packages, bridge rules and rule modifications. Proposals live in
their own store (``<project>/proposals/p-<n>.yaml``), outside the active configuration: generating, validating or
rejecting a proposal never changes the analysis. Only an explicit approval of a *validated* proposal activates it
(and only that step writes to the analysis profile or to ``rules/``); the next ``cgs scan`` applies it and never
needs the AI. Automatic approval exists only through a project policy that is configured separately
(``cgs ai-policy``) and recorded; every approval, automatic or not, is in the proposal's history.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.core.profile import FileOverride, HistoryEntry, RuleRef
from codegraph_sci.core.project import Project
from codegraph_sci.inventory.profile_io import load_profile, save_profile

STATUSES = ("draft", "validated", "rejected", "approved")
KINDS = ("override", "language", "bridge", "rule_change")
POLICY_FILE = "ai_policy.yaml"
# Keys of an AI keyword profile that are not extraction rules (they move to the package itself).
_PROFILE_KEYS = {"language", "version", "format_version", "source", "status", "extensions", "coverage", "evidence"}


class ProposalError(RuntimeError):
    """A proposal cannot change state; the message says why."""


@dataclass
class StoredProposal:
    id: str  # p-0001
    kind: str  # override, language, bridge, rule_change
    target: str
    status: str
    content: dict[str, Any]
    validation: dict[str, Any] = field(default_factory=dict)  # checks, passed, reason, independent tests
    provenance: dict[str, Any] = field(default_factory=dict)  # model, task, document, passages, assumptions
    history: list[dict[str, str]] = field(default_factory=list)
    activation: dict[str, Any] = field(default_factory=dict)  # what approval changed

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "target": self.target, "status": self.status,
                "content": self.content, "validation": self.validation, "provenance": self.provenance,
                "history": self.history, "activation": self.activation}


def store(project: Project) -> Path:
    return project.folder / "proposals"


def _path(project: Project, proposal_id: str) -> Path:
    if not re.fullmatch(r"p-\d{4,}", proposal_id):
        raise ProposalError(f"invalid proposal id {proposal_id!r} (expected p-0001)")
    return store(project) / f"{proposal_id}.yaml"


def save(project: Project, proposal: StoredProposal) -> None:
    folder = store(project)
    folder.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(proposal.to_dict(), sort_keys=False, allow_unicode=True, width=110)
    (folder / f"{proposal.id}.yaml").write_bytes(text.encode("utf-8"))


def load(project: Project, proposal_id: str) -> StoredProposal:
    path = _path(project, proposal_id)
    if not path.is_file():
        raise ProposalError(f"no proposal {proposal_id} in {store(project)}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return StoredProposal(**data)


def list_proposals(project: Project) -> list[StoredProposal]:
    folder = store(project)
    if not folder.is_dir():
        return []
    return [load(project, p.stem) for p in sorted(folder.glob("p-*.yaml"))]


def record(project: Project, kind: str, target: str, content: dict[str, Any], *, passed: bool, reason: str,
           checks: dict[str, Any], provenance: dict[str, Any], independent: dict[str, Any] | None = None
           ) -> StoredProposal:
    """Store a new proposal: a draft, then validated or rejected by its checks. Nothing active changes."""
    if kind not in KINDS:
        raise ProposalError(f"unknown proposal kind {kind!r}")
    existing = list_proposals(project)
    number = 1 + max([int(p.id.split("-")[1]) for p in existing] or [0])
    proposal = StoredProposal(f"p-{number:04d}", kind, target, "draft", content,
                              provenance=provenance, history=[{"status": "draft", "by": "ai", "reason": "generated"}])
    proposal.validation = {"checks": checks, "passed": passed, "reason": reason,
                           "independent_tests": independent or {"status": "none"}}
    proposal.status = "validated" if passed else "rejected"
    proposal.history.append({"status": proposal.status, "by": "validation", "reason": reason})
    save(project, proposal)
    return proposal


def reject(project: Project, proposal_id: str, reason: str = "rejected by the user") -> StoredProposal:
    proposal = load(project, proposal_id)
    if proposal.status == "approved":
        raise ProposalError(f"{proposal_id} is already approved; change the active rule instead")
    proposal.status = "rejected"
    proposal.history.append({"status": "rejected", "by": "user", "reason": reason})
    save(project, proposal)
    return proposal


# ------------------------------------------------------------------ policy
def auto_approval_enabled(project: Project) -> bool:
    path = project.folder / POLICY_FILE
    if not path.is_file():
        return False
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return bool(data.get("auto_approve", False))


def set_auto_approval(project: Project, enabled: bool, by: str = "user") -> None:
    """Automatic approval of validated proposals: off by default, configured separately, every change recorded."""
    path = project.folder / POLICY_FILE
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None) or {}
    history = list(data.get("history", []))
    history.append({"auto_approve": enabled, "by": by})
    project.folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(yaml.safe_dump({"auto_approve": enabled, "history": history}, sort_keys=False).encode("utf-8"))


# ------------------------------------------------------------------ approval = activation
def approve(project: Project, proposal_id: str, *, by: str = "user") -> StoredProposal:
    """Activate a validated proposal (the only step that changes the active configuration)."""
    proposal = load(project, proposal_id)
    if proposal.status != "validated":
        raise ProposalError(f"{proposal_id} is {proposal.status}: only a validated proposal can be approved")
    if by == "auto-policy" and not auto_approval_enabled(project):
        raise ProposalError("automatic approval is not enabled for this project (cgs ai-policy)")
    activation = {"override": _activate_override, "language": _activate_language, "bridge": _activate_bridge,
                  "rule_change": _activate_rule_change}[proposal.kind](project, proposal)
    proposal.status = "approved"
    proposal.activation = activation
    proposal.history.append({"status": "approved", "by": by, "reason": activation.get("summary", "")})
    save(project, proposal)
    return proposal


def _profile_change(project: Project, change: str, by: str) -> Any:
    profile = load_profile(project.profile_path)
    profile.profile_version += 1
    profile.history.append(HistoryEntry(profile.profile_version, change, by))
    return profile


def _activate_override(project: Project, proposal: StoredProposal) -> dict[str, Any]:
    c = proposal.content
    profile = _profile_change(project, f"AI {proposal.id}: {c['glob']} read as {c['language']}", "ai-approved")
    profile.file_overrides = [o for o in profile.file_overrides if o.glob != c["glob"]]
    profile.file_overrides.append(FileOverride(str(c["glob"]), str(c["language"]), str(c.get("reason", ""))))
    save_profile(project.profile_path, profile)
    return {"summary": f"override {c['glob']} -> {c['language']}", "profile": "file_overrides"}


def language_package(proposal: StoredProposal, tests: list[dict[str, str]]) -> dict[str, Any]:
    """The language package (package format 1) of an AI keyword proposal."""
    profile = proposal.content
    rules = {k: v for k, v in profile.items() if k not in _PROFILE_KEYS}
    document = proposal.provenance.get("document") or {}
    provenance: dict[str, Any] = {"source": "ai", "notes": f"AI proposal {proposal.id}"}
    if document.get("path"):
        provenance["document"] = str(document["path"])
    return {"package_format": 1, "language": proposal.target, "version": "0.1", "status": "proposed",
            "extensions": list(profile.get("extensions", [])), "backend": "keywords", "rules": rules,
            "naming": {"case_sensitive": bool(profile.get("case_sensitive", False)), "qualification": "lexical"},
            "relationships": ["calls", "maybe_calls", "includes"],
            "resolution": {"confidence": "heuristic", "capabilities": ["names"]},
            "limitations": ["Proposed by the AI from samples: heuristic keyword extraction."],
            "tests": tests, "provenance": provenance}


def _activate_language(project: Project, proposal: StoredProposal) -> dict[str, Any]:
    from codegraph_sci.rules import RuleWorkflowError, activate_rule

    independent = proposal.validation.get("independent_tests") or {}
    cases = independent.get("cases") or []
    if independent.get("status") != "passed" or not cases:
        raise ProposalError(f"{proposal.id}: a language package is activated only against expected results written "
                            "independently of the AI (cgs complete --expected <folder>); none passed")
    folder = project.rules_dir / "languages" / proposal.target
    if folder.exists():
        raise ProposalError(f"{folder} already exists: change that package instead")
    (folder / "tests").mkdir(parents=True)
    tests = []
    for case in cases:
        source, expected = Path(case["source"]), Path(case["expected"])
        shutil.copyfile(source, folder / "tests" / source.name)
        shutil.copyfile(expected, folder / "tests" / expected.name)
        tests.append({"source": f"tests/{source.name}", "expected": f"tests/{expected.name}"})
    path = folder / "language.yaml"
    path.write_bytes(yaml.safe_dump(language_package(proposal, tests), sort_keys=False,
                                    allow_unicode=True).encode("utf-8"))
    try:
        summary = activate_rule(path)  # validation, the independent tests, unambiguous selection
    except RuleWorkflowError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise ProposalError(f"{proposal.id}: {exc}") from exc
    return {"summary": summary, "package": str(path.relative_to(project.folder).as_posix())}


def _activate_bridge(project: Project, proposal: StoredProposal) -> dict[str, Any]:
    profile = load_profile(project.profile_path)
    number = 1 + max([int(r.id.split("-")[1]) for r in profile.rules if re.fullmatch(r"r-\d+", r.id)] or [0])
    rule_id = f"r-{number:04d}"
    project.rules_dir.mkdir(parents=True, exist_ok=True)
    (project.rules_dir / f"{rule_id}.yaml").write_bytes(
        yaml.safe_dump(proposal.content, sort_keys=False).encode("utf-8"))
    profile = _profile_change(project, f"AI {proposal.id}: bridge rule {rule_id} for {proposal.target}",
                              "ai-approved")
    profile.rules.append(RuleRef(rule_id, "bridge", "ai", "approved", f"rules/{rule_id}.yaml"))
    save_profile(project.profile_path, profile)
    return {"summary": f"bridge rule {rule_id}", "rule": rule_id}


def _activate_rule_change(project: Project, proposal: StoredProposal) -> dict[str, Any]:
    """Replace a rule file under ``rules/`` with the proposed data, kept only if it validates."""
    from codegraph_sci.rules import validate_rule

    rel = str(proposal.content["file"])
    path = (project.rules_dir / rel).resolve()
    if not path.is_relative_to(project.rules_dir.resolve()) or path.suffix != ".yaml":
        raise ProposalError(f"{proposal.id}: {rel!r} is not a rule file of this project")
    before = path.read_bytes() if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(yaml.safe_dump(proposal.content["data"], sort_keys=False, allow_unicode=True).encode("utf-8"))
    check = validate_rule(path)
    if check.errors:
        if before is None:
            path.unlink()
        else:
            path.write_bytes(before)
        raise ProposalError(f"{proposal.id}: {check.errors[0]}")
    return {"summary": f"rule file {rel} replaced", "file": rel}
