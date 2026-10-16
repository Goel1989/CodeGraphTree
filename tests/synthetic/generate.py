"""Synthetic multi-language repository whose inventory and call graph are known by construction (§5.3).

Usage:
    python tests/synthetic/generate.py OUT --routines 15000 --files 3000 \
        --langs fortran,python,cpp,c --seed 42 [--calls 6] [--hubs 10]

Same parameters -> same repository (byte for byte). ``generate`` returns the expected graph:
``{"files": {path: lang}, "routines": {uid: path}, "calls": {src_uid: [[dst_uid, line, col], ...]}}``.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

LANGS = ("fortran", "python", "cpp", "c")
EXT = {"fortran": ".f90", "python": ".py", "cpp": ".cpp", "c": ".c"}
PREFIX = {"fortran": "r", "python": "p", "cpp": "x", "c": "c"}


def _name(lang: str, i: int) -> str:
    return f"{PREFIX[lang]}_{i:05d}"


def _uid(lang: str, name: str, module: str) -> str:
    if lang == "fortran":
        return f"f:{name}"
    if lang == "c":
        return f"c:{name}"
    if lang == "cpp":
        return f"cpp:syn::{name}()"
    return f"py:{module}.{name}"


def generate(out: Path, routines: int = 15000, files: int = 3000, langs: tuple[str, ...] = LANGS,
             seed: int = 42, calls: int = 6, hubs: int = 10) -> dict[str, Any]:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    expected: dict[str, Any] = {"files": {}, "routines": {}, "calls": {}}
    per_lang_routines = routines // len(langs)
    per_lang_files = max(1, files // len(langs))
    for lang in langs:
        folder = out / lang
        folder.mkdir(exist_ok=True)
        if lang == "python":
            (folder / "__init__.py").write_text('"""Synthetic package."""\n', encoding="utf-8", newline="\n")
            expected["files"]["python/__init__.py"] = "python"
        names = [_name(lang, i) for i in range(per_lang_routines)]
        file_of = {name: i % per_lang_files for i, name in enumerate(names)}
        module_of = {name: f"python.m_{file_of[name]:04d}" for name in names}
        hub_names = names[:hubs]
        callees: dict[str, list[str]] = {}
        for i, name in enumerate(names):
            k = rng.randint(0, 2 * calls)
            pool = [names[rng.randrange(len(names))] for _ in range(k)]
            if i >= hubs and rng.random() < 0.5:
                pool.append(hub_names[rng.randrange(len(hub_names))])
            callees[name] = [c for c in pool if c != name]
        by_file: dict[int, list[str]] = {}
        for name in names:
            by_file.setdefault(file_of[name], []).append(name)
        for index in sorted(by_file):
            rel = f"{lang}/m_{index:04d}{EXT[lang]}"
            module = f"python.m_{index:04d}"
            lines: list[str] = []
            if lang == "python":
                imports = sorted({module_of[c] for n in by_file[index] for c in callees[n]} - {module})
                for mod in imports:
                    lines.append(f"from python import {mod.split('.')[-1]}")
                lines.append("")
            if lang == "cpp":
                lines.append("namespace syn {")
            for name in by_file[index]:
                uid = _uid(lang, name, module)
                expected["routines"][uid] = rel
                sites: list[list[Any]] = []
                if lang == "fortran":
                    lines.append(f"subroutine {name}()")
                    for c in callees[name]:
                        lines.append(f"  call {c}()")
                        sites.append([_uid(lang, c, ""), len(lines), 8])
                    lines.append(f"end subroutine {name}")
                elif lang in ("c", "cpp"):
                    lines.append(f"void {name}(void) {{" if lang == "c" else f"void {name}() {{")
                    for c in callees[name]:
                        lines.append(f"    {c}();")
                        sites.append([_uid(lang, c, ""), len(lines), 5])
                    lines.append("}")
                else:
                    lines.append(f"def {name}():")
                    for c in callees[name]:
                        if module_of[c] == module:
                            lines.append(f"    {c}()")
                        else:
                            lines.append(f"    {module_of[c].split('.')[-1]}.{c}()")
                        sites.append([_uid(lang, c, module_of[c]), len(lines), 5])
                    lines.append("    return None")
                lines.append("")
                expected["calls"][uid] = sites
            if lang == "cpp":
                lines.append("}")
            (out / rel).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            expected["files"][rel] = lang
    return expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--routines", type=int, default=15000)
    parser.add_argument("--files", type=int, default=3000)
    parser.add_argument("--langs", default=",".join(LANGS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calls", type=int, default=6)
    parser.add_argument("--hubs", type=int, default=10)
    args = parser.parse_args()
    expected = generate(args.out, args.routines, args.files, tuple(args.langs.split(",")), args.seed,
                        args.calls, args.hubs)
    (args.out.parent / f"{args.out.name}.expected.json").write_text(json.dumps(expected), encoding="utf-8")
    n_sites = sum(len(v) for v in expected["calls"].values())
    print(f"{len(expected['files'])} files, {len(expected['routines'])} routines, {n_sites} call sites")


if __name__ == "__main__":
    main()
