# Phase 10: generality, with Code_Aster optional

Scope: Phase 10 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Validate
generality and keep Code_Aster optional"). Base: Phase 9 working tree on `phase1/engine-reliability`. Decision: D36
in `docs/architecture.md`.

## Findings on the base

| Area | Finding | Change |
| --- | --- | --- |
| Separation | No Code_Aster identifier in the core (checked by `test_isolation_no_pack_identifier_in_core` since lot 12) | Kept; a second test checks that no shipped pack *name* appears in the core |
| Activation | Default packs are the two generic ones; packs are loaded only when listed in the profile (detection only suggests) | Tested: a repository matching the Code_Aster detection rules is analyzed without that pack |
| Pack structure | `packs/code_aster/rules.yaml` had no validation of its own (only the real corpus, outside CI) | Same structure as any project pack (Phase 4): a `validation` repository written for the pack (fictional miniature following its conventions), run by `cgs rules test packs/code_aster/rules.yaml` |
| Packaging | The assessment found pack resources missing from the wheel | Domain packs are data outside the core package (D24), so they are not in the wheel by design; `tools/check_wheel.py` builds the wheel offline, checks that every data file of `codegraph_sci` is in it, and runs a smoke test from an unpacked wheel outside the checkout |
| Matrix | No Python library without `main` among the fixtures | `python_library` fixture (package with a re-exporting `__init__`, classes, inheritance, methods, an ambiguous method call) |

## Validation matrix (regular CI, without any shipped pack)

| Corpus | Fixture | Validates |
| --- | --- | --- |
| Python library without main | `python_library` | Imports and re-exports, classes, methods, inheritance, package structure |
| C project | `c_basic` | Headers, declarations, static functions |
| C++ project | `cpp_overloads` | Namespaces, methods, overloads |
| Fortran project | `fortran_arrays_includes` | Modules, procedures, includes |
| Independent mixed-language project | `mini_hybrid` (`expected_graph_bridges.json`) | Cross-language binding evidence (Python, C++, C, Fortran) |
| Custom language / DSL | `keywords_language` (+ the AI tests of Phase 9) | User rules and AI proposals |
| Code_Aster | `tests/corpus/code_aster_start`, `code_aster_full` | Optional large scientific code: `cgs audit corpus` with the revision and configuration recorded (`tools/prepare_corpus.py`, `docs/validation/code_aster_start.md`) |

Each row is `test_validation_matrix_without_shipped_packs[...]`: the fixture is analyzed with the installation's
`packs/` folder hidden and compared with its hand-written expected graph.

## Plan requirements → tests (`tests/unit/test_phase10_generality.py`)

| Requirement | Test |
| --- | --- |
| Core tests pass without Code_Aster installed | `test_validation_matrix_without_shipped_packs` (6 corpora), `test_core_works_without_code_aster` |
| No privileged activation path | `test_packs_are_never_activated_by_name_or_detection` |
| A new project needs configuration or extensions, not core exceptions | `test_core_names_no_shipped_pack`, `test_isolation_no_pack_identifier_in_core` |
| Code_Aster pack in the neutral project-pack structure | `test_code_aster_pack_is_validated_like_any_project_pack` |
| Installed artifacts validated outside the checkout | `test_installed_wheel_works_outside_the_checkout` (`tools/check_wheel.py`) |

## Not covered by Phase 10

- The real Code_Aster corpus is not run in regular CI (GPL sources never versioned; minutes of analysis); its run is
  reproducible with `tools/prepare_corpus.py` and `cgs audit corpus`.
- The portable executable (PyInstaller) was not rebuilt; only the wheel was checked.
- The wheel check runs the smoke test with the development environment's dependencies; a clean virtual environment
  would need the dependencies from the network or a local wheelhouse.
