# AGENTS.md — Developer Agent Guidelines

(Copy of Appendix C from `docs/architecture.md`.)

1. Read `docs/architecture.md` (§3 and the requested lot) before coding. Only read a `docs/packs/<code>.md` file when working on that specific pack.
2. Implement **only one lot at a time**; stop when its validation tests pass. Do not start UI lots until Lot 7 is validated.
3. Respect the contracts (§3.5 to §3.10) and package dependencies (§3.4). Any contract change must be recorded in `docs/architecture.md`.
4. Write or update tests **before** writing the code that makes them pass.
5. No network access and no open ports, in both production code and tests.
6. No dependencies outside the list in §3.15.
7. No identifier specific to an analyzed codebase inside `src/codegraph_sci/`.
8. Determinism: sort every collection before writing it; no timestamps in facts; relative paths using `/`; analysis reads only the analysis profile and never calls AI.
9. A file's language comes from the inventory; no adapter guesses it.
10. Every observed call becomes a call site with file, line, column, condition, and origin; never merge two call sites in a way that loses this information.
11. Configuration files: `yaml.safe_load` and schema validation only; never `pickle`.
12. Every analyzed file has a maximum timeout; a failure is logged, never blocking.
13. The UI accesses data only through `GraphQuery`; no long-running query on the main thread.
14. Every AI feature must be testable with the mock model.
15. Typed Python 3.12 (`mypy` strict), formatted with `ruff`; identifiers, code, UI, comments, and documentation in English. English is the only project language even when instructions are given in another language: translate the intent, never copy the wording. Exceptions: analysed source code and fixtures that intentionally represent foreign-language code. Checked by `tests/unit/test_english_only.py`.
16. Every change must be coherent with the existing code, contracts and decisions, and must not degrade it (behaviour, precision, performance, determinism, readability): a fix comes with a non-regression test, and the whole check (`tools/check.py`) passes before and after. **When in doubt** (business or licensing choice, contract change, deletion of user material, effect on precision not measured), change nothing: report the point and the options to the user, and wait for their decision before modifying.

## Environment

- Python 3.12 in `.venv`: `.venv/Scripts/python tools/check.py` (Windows) or `.venv/bin/python tools/check.py`.
- Tree-sitter grammars: individual wheels (`tree-sitter-fortran`, `-python`, `-c`, `-cpp`). Do not use `tree-sitter-language-pack` ≥ 1.0: it downloads grammars at runtime.
