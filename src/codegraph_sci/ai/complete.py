"""AI roles 1 and 2 (§3.13): identify unknown languages, define missing keywords (keyword profiles,
bridge rules). What to ask comes from the deterministic diagnosis (``ai/diagnose.py``). Proposals are checked
automatically (replaying Link on the cached facts, extracting samples, and comparing with expected results
written independently of the AI), then stored as drafts, validated or rejected (``ai/proposals.py``): generating
never changes the active analysis. Only an explicit approval activates a validated proposal; automatic approval
needs a project policy configured separately. The analysis itself never calls the AI.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.ai.diagnose import Diagnosis, diagnose
from codegraph_sci.ai.proposals import ProposalError, approve, auto_approval_enabled, record
from codegraph_sci.ai.worker import AIClient
from codegraph_sci.core.facts import FileFacts, SourceFile, decode_facts
from codegraph_sci.core.plugins import ExtractContext, decode_bytes, sha256_text
from codegraph_sci.core.profile import HistoryEntry
from codegraph_sci.core.project import Project
from codegraph_sci.enrich.packs import _schema as pack_schema
from codegraph_sci.extract.keywords import KeywordAdapter, KeywordProfile
from codegraph_sci.inventory.profile_io import load_profile, save_profile
from codegraph_sci.inventory.run import run_inventory
from codegraph_sci.link.linker import Linker
from codegraph_sci.query.api import GraphQuery, site_pattern
from codegraph_sci.scan import ScanOptions, in_scope, load_bridge_rules, native_adapters, scan
from codegraph_sci.store.cache import load_cache

NATIVE = ("fortran", "python", "c", "cpp")


def _sample_half(path: str) -> int:
    """Stable file partition; independent of the interpreter's randomized hash seed."""
    return int(sha256_text(path), 16) % 2


IDENTIFY_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["language", "use_adapter", "rationale"],
    "properties": {"language": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                   "use_adapter": {"enum": [*NATIVE, "keywords", "none"]},
                   "rationale": {"type": "string", "maxLength": 400}}}
THRESHOLDS = {"min_gain": 0.5, "max_new_sites_per_kloc": 200.0, "min_plausible": 0.9, "max_stability_gap": 0.10}


def bridge_schema() -> dict[str, Any]:
    full = pack_schema()
    schema: dict[str, Any] = full["$defs"]["bridge"]
    return {**schema, "required": ["from", "to", "call_prefixes", "name_transform"], "$defs": full["$defs"]}


def keyword_schema() -> dict[str, Any]:
    text = resources.files("codegraph_sci.extract.keywords").joinpath("language.schema.json").read_text(
        encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


@dataclass
class Proposal:
    kind: str  # override, keywords, bridge
    target: str  # extension, language or site pattern
    content: dict[str, Any]
    checks: dict[str, Any] = field(default_factory=dict)
    accepted: bool = False  # passed its validation (not an approval)
    reason: str = ""
    preview: dict[str, Any] = field(default_factory=dict)
    rule_id: str | None = None
    id: str | None = None  # p-0001 once stored
    status: str = "draft"  # draft, validated, rejected, approved
    provenance: dict[str, Any] = field(default_factory=dict)
    independent: dict[str, Any] = field(default_factory=dict)  # expected results written independently


@dataclass
class DocumentInput:
    """A user-provided document: read, or the reason it could not be (never dropped silently)."""

    path: str | None
    status: str  # none, read, missing, unreadable, pdf_unsupported
    sha256: str | None = None
    text: str = ""
    error: str = ""

    def reference(self) -> dict[str, Any]:
        return {"path": self.path, "status": self.status, "sha256": self.sha256, "error": self.error or None}


# ------------------------------------------------------------------ helpers
def _samples(root: Path, paths: list[str], n: int = 3, lines: int = 40) -> str:
    out = []
    for p in sorted(paths)[:n]:
        text, _ = decode_bytes((root / p).read_bytes())
        out.append(f"--- {p}\n" + "\n".join(text.splitlines()[:lines]))
    return "\n".join(out)


def read_document(path: Path | None, limit: int = 6000) -> DocumentInput:
    """Text of a technical document (text, Markdown, PDF), or why it could not be read."""
    import hashlib

    if path is None:
        return DocumentInput(None, "none")
    if not path.is_file():
        return DocumentInput(str(path), "missing", error="file not found")
    try:
        data = path.read_bytes()
    except OSError as exc:
        return DocumentInput(str(path), "unreadable", error=str(exc))
    digest = hashlib.sha256(data).hexdigest()
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return DocumentInput(str(path), "pdf_unsupported", digest, error="PDF support (pypdf) is not installed")
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages[:20])
        except Exception as exc:  # noqa: BLE001 - any parsing failure of a damaged PDF is reported
            return DocumentInput(str(path), "unreadable", digest, error=f"{type(exc).__name__}: {exc}")
    else:
        text = data.decode("utf-8", errors="replace")
    if not text.strip():
        return DocumentInput(str(path), "unreadable", digest, error="no text could be extracted")
    return DocumentInput(str(path), "read", digest, text[:limit])


def _evidence_from_document(doc: DocumentInput, profile: dict[str, Any]) -> dict[str, Any]:
    """Passages of the document that support the proposed keywords, and what is assumed without support."""
    words = sorted({str(k) for section in ("definitions", "calls", "includes") for rule in profile.get(section, [])
                    for k in list(rule.get("keywords", [])) + list(rule.get("end_keywords", []))})
    if doc.status != "read":
        return {"passages": [], "assumptions": [f"no document read ({doc.status}): every keyword comes from samples"]}
    lower = doc.text.lower()
    passages: list[str] = []
    for line in doc.text.splitlines():
        if any(re.search(rf"\b{re.escape(w.lower())}\b", line.lower()) for w in words) and line.strip():
            passages.append(line.strip()[:200])
        if len(passages) >= 10:
            break
    assumptions = [f"keyword {w!r} is not in the document: taken from the samples" for w in words
                   if not re.search(rf"\b{re.escape(w.lower())}\b", lower)]
    for marker in (profile.get("comments") or {}).get("line", []):
        if str(marker) not in doc.text:
            assumptions.append(f"comment marker {marker!r} is not in the document: taken from the samples")
    return {"passages": passages, "assumptions": assumptions}


def independent_results(expected: Path | None, language: str, adapter: Any) -> dict[str, Any]:
    """Compare the extraction with expected results written independently of the AI.

    ``expected`` holds pairs ``<case>.<ext>`` + ``<case>.expected.json`` (format of language tests, phase 4).
    Recall and precision of definitions are measured against those files, never against the proposed keywords.
    """
    from codegraph_sci.rules import facts_view

    if expected is None or not expected.is_dir():
        return {"status": "none"}
    cases, details = [], []
    found = expected_defs = matched = 0
    for exp in sorted(expected.glob("*.expected.json")):
        stem = exp.name[: -len(".expected.json")]
        sources = [s for s in sorted(expected.glob(f"{stem}.*")) if s != exp and not s.name.endswith(".json")]
        if not sources:
            details.append(f"{exp.name}: no source file {stem}.<ext>")
            continue
        source = sources[0]
        text, enc = decode_bytes(source.read_bytes())
        actual = facts_view(adapter.extract(SourceFile(f"tests/{source.name}", language, None, enc, text),
                                            ExtractContext()))
        want = json.loads(exp.read_text(encoding="utf-8"))
        ok = True
        for section in ("definitions", "references"):
            if section not in want:
                continue
            w = {json.dumps(x, sort_keys=True) for x in want[section]}
            g = {json.dumps(x, sort_keys=True) for x in actual[section]}
            if section == "definitions":
                expected_defs += len(w)
                found += len(g)
                matched += len(w & g)
            if w != g:
                ok = False
                details += [f"{source.name}: missing {section[:-1]} {x}" for x in sorted(w - g)][:5]
                details += [f"{source.name}: unexpected {section[:-1]} {x}" for x in sorted(g - w)][:5]
        cases.append({"source": str(source), "expected": str(exp), "passed": ok})
    if not cases:
        return {"status": "none", "details": details}
    return {"status": "passed" if all(c["passed"] for c in cases) and not details else "failed", "cases": cases,
            "definitions_recall": round(matched / expected_defs, 3) if expected_defs else None,
            "definitions_precision": round(matched / found, 3) if found else None, "details": details}


def _cached_facts(project: Project) -> list[FileFacts]:
    return [decode_facts(b) for _k, b in sorted(load_cache(project.db_path).items())]


def _relink(project: Project, facts: list[FileFacts], extra_rules: list[dict[str, Any]]) -> dict[tuple[str, int, int, str], str | None]:
    profile = load_profile(project.profile_path)
    full = [f for f in facts if in_scope(f.path, profile)]
    outline = [f for f in facts if not in_scope(f.path, profile)]
    info: dict[str, tuple[str | None, int]] = {f.path: (f.lang, 1) for f in facts}
    rules = load_bridge_rules(project, profile) + extra_rules
    result = Linker(full, outline, info, bridge_rules=rules).run()
    return {(s.file, s.line, s.col, s.target_text): s.dst for s in result.call_sites}


# ------------------------------------------------------------ the engine
class Completion:
    def __init__(self, project: Project, client: AIClient, *, auto: bool = False, document: Path | None = None,
                 expected: Path | None = None, max_iterations: int = 3, max_calls: int = 10) -> None:
        self.project = project
        self.client = client
        self.auto = auto  # approve validated proposals through the project policy (cgs ai-policy)
        self.document = document
        self.expected = expected  # expected results written independently of the AI (language proposals)
        self.max_iterations = max_iterations
        self.max_calls = max_calls
        self.proposals: list[Proposal] = []
        self.asked: set[tuple[str, str]] = set()
        self.diagnosis: list[Diagnosis] = []
        self.doc = read_document(document)

    def run(self) -> list[Proposal]:
        """Propose, validate and store. Without the automatic policy nothing active changes and nothing is
        rescanned: the user approves (``cgs ai-approve``), then runs ``cgs scan``."""
        if self.auto and not auto_approval_enabled(self.project):
            raise ProposalError("automatic approval is not enabled for this project: run "
                                "`cgs ai-policy <folder> --auto-approve on` first, or approve proposals one by one")
        if not self.project.db_path.is_file():
            scan(self.project, ScanOptions())
        for _ in range(self.max_iterations):
            self.diagnosis = diagnose(self.project)
            new = self.identify_languages() + self.missing_packages() + self.bridge_rules()
            for p in new:
                self._store(p)
            if not self.auto:
                break
            approved = 0
            for p in new:
                if p.status != "validated" or p.id is None:
                    continue
                try:
                    approve(self.project, p.id, by="auto-policy")
                except ProposalError as exc:
                    p.reason = f"{p.reason}; not approved: {exc}"
                    continue
                p.status = "approved"
                approved += 1
            if not approved:
                break
            scan(self.project, ScanOptions())
        return self.proposals

    def _store(self, p: Proposal) -> None:
        kind = {"override": "override", "keywords": "language", "bridge": "bridge"}[p.kind]
        provenance = {"model": self.client.model_spec, "task": p.kind, "document": self.doc.reference(),
                      **p.provenance}
        stored = record(self.project, kind, p.target, p.content, passed=p.accepted, reason=p.reason,
                        checks={**p.checks, **({"preview": p.preview} if p.preview else {})},
                        provenance=provenance, independent=p.independent or None)
        p.id, p.status = stored.id, stored.status

    # ---------------------------------------------------------- role 1
    def missing_packages(self) -> list[Proposal]:
        """Languages the inventory knows (``.jl``, ``.rs``…) without an installed package: a keyword package."""
        out: list[Proposal] = []
        for d in self.diagnosis:
            if d.kind != "missing_package" or ("keywords", d.target) in self.asked or self.client.calls >= \
                    self.max_calls:
                continue
            self.asked.add(("keywords", d.target))
            profile = load_profile(self.project.profile_path)
            paths = [e.path for e in run_inventory(self.project.root, profile).entries if e.lang == d.target]
            ext = Path(paths[0]).suffix if paths else ""
            out.append(self._keyword_profile(ext, paths, d.target))
        self.proposals += out
        return out

    def identify_languages(self) -> list[Proposal]:
        out: list[Proposal] = []
        unknown = {d.target: d for d in self.diagnosis if d.kind == "unknown_language"}
        profile = load_profile(self.project.profile_path)
        groups = run_inventory(self.project.root, profile).unknown_groups if unknown else {}
        for ext, paths in groups.items():
            if ("identify", ext) in self.asked or self.client.calls >= self.max_calls:
                continue
            self.asked.add(("identify", ext))
            prompt = (f"Files with extension {ext!r} ({len(paths)} files) could not be identified.\n"
                      f"Languages already covered: {', '.join(NATIVE)}.\n"
                      "Say which language they are written in, and whether an existing adapter can read them "
                      "('keywords' if a keyword profile is needed, 'none' if they are not source code).\n"
                      f"Samples:\n{_samples(self.project.root, paths)}")
            answer = self.client.ask("identify", ext, prompt, IDENTIFY_SCHEMA)
            if answer["use_adapter"] in NATIVE:
                out.append(self._check_override(ext, paths, answer))
            elif answer["use_adapter"] == "keywords":
                out.append(self._keyword_profile(ext, paths, answer["language"]))
        self.proposals += out
        return out

    def _check_override(self, ext: str, paths: list[str], answer: dict[str, Any]) -> Proposal:
        lang = str(answer["use_adapter"])
        adapter = native_adapters()[lang]
        defs, errors = 0, 0
        for p in sorted(paths)[:5]:
            text, enc = decode_bytes((self.project.root / p).read_bytes())
            variant = "free" if lang == "fortran" else None
            try:
                facts = adapter.extract(SourceFile(p, lang, variant, enc, text), ExtractContext())
            except Exception:  # noqa: BLE001 - a failing adapter rejects the proposal
                errors += 1
                continue
            defs += len(facts.definitions)
            errors += int(facts.used_fallback)
        prop = Proposal("override", ext, {"glob": f"*{ext}", "language": lang,
                                          "reason": f"AI: {str(answer['rationale'])[:120]}"},
                        checks={"sample_files": min(5, len(paths)), "definitions": defs, "errors": errors})
        prop.accepted = errors == 0 and defs > 0
        prop.reason = "ok" if prop.accepted else "the adapter does not read the samples (errors or no definition)"
        return prop

    def _keyword_profile(self, ext: str, paths: list[str], language: str) -> Proposal:
        doc = self.doc.text if self.doc.status == "read" else ""
        prompt = (f"Write a keyword profile for the language {language!r} (files {ext}): definition keywords "
                  "and their end keywords, call keywords, name(...) calls, include keywords, comment and string "
                  "markers. Use plain keywords, never regular expressions.\n"
                  + (f"Technical document:\n{doc}\n" if doc else "")
                  + f"Samples:\n{_samples(self.project.root, paths, n=3, lines=80)}")
        answer = self.client.ask("keywords", language, prompt, keyword_schema())
        answer = {**answer, "language": language, "source": "ai", "format_version": 1}
        answer.setdefault("extensions", [ext])
        rng = random.Random(0)
        ordered = sorted(paths)
        rng.shuffle(ordered)
        halves = [ordered[: max(1, len(ordered) // 2)], ordered[max(1, len(ordered) // 2):] or ordered[:1]]
        stats = []
        adapter = KeywordAdapter(KeywordProfile(language, answer))
        independent = independent_results(self.expected, language, adapter)
        for half in halves:
            defs = calls = expected_defs = 0
            def_words = {k.lower() for d in answer.get("definitions", []) for k in d["keywords"]}
            for p in half:
                text, enc = decode_bytes((self.project.root / p).read_bytes())
                facts = adapter.extract(SourceFile(p, language, None, enc, text), ExtractContext())
                defs += len(facts.definitions)
                calls += sum(1 for r in facts.references if r.kind in ("call", "maybe_call"))
                expected_defs += sum(1 for line in text.splitlines()
                                     if line.strip() and line.split()[0].lower() in def_words)
            # Matches of the proposed keywords themselves: a consistency check, not a measured recall.
            stats.append({"files": len(half), "definitions": defs, "calls": calls,
                          "keyword_consistency": defs / expected_defs if expected_defs else 0.0})
        gap = abs(stats[0]["keyword_consistency"] - stats[1]["keyword_consistency"])
        stable = gap < THRESHOLDS["max_stability_gap"] + 1e-9
        prop = Proposal("keywords", language, answer, checks={"halves": stats, "stable": stable},
                        independent=independent)
        problems = []
        if not all(s["definitions"] > 0 for s in stats) or not stable:
            problems.append("too few definitions found, or unstable between samples")
        if independent["status"] == "failed":
            problems.append("independent expected results not met: " + "; ".join(independent.get("details", [])[:3]))
        prop.accepted = not problems
        prop.reason = "ok" if prop.accepted else "; ".join(problems)
        if independent["status"] == "passed":
            answer["coverage"] = {"sample_files": len(independent["cases"]),
                                  "definitions_recall": independent["definitions_recall"]}
        else:
            prop.reason += " (recall not measured: no independent expected results)" if prop.accepted else ""
        prop.provenance = {**_evidence_from_document(self.doc, answer),
                           "examples": sorted(paths)[:3]}
        return prop

    # ---------------------------------------------------------- role 2
    def bridge_rules(self) -> list[Proposal]:
        with GraphQuery(self.project.db_path) as q:
            groups = [g for g in q.unresolved(limit=200) if g.pattern.endswith("_*") and g.count >= 3
                      and g.lang in ("c", "cpp", "fortran", "python")]
            examples: dict[str, list[str]] = {}
            for g in groups:
                lines = []
                for ex in g.examples[:4]:
                    src = q.source(f"file:{ex['file']}", ex["line"], ex["line"])
                    lines.append(f"{ex['file']}:{ex['line']}: {src.lines[0].strip() if src.lines else ''}")
                examples[g.pattern] = lines
            routines: list[str] = []
        out: list[Proposal] = []
        facts: list[FileFacts] | None = None
        for g in groups:
            key = f"{g.lang}:{g.pattern}"
            if ("bridge", key) in self.asked or self.client.calls >= self.max_calls:
                continue
            self.asked.add(("bridge", key))
            prompt = (f"{g.count} call sites from {g.lang} with the prefix pattern {g.pattern!r} are unresolved. "
                      "If this prefix calls routines of another language, give the bridge rule: source and target "
                      "languages, call prefixes, and the name transform (strip_prefix, lowercase, uppercase, "
                      "append_underscore, strip_underscore).\nExamples:\n" + "\n".join(examples[g.pattern])
                      + (f"\nKnown routines: {', '.join(routines[:50])}" if routines else ""))
            answer = self.client.ask("bridge", key, prompt, bridge_schema())
            if facts is None:
                facts = _cached_facts(self.project)
            out.append(self._check_bridge(g, answer, facts))
        self.proposals += out
        return out

    def _check_bridge(self, group: Any, rule: dict[str, Any], facts: list[FileFacts]) -> Proposal:
        base = _relink(self.project, facts, [])
        new = _relink(self.project, facts, [rule])
        targeted = [k for k, dst in base.items() if dst is None and site_pattern(k[3]) == group.pattern]
        gained = [k for k in targeted if new.get(k) is not None]
        changed = [k for k, dst in base.items() if dst is not None and new.get(k) != dst]
        added = [k for k, dst in new.items() if dst is not None and base.get(k) is None]
        to_lang = str(rule.get("to"))
        prefix = {"fortran": "f:", "c": "c:", "cpp": "cpp:", "python": "py:"}.get(to_lang, "")
        plausible = sum(1 for k in gained if str(new[k]).startswith(prefix)) / len(gained) if gained else 0.0
        halves = [[k for k in targeted if _sample_half(k[0]) == i] for i in (0, 1)]
        rates = [sum(1 for k in h if new.get(k) is not None) / len(h) for h in halves if h]
        kloc = max(1.0, sum(1 for _ in facts) / 10)
        checks = {"targeted": len(targeted), "gain": len(gained) / len(targeted) if targeted else 0.0,
                  "regressions": len(changed), "added": len(added), "plausible": plausible,
                  "stability_gap": max(rates) - min(rates) if len(rates) == 2 else 0.0,
                  "new_sites_per_kloc": len(added) / kloc}
        problems = []
        if checks["gain"] < THRESHOLDS["min_gain"]:
            problems.append(f"gain {checks['gain']:.0%} < 50%")
        if checks["regressions"]:
            problems.append(f"{checks['regressions']} existing link(s) changed")
        if checks["plausible"] < THRESHOLDS["min_plausible"]:
            problems.append(f"plausible targets {checks['plausible']:.0%} < 90%")
        if checks["stability_gap"] >= THRESHOLDS["max_stability_gap"]:
            problems.append("unstable between two samples")
        if checks["new_sites_per_kloc"] > THRESHOLDS["max_new_sites_per_kloc"]:
            problems.append("too many new links")
        prop = Proposal("bridge", group.pattern, rule, checks=checks, accepted=not problems,
                        reason="ok" if not problems else "; ".join(problems))
        prop.preview = {"added": len(added), "removed": len(changed),
                        "examples": [{"file": k[0], "line": k[1], "target": k[3], "dst": new[k]}
                                     for k in sorted(gained)[:10]]}
        return prop



def set_rule_status(project: Project, rule_id: str, status: str) -> None:
    """Status of a rule written by an earlier version (``rules/r-<n>.yaml`` or a keyword profile in the profile).
    New proposals go through ``ai/proposals.py`` (``cgs ai-approve p-<n>``)."""
    profile = load_profile(project.profile_path)
    found = False
    for r in profile.rules:
        if r.id == rule_id:
            r.status, found = status, True
    if rule_id in profile.languages:
        profile.languages[rule_id].status = status
        path = project.rules_dir / "languages" / f"{rule_id}.yaml"
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["status"] = status
            path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        found = True
    if not found:
        raise KeyError(rule_id)
    profile.profile_version += 1
    profile.history.append(HistoryEntry(profile.profile_version, f"{rule_id} {status}", "user"))
    save_profile(project.profile_path, profile)
