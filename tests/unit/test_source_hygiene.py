"""No control character in project sources: a stray one silently broke a regex (``end select``) in lot 12."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]
ALLOWED = {9, 10, 13}  # tab, line feed, carriage return


def test_no_control_characters_in_sources() -> None:
    offenders = []
    for folder in ("src", "tests", "tools", "packs"):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in (".py", ".yaml", ".json", ".sql", ".js", ".html", ".md", ".toml") or \
                    "vendor" in path.parts or "fixtures" in path.parts:
                continue
            for number, line in enumerate(path.read_bytes().split(b"\n"), start=1):
                if any(b < 32 and b not in ALLOWED for b in line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
