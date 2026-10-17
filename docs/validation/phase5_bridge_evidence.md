# Phase 5: bridges and evidence

Scope: Phase 5 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Generalize bridges
and evidence"; requirements 5, 12, 19, 24). Base: Phase 4 working tree on `phase1/engine-reliability`. Decision:
D31 in `docs/architecture.md`.

## Findings on the base

| Area | Before | After |
| --- | --- | --- |
| Bridge declaration | Native bridges described only in a module docstring | `core/bridge_catalog.py`: languages, mechanisms, evidence kind, matching, transformation, constraints, candidate policy, identifier, version |
| Homonyms | A C++ target of a rule bridge (and of a declaration binding) was the first of the sorted homonyms | Every homonym kept as an ambiguous candidate (`candidates: keep_ambiguous`, default), or no link (`unique`) |
| Name similarity | A prefix rule linked any transformed name that existed | `require_declaration` links only names declared by the rule's declaration patterns; `files` and `target_files` constrain callers and targets |
| Evidence | Only `origin` (`bridge:fortran_c`, …) | Each bridge site stores rule, version, mechanism, evidence kind, binding declaration, transformed name, candidate selection and reason (`call_sites.evidence`, schema 3) |
| Traceability | Extraction rule and resolution reason not exposed | `CallSite.evidence` adds the extraction rule (adapter and version), the resolution rule and a reason for every site; `cgs callees` prints the mechanism and declaration; `GraphQuery.bridges()` |

## Mechanisms exposed by the independent fixtures

| Fixture | Site | Mechanism | Evidence kind | Binding |
| --- | --- | --- | --- | --- |
| `bridge_fortran_c` | `fort_exported` (C → Fortran) | `bind_c_name` | binding declaration | `f:exported` |
| | `compute_` | `trailing_underscore` | naming convention | — |
| | `COMPUTE2` | `uppercase_name` | naming convention | — |
| | `legacy_double__` | `g77_double_underscore` | naming convention | — |
| | `c_callback` (Fortran → C) | `trailing_underscore` | naming convention | — |
| | `c_named` (Fortran → C) | `bind_c_name` | binding declaration | `BIND(C, NAME="c_named_impl") in f:compute` |
| `bridge_pybind11` | Python calls | `pybind11_def` / `pybind11_module` | binding declaration | `bind:pybind11:…` |
| new (test) | `CPP_SOLVE` toward two C++ overloads | `prefix_call` | rule | ambiguous, both candidates |
| new (test) | `CALL_SOLVE` with `DECLARE_F(solve)` | `declaration_macro` | binding declaration | `bind:decl:solve@main.c` |

No mechanism was added; the existing fixtures (`bridge_fortran_c`, `bridge_pybind11`, `bridge_prefix_negative`,
`mini_hybrid`) keep their expected graphs.

## Plan requirements → tests (`tests/unit/test_phase5_bridge_evidence.py`)

| Requirement | Test |
| --- | --- |
| Each bridge declares languages, mechanism, matching, transformation, constraints, candidate policy, evidence, identifier and version | `test_catalog_declares_every_native_bridge`, `test_new_bridge_keys_are_validated`, `test_bridge_rules_are_recorded_with_their_version` |
| Fixtures resolve through documented mechanisms and expose their evidence | `test_fortran_c_links_expose_their_mechanism`, `test_python_binding_links_name_their_declaration` |
| Not solely from similar names | `test_rule_requiring_a_declaration_links_only_declared_names`, `test_rule_file_and_target_constraints` |
| Ambiguous candidates preserved | `test_rule_keeps_ambiguous_candidates_instead_of_picking_one` |
| Extraction rule, resolution rule, binding declaration, candidate selection and reason persisted and exposed | `test_query_exposes_extraction_and_resolution_evidence`, `test_native_resolutions_get_a_derived_reason`, `test_cli_callees_shows_the_mechanism` |
| Determinism | `test_evidence_is_deterministic` |

## Decisions left to the owner

- **Naming-convention bridges.** `fortran_c` (name decoration) and `c_cpp` (same name with C linkage) still link
  on a documented convention when exactly one target exists; they do not require a declaration. Requiring one (for
  example a C prototype or an `extern "C"` block) would change existing graphs, including Code_Aster, without a
  measured effect on precision, so it was not done. The evidence labels these links `naming_convention`, so they
  can be filtered or reviewed.
- **Native homonyms** stay as before (unresolved when several C++ candidates exist for `c_cpp`); only rule bridges
  and declaration bindings keep ambiguous candidates.

## Not covered by Phase 5

- Evidence for native (non-bridge) resolutions is derived from the stored resolution, confidence and candidates,
  not recorded step by step by each language resolver.
- The desktop inspector does not display the evidence yet (UI work).
- The dependency tables of Phase 7 will show the evidence per row.
