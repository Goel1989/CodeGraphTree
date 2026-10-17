"""Keyword adapter (§3.9): languages without a native adapter, described by a profile of keywords.

The profile only lists keywords and markers (written by hand or proposed by the AI); the core turns
them into extraction rules, deterministically. Extraction is heuristic: links get the confidence
``heuristic`` and the coverage of a profile is measured, never assumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from codegraph_sci.core.facts import Definition, FileFacts, ParseError, Reference, SourceFile, canonical_json
from codegraph_sci.core.ids import file_uid, kw_uid, variant_uid
from codegraph_sci.core.plugins import ExtractContext, sha256_text

VERSION = "2.0"


class KeywordProfileError(ValueError):
    pass


@dataclass
class KeywordProfile:
    language: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def extensions(self) -> list[str]:
        return [str(e) for e in self.data.get("extensions", [])]

    @property
    def case_sensitive(self) -> bool:
        return bool(self.data.get("case_sensitive", False))

    @property
    def status(self) -> str:
        return str(self.data.get("status", "approved"))


def _schema() -> dict[str, Any]:
    text = resources.files("codegraph_sci.extract.keywords").joinpath("language.schema.json").read_text(
        encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def load_keyword_profile(path: Path) -> KeywordProfile:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise KeywordProfileError(f"{path}: invalid YAML (only plain data is accepted): {exc}") from exc
    if not isinstance(data, dict):
        raise KeywordProfileError(f"{path}: key '(root)': expected a mapping")
    errors = sorted(jsonschema.Draft202012Validator(_schema()).iter_errors(data),
                    key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        err = errors[0]
        key = "/".join(str(p) for p in err.absolute_path) or "(root)"
        raise KeywordProfileError(f"{path}: key '{key}': {err.message} (value: {err.instance!r})")
    return KeywordProfile(str(data["language"]), data)


def _blank(text: str, profile: KeywordProfile) -> str:
    """Comments and string contents replaced by spaces (positions kept)."""
    data = profile.data
    comments = data.get("comments") or {}
    pieces: list[str] = []
    for start, end in comments.get("block", []):
        pieces.append(re.escape(start) + r".*?" + re.escape(end))
    for marker in comments.get("line", []):
        pieces.append(re.escape(marker) + r"[^\n]*")
    for quote in data.get("strings", []):
        q = re.escape(quote)
        pieces.append(q + r"(?:\\.|[^\\\n" + q + r"])*" + q)
    if not pieces:
        return text
    rx = re.compile("|".join(pieces), re.S)

    def repl(m: re.Match[str]) -> str:
        s = m.group(0)
        quote: str | None = next((str(q) for q in data.get("strings", []) if s.startswith(str(q))), None)
        if quote is not None:  # keep the quotes, blank the content
            return quote + re.sub(r"[^\n]", " ", s[len(quote):-len(quote)]) + quote
        return re.sub(r"[^\n]", " ", s)

    return rx.sub(repl, text)


class KeywordAdapter:
    def __init__(self, profile: KeywordProfile) -> None:
        self.profile = profile
        self.name = f"keywords:{profile.language}"
        self.version = f"{VERSION}+{sha256_text(canonical_json(profile.data))}"
        self.languages = [profile.language]

    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts:
        p = self.profile
        lang = p.language
        flags = 0 if p.case_sensitive else re.IGNORECASE
        text = file.text.replace("\r\n", "\n").replace("\r", "\n")
        clean = _blank(text, p)
        cont = p.data.get("line_continuation")
        definitions: list[Definition] = []
        references: list[Reference] = []
        errors: list[ParseError] = []
        stack: list[tuple[str, str, int, str]] = []  # (uid, name, start line, kind)
        counts: dict[str, int] = {}
        parents: dict[str, str | None] = {}
        def norm(s: str) -> str:
            return s if p.case_sensitive else s.lower()

        def_rules = [(re.compile(r"^\s*(?:" + "|".join(map(re.escape, d["keywords"])) + r")\s+([A-Za-z_][\w.]*)",
                                 flags), [norm(k) for k in d.get("end_keywords", [])], d.get("kind", "routine"))
                     for d in p.data.get("definitions", [])]
        end_words = {e for _rx, ends, _k in def_rules for e in ends}
        kw_calls = [re.compile(r"\b(?:" + "|".join(map(re.escape, c["keywords"])) + r")\s+([A-Za-z_][\w.]*)", flags)
                    for c in p.data.get("calls", []) if c.get("keywords")]
        paren_calls = [c for c in p.data.get("calls", []) if c.get("style") == "name_then_paren"]
        includes = [re.compile(r"^\s*(?:" + "|".join(map(re.escape, i["keywords"])) + r")\s+[\"']?([\w./-]+)", flags)
                    for i in p.data.get("includes", [])]
        def_words = {norm(k) for d in p.data.get("definitions", []) for k in d["keywords"]}
        call_words = {norm(k) for c in p.data.get("calls", []) for k in c.get("keywords", [])}
        lines = clean.split("\n")
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            first = norm(re.split(r"\W+", stripped, maxsplit=1)[0])
            if first in end_words and stack:
                uid, name, start, kind = stack.pop()
                definitions.append(Definition(uid, name, "routine" if kind == "routine" else kind,
                                              f"kw_{kind}", norm(name), (start, number), parent=parents[uid]))
                continue
            src = stack[-1][0] if stack else file_uid(file.path)
            matched_def = False
            for rx, _ends, kind in def_rules:
                m = rx.match(line)
                if m:
                    name = m.group(1)
                    qualified = ".".join([norm(s[1]) for s in stack] + [norm(name)])
                    base = kw_uid(lang, qualified, file.path)
                    counts[base] = counts.get(base, 0) + 1
                    uid = variant_uid(base, counts[base])
                    parents[uid] = stack[-1][0] if stack else None
                    stack.append((uid, name, number, str(kind)))
                    matched_def = True
                    break
            if matched_def:
                continue
            for rx in includes:
                m = rx.match(line)
                if m:
                    references.append(Reference(file_uid(file.path), m.group(1), "use", number, m.start(1) + 1,
                                                hint={"key": norm(m.group(1))}))
            taken: set[int] = set()
            for rx in kw_calls:
                for m in rx.finditer(line):
                    references.append(Reference(src, m.group(1), "call", number, m.start(1) + 1,
                                                confidence="heuristic", hint={"key": norm(m.group(1))}))
                    taken.add(m.start(1))
            for rule in paren_calls:
                for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", line):
                    word = norm(m.group(1))
                    if m.start(1) in taken or word in def_words or word in call_words:
                        continue
                    references.append(Reference(src, m.group(1), "maybe_call", number, m.start(1) + 1,
                                                confidence="heuristic",
                                                hint={"key": word,
                                                      "only_known_names": bool(rule.get("only_known_names", True))}))
            if cont and line.rstrip().endswith(str(cont)):
                continue
        while stack:
            uid, name, start, kind = stack.pop()
            errors.append(ParseError(f"definition {name} not closed", start))
            definitions.append(Definition(uid, name, "routine", f"kw_{kind}", norm(name), (start, len(lines)),
                                          parent=parents[uid]))
        return FileFacts(path=file.path, lang=lang, encoding=file.encoding, adapter=self.name,
                         adapter_version=self.version, definitions=definitions, references=references,
                         errors=errors, variant=file.variant).sort()
