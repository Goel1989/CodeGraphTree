# CodeGraph-Sci

Offline desktop call-graph explorer for multi-language scientific code: **Fortran, Python, C, C++** and the bridges
between them (Fortran↔C `bind(c)` and naming conventions, C/C++ macros, pybind11, Python C extensions).

Given a source folder, CodeGraph-Sci identifies the languages file by file, builds a deterministic call graph and
stores it in a local SQLite database. Every observed call is kept as a call site (file, line, column, preprocessor
condition, confidence, origin). The desktop window answers "who calls this routine, and how many?", what it calls,
how files are linked, the path between two routines and the impact of a change, with 3D views of functions and files.

- **Offline**: CodeGraph-Sci does not require a cloud service and does not send analysed source code to a remote service. Analysis and optional local AI execution run on the user's machine. Its processes refuse network sockets (a Python-level guard, not an operating-system sandbox) and open no port.
- **Modest machines**: CPU only, the interface never loads the whole graph.
- **Source-available, dual-licensed**: see [License](#license).

## Install (development)

Python 3.12 is required.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

On Linux use `.venv/bin/python`. The optional standalone 3D window (`cgs view3d`) needs the `view3d` extra.

## Use

Desktop application (Windows: `Start_CodeGraph-Sci.bat`):

```bash
.venv/Scripts/python -m codegraph_sci.ui.app
```

Command line:

```bash
cgs scan path/to/code                 # analyse (deterministic, incremental)
cgs callers some_routine --root path/to/code
cgs callees some_routine --root path/to/code
cgs path a b --root path/to/code      # how A reaches B
cgs impact some_routine --root path/to/code
cgs unresolved --ambiguous --root path/to/code
cgs health --root path/to/code
cgs selftest                          # check the installation offline
```

`cgs --help` lists every command; `cgs profile all-subfolders <folder> on` analyses folders skipped by default
(`.gitignore`, `build`, `.venv`, …).

## Develop

```bash
.venv/Scripts/python tools/check.py   # ruff, mypy (strict), import contracts, tests
```

Read [`AGENTS.md`](AGENTS.md) (coding rules) and [`docs/architecture.md`](docs/architecture.md) (architecture,
contracts, decisions) before changing the code. Each analysed codebase is described as a test case in
`docs/packs/<code>.md`.

## Status and limits

- Checked on the fixture mini-codebases (exact expected graphs) and on a Code_Aster 17.5.7 sample (18,438 source
  files, none failed, 16/16 corpus expectations): see `docs/validation/code_aster_start.md`.
- The precision and recall of the call graph on real code have **not been measured yet**: the manual review sheets of
  `tests/corpus/code_aster_start/review/` are still to be filled. The unresolved rate on Code_Aster (8.53 % of call
  sites) is above the 2 % target; `cgs health` splits non-resolved references by category.
- Performance figures are measurements on one development machine (`docs/bench/scan_benchmark.md`), not guarantees.
- AI features are tested with the mock model only.
- The offline behaviour of the packaged application without network has not been tested yet (Lot 16).

## License

One product, two licensing paths (same software, same features): the community path under the
[PolyForm Noncommercial License 1.0.0](LICENSE) for the uses it permits, and a separate
[commercial license](COMMERCIAL_LICENSE.md) for commercial use. See [`LICENSING.md`](LICENSING.md) (plain-language
explanation and examples), [`NOTICE`](NOTICE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). There is no
license key, no activation and no license telemetry. Contributions: [`CONTRIBUTING.md`](CONTRIBUTING.md).
