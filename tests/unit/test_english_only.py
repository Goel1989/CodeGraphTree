"""Rule 15: project-owned content is English, even when instructions were given in another language.

Excluded on purpose (§0.4 of the corrective audit): analysed source code quoted by review sheets, fixtures that
intentionally represent foreign-language code or file names, and vendored third-party files.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
EXCLUDED = ("tests/fixtures/", "src/codegraph_sci/ui/web/vendor/")
EXCLUDED_PATTERNS = (re.compile(r"^tests/corpus/[^/]+/review/"),)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".sql", ".bat", ".js", ".html", ".spec",
                 ".cfg", ".ini", ""}
ACCENTED = re.compile(r"[éèàçêùôîâëïûœ]", re.IGNORECASE)
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
    french = re.compile(r"(lancer|lisez|strategie|fichier|dossier|projet|élément)", re.IGNORECASE)
    allowed = {"docs/strategie_licence.md", "strategie_licence.md"}  # replaced by LICENSING.md in phase 2
    offenders = [f for f in _project_files() if french.search(Path(f).name) and f not in allowed]
    assert offenders == []
