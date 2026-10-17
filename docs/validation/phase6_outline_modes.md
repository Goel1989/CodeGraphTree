# Phase 6: FULL and OUTLINE extraction

Scope: Phase 6 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Implement FULL and
OUTLINE extraction"; requirements 22–23). Base: Phase 5 working tree on `phase1/engine-reliability`. Decision: D32
in `docs/architecture.md` (D25 introduced the modes).

## Findings on the base

The plan's assessment ("OUTLINE is selected after extraction") was written before the corrective audit. On the
base, the mode was already chosen before scheduling (`mode_of` in `scan.py`), was part of the cache identity, and
an out-of-scope file was stored as definitions and includes only. But only the Fortran parser skipped work: the
Python, C/C++ and keyword adapters extracted every call and the facts were trimmed afterwards.

| Adapter | OUTLINE before | OUTLINE after |
| --- | --- | --- |
| Fortran | Executable statements skipped (except `SELECT CASE`) | Unchanged |
| Python (`ast`) | Full extraction, then trimmed | Expressions, calls, decorators and base classes not analyzed; module context (imports, instances) kept |
| Python (tree-sitter fallback) | Full extraction, then trimmed | Calls not extracted |
| C / C++ (tree-sitter) | Full extraction, then trimmed | Call expressions inside bodies not analyzed; local declarations still visited (local classes kept) |
| C / C++ (pattern fallback) | Full extraction, then trimmed | Calls in bodies not searched |
| Keyword languages | Full extraction, then trimmed | No call rule applied |

Cached facts are identical to before (the trimmed result was already definitions and includes), so no adapter
version changed and existing caches stay valid.

## Measurement

`ExtractContext(outline=…)` on the synthetic code base (`tests/synthetic/generate.py`, 6,000 routines, 1,200
files, seed 42), best of two runs per mode, same machine:

| Language | Files | FULL | OUTLINE | Ratio |
| --- | --- | --- | --- | --- |
| C | 300 | 0.23 s | 0.17 s | 0.73 |
| C++ | 300 | 0.21 s | 0.15 s | 0.70 |
| Fortran | 300 | 0.29 s | 0.20 s | 0.68 |
| Python | 301 | 0.41 s | 0.31 s | 0.76 |

Synthetic routines have few calls; real code, with denser bodies, gains more. The remaining time is parsing,
which OUTLINE still needs to find definitions.

## Plan requirements → tests

| Requirement | Test |
| --- | --- |
| OUTLINE avoids internal call extraction (every native adapter, every fixture) | `test_outline_adapters_extract_no_call_and_the_same_definitions` (13 language/fixture cases) |
| The call extraction code is not run at all | `test_python_and_c_family_never_run_their_call_extraction_in_outline` |
| Fallback extractors and keyword languages | `test_python_fallback_outline_extracts_no_call`, `test_keyword_adapter_outline` |
| Definitions identical (including local classes) | the tests above, `test_cpp_local_class_inside_a_body_is_kept_in_outline`, `test_outline_keeps_exactly_the_definitions` (Fortran) |
| An in-scope caller resolves to an out-of-scope definition without its internal call graph; moving it into scope forces FULL, and back | `test_in_scope_callers_reach_outline_definitions_then_full_when_moved_into_scope` (Python, C, C++), `test_full_and_outline_files` (Fortran) |
| Mode in the cache identity | the same tests (a mode change re-extracts; an unchanged scan reuses both kinds) |

## Not covered by Phase 6

- Installed native backends (Phase 3 entry points) must honour `ExtractContext.outline` themselves; the facts are
  still trimmed after extraction, so the stored result is correct either way.
- C++ inheritance declared in out-of-scope files is not extracted in OUTLINE, as before; it only matters for virtual
  calls on out-of-scope classes.
