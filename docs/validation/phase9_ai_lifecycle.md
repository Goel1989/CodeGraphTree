# Phase 9: AI lifecycle

Scope: Phase 9 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Correct and extend
the AI lifecycle"; requirements 13–17). Base: Phase 8 working tree on `phase1/engine-reliability`. Decision: D35 in
`docs/architecture.md`. The move of the AI code to a neutral package (`codegraph_sci.ai`) was already done by the
corrective audit.

## Findings on the base

| Finding | Before | After |
| --- | --- | --- |
| Override approval bypass (plan §2.1) | `write_proposals` appended an AI language override to the active `file_overrides` even without automatic approval | Overrides are stored as proposals; only `approve` writes them |
| Validation vs approval | One step: accepted proposals written to the profile (approved or "proposed"), then a rescan | `draft -> validated -> approved` or `rejected`, separate store, explicit approval, explicit rescan |
| Automatic mode | A command-line flag | Requires a project policy configured separately and recorded; each automatic approval recorded |
| Measured recall | Matches of the AI's own keywords reported as `definitions_recall` | Recall and precision measured against expected results written independently; otherwise "not measured" |
| Diagnosis | Unknown extensions and unresolved prefix groups only | Six cases (unknown language, missing package, unsupported dialect, partial coverage, repeated parser failures, unsupported binding) |
| Documents | Missing file, unreadable file or missing PDF support silently dropped | Status, error and SHA-256 recorded and reported; supporting passages and assumptions recorded |

## Lifecycle

| Step | Command | Effect on the analysis |
| --- | --- | --- |
| Generate, validate | `cgs complete <folder> --model … [--document …] [--expected …]` | None: proposals stored as validated or rejected |
| Review | `cgs ai-proposals <folder>` | None |
| Reject | `cgs ai-approve <folder> p-<n> --reject` | None |
| Approve (activate) | `cgs ai-approve <folder> p-<n>` | Override: profile; bridge: `rules/r-<n>.yaml` + profile; language: `rules/languages/<lang>/` through `cgs rules activate` with the independent tests; rule change: replaced file, kept only if it validates |
| Apply | `cgs scan <folder>` | Deterministic, without the AI |
| Automatic | `cgs ai-policy <folder> --auto-approve on`, then `cgs complete --auto` | Approves validated proposals, recorded as `auto-policy` |

## Plan requirements → tests (`tests/unit/test_phase9_ai_lifecycle.py`, `test_lot13_ai.py`)

| Requirement | Test |
| --- | --- |
| Generation and rejection leave the active analysis unchanged | `test_override_generation_and_rejection_leave_the_analysis_unchanged` (profile and canonical graph compared) |
| Explicit approval activates only validated rules; later scans work without the AI | `test_explicit_approval_activates_then_scans_need_no_ai`, `test_bridge_rule_one_click_validation` |
| Automatic approval separately configured and auditable | `test_automatic_approval_needs_a_recorded_policy`, `test_unknown_extension_identified_and_adopted` |
| Independent expected results | `test_language_proposal_needs_independent_expected_results`, `test_language_proposal_failing_independent_results_is_rejected`, `test_language_proposal_approved_against_independent_results`, `test_keyword_profile_proposed_by_ai` |
| Diagnosis of the six cases | `test_diagnosis_distinguishes_the_six_cases` |
| Document references, passages, assumptions; read failures reported | `test_language_proposal_needs_independent_expected_results`, `test_documents_that_cannot_be_read_are_reported` |
| One lifecycle for rule modifications | `test_rule_change_proposals_follow_the_same_lifecycle` |

## Not covered by Phase 9

- The model never produced the assumptions itself: they are derived deterministically (proposed keywords and
  comment markers that the document does not mention).
- Bridge proposals are still validated by replaying the project's own graph (gain, regressions, plausibility,
  stability), not against independent fixtures.
- No real local model was run; every test uses the mock model.
- The desktop window has no proposal review panel yet (command line only).
