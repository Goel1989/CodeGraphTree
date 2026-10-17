"""Per-file detection: extension table, content signatures, variants."""

from __future__ import annotations

import re
from dataclasses import dataclass

from codegraph_sci.inventory.table import ExtensionTable

_SHEBANG = re.compile(r"^#!\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?([A-Za-z0-9_.+-]+)")
_MODE = re.compile(r"-\*-\s*(?:mode:\s*)?([\w+-]+)\s*;?.*-\*-|vim?:.*\b(?:ft|filetype)=([\w+-]+)")
_PREPROC = re.compile(r"(?m)^[ \t]*#[ \t]*(if|ifdef|ifndef|include|define|else|elif|endif)\b")
_PY2 = [
    re.compile(r"(?m)^[ \t]*print[ \t]+(?![(=])[\"'\w]"),
    re.compile(r"(?m)^[ \t]*print[ \t]*>>"),
    re.compile(r"(?m)^[ \t]*except[ \t]+[\w.]+[ \t]*,[ \t]*\w+[ \t]*:"),
    re.compile(r"(?m)^[ \t]*exec[ \t]+[\"'\w]"),
    re.compile(r"(?m)\b\d+L\b"),
    re.compile(r"(?m)^[ \t]*raise[ \t]+\w+[ \t]*,"),
]
_FIXED_COMMENT = re.compile(r"(?m)^[cC*][^\n]*$")
_FIXED_CODE = re.compile(r"(?m)^ {6}\S")
_FREE_HINT = re.compile(r"(?m)^\S.*(::|&\s*$)|^ {0,5}[a-zA-Z]")


@dataclass
class Detection:
    lang: str | None
    variant: str | None
    confidence: float
    decided_by: str
    status: str  # source, not_covered, ambiguous, unknown, ignored, binary


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def is_binary(head: bytes) -> bool:
    return b"\x00" in head


def file_ext(name: str) -> str:
    if name.startswith(".") and name.count(".") == 1:
        return name  # dot-files such as .gitignore
    dot = name.rfind(".")
    return name[dot:] if dot > 0 else ""


def fortran_variant(base: str | None, ext: str, text: str) -> str:
    form = base or ("fixed" if looks_fixed_form(text) else "free")
    preprocessed = any(ch.isupper() for ch in ext) or bool(_PREPROC.search(text))
    return f"{form}+preprocessed" if preprocessed else form


def looks_fixed_form(text: str) -> bool:
    comments = len(_FIXED_COMMENT.findall(text))
    code6 = len(_FIXED_CODE.findall(text))
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("!", "#"))]
    if not lines:
        return False
    starting_col1 = sum(1 for ln in lines if ln[:1].isalpha() and ln[:1] not in "cC")
    return (comments + code6) > 0 and code6 >= starting_col1


def python_variant(text: str) -> str | None:
    return "python2" if any(rx.search(text) for rx in _PY2) else None


def shebang_interpreter(text: str) -> str | None:
    """Interpreter named by a ``#!`` first line (``python3`` for ``#!/usr/bin/env python3``), if any."""
    m = _SHEBANG.match(text.split("\n", 1)[0])
    return m.group(1) if m else None


def signature_scores(table: ExtensionTable, text: str) -> dict[str, int]:
    head = "\n".join(text.splitlines()[: table.signature_lines])
    scores: dict[str, int] = {}
    for lang, rules in sorted(table.signatures.items()):
        scores[lang] = sum(weight * min(3, len(rx.findall(head))) for rx, weight in rules)
    return scores


def detect_by_content(table: ExtensionTable, text: str, candidates: list[str] | None = None
                      ) -> tuple[str | None, float, str]:
    """Shebang, editor mode line, then weighted keyword score. Returns (lang, confidence, rule)."""
    first = text.split("\n", 1)[0]
    m = _SHEBANG.match(first)
    if m:
        interp = re.sub(r"[\d.]+$", "", m.group(1))
        lang = table.shebang.get(m.group(1)) or table.shebang.get(interp)
        if lang and (candidates is None or lang in candidates):
            return lang, 1.0, f"shebang:{m.group(1)}"
    for line in text.splitlines()[:3]:
        mm = _MODE.search(line)
        if mm:
            mode = (mm.group(1) or mm.group(2) or "").lower()
            lang = table.modes.get(mode)
            if lang and (candidates is None or lang in candidates):
                return lang, 1.0, f"mode:{mode}"
    scores = signature_scores(table, text)
    if candidates is not None:
        scores = {k: v for k, v in scores.items() if k in candidates}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 4:
        return None, 0.0, "signature:none"
    best, score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if score < 2 * second and score - second < 4:
        return None, 0.0, "signature:tie"
    confidence = round(min(0.95, 0.5 + (score - second) / (2 * score + 1)), 2)
    return best, confidence, "signature:keywords"
