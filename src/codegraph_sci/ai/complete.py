"""AI roles 1 and 2 (§3.13): identify unknown languages, define missing keywords (keyword profiles,
bridge rules). Proposals are checked automatically by replaying Link on the cached facts, shown
as a preview (links added/removed), then written to the analysis profile — approved in one click,
or automatically when the project enables it. The analysis itself never calls the AI.
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

from codegraph_sci.ai.worker import AIClient
from codegraph_sci.core.facts import FileFacts, SourceFile, decode_facts
from codegraph_sci.core.plugins import ExtractContext, decode_bytes, sha256_text
from codegraph_sci.core.profile import FileOverride, HistoryEntry, LanguageEntry, RuleRef
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
    accepted: bool = False
    reason: str = ""
    preview: dict[str, Any] = field(default_factory=dict)
    rule_id: str | None = None


# ------------------------------------------------------------------ helpers
def _samples(root: Path, paths: list[str], n: int = 3, lines: int = 40) -> str:
    out = []
    for p in sorted(paths)[:n]:
        text, _ = decode_bytes((root / p).read_bytes())
        out.append(f"--- {p}\n" + "\n".join(text.splitlines()[:lines]))
    return "\n".join(out)


def _document(path: Path | None, limit: int = 6000) -> str:
    if path is None or not path.is_file():
        return ""
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages[:20])
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


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
                 max_iterations: int = 3, max_calls: int = 10) -> None:
        self.project = project
        self.client = client
        self.auto = auto
        self.document = document
        self.max_iterations = max_iterations
        self.max_calls = max_calls
        self.proposals: list[Proposal] = []
        self.asked: set[tuple[str, str]] = set()

    def run(self) -> list[Proposal]:
        if not self.project.db_path.is_file():
            scan(self.project, ScanOptions())
        for _ in range(self.max_iterations):
            new = self.identify_languages() + self.bridge_rules()
            if not any(p.accepted for p in new):
                break
            self.adopt([p for p in new if p.accepted])
            scan(self.project, ScanOptions())
        return self.proposals

    # ---------------------------------------------------------- role 1
    def identify_languages(self) -> list[Proposal]:
        profile = load_profile(self.project.profile_path)
        inv = run_inventory(self.project.root, profile)
        out: list[Proposal] = []
        for ext, paths in inv.unknown_groups.items():
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
        doc = _document(self.document)
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
            stats.append({"files": len(half), "definitions": defs, "calls": calls,
                          "recall": defs / expected_defs if expected_defs else 0.0})
        stable = abs(stats[0]["recall"] - stats[1]["recall"]) < THRESHOLDS["max_stability_gap"] + 1e-9
        prop = Proposal("keywords", language, answer, checks={"halves": stats, "stable": stable})
        prop.accepted = all(s["definitions"] > 0 for s in stats) and stable
        prop.reason = "ok" if prop.accepted else "too few definitions found, or unstable between samples"
        answer["coverage"] = {"sample_files": len(paths), "definitions_recall": round(
            sum(s["recall"] for s in stats) / len(stats), 3)}
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

    # ---------------------------------------------------------- adoption
    def adopt(self, proposals: list[Proposal]) -> None:
        """Write accepted proposals to the profile: approved in auto mode, proposed otherwise."""
        write_proposals(self.project, proposals, approved=self.auto)


def write_proposals(project: Project, proposals: list[Proposal], approved: bool) -> None:
    profile = load_profile(project.profile_path)
    status = "approved" if approved else "proposed"
    for p in proposals:
        if p.kind == "override":
            profile.file_overrides.append(FileOverride(p.content["glob"], p.content["language"],
                                                       p.content["reason"]))
            change = f"AI: {p.target} read as {p.content['language']}"
        elif p.kind == "keywords":
            folder = project.rules_dir / "languages"
            folder.mkdir(parents=True, exist_ok=True)
            content = {**p.content, "status": status}
            (folder / f"{p.target}.yaml").write_text(yaml.safe_dump(content, sort_keys=False, allow_unicode=True),
                                                     encoding="utf-8")
            profile.languages[p.target] = LanguageEntry(0, f"keywords:{p.target}", source="ai", status=status)
            change = f"AI: keyword profile {p.target} ({status})"
        else:
            n = 1 + max([int(r.id.split("-")[1]) for r in profile.rules if re.fullmatch(r"r-\d+", r.id)] or [0])
            rule_id = f"r-{n:04d}"
            project.rules_dir.mkdir(parents=True, exist_ok=True)
            (project.rules_dir / f"{rule_id}.yaml").write_text(yaml.safe_dump(p.content, sort_keys=False),
                                                                encoding="utf-8")
            profile.rules.append(RuleRef(rule_id, "bridge", "ai", status, f"rules/{rule_id}.yaml"))
            p.rule_id = rule_id
            change = f"AI: bridge rule {rule_id} for {p.target} ({status})"
        profile.profile_version += 1
        profile.history.append(HistoryEntry(profile.profile_version, change, "ai"))
    save_profile(project.profile_path, profile)


def set_rule_status(project: Project, rule_id: str, status: str) -> None:
    """One-click validation: approve or reject a proposed rule or keyword profile."""
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
