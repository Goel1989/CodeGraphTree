"""Rule 15: project-owned content is English, even when instructions were given in another language.

Excluded on purpose (§0.4 of the corrective audit): analysed source code quoted by review sheets, fixtures that
intentionally represent foreign-language code or file names, and vendored third-party files.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
EXCLUDED = ("tests/fixtures/", "src/codegraph_sci/ui/web/vendor/",
            "tests/unit/test_english_only.py")  # this file lists the French words it looks for
EXCLUDED_PATTERNS = (re.compile(r"^tests/corpus/[^/]+/review/"),)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".sql", ".bat", ".js", ".html", ".spec",
                 ".cfg", ".ini", ""}
# French accented letters, written as escapes so that this file passes its own check.
ACCENTED = re.compile("[\u00e9\u00e8\u00e0\u00e7\u00ea\u00f9\u00f4\u00ee\u00e2\u00eb\u00ef\u00fb\u0153]", re.IGNORECASE)
FRENCH_WORDS = re.compile(r"\b(le|la|les|des|une|avec|pour|dans|sur|fichier|dossier|projet|aucun|sont|ou|et|est)\b")


def _project_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [f for f in out.decode("utf-8").split("\0") if f]
    return [f for f in files if not f.startswith(EXCLUDED) and not any(p.match(f) for p in EXCLUDED_PATTERNS)
            and Path(f).suffix.lower() in TEXT_SUFFIXES]


def test_project_owned_text_is_english() -> None:
    offenders = []
    for rel in _project_files():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if ACCENTED.search(line) or len(FRENCH_WORDS.findall(line)) >= 3:
                offenders.append(f"{rel}:{number}: {line.strip()[:100]}")
                break
    assert offenders == []


def test_project_owned_file_names_are_english() -> None:
    french = re.compile("(lancer|lisez|strategie|fichier|dossier|projet|\u00e9l\u00e9ment)", re.IGNORECASE)
    allowed = {"strategie_licence.md"}  # the owner's original specification at the root (kept until they decide)
    offenders = [f for f in _project_files() if french.search(Path(f).name) and f not in allowed]
    assert offenders == []
