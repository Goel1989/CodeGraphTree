# Phase 4: rule format and workflow

Scope: Phase 4 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Publish the rule
format and workflow"; requirements 10–11, 17–18). Base: Phase 3 working tree on `phase1/engine-reliability`.
Decision: D30 in `docs/architecture.md`. Guide: `docs/rules/README.md`.

## Findings on the base

| Area | Before | After |
| --- | --- | --- |
| Documentation | Formats described inside the architecture (§3.8, §3.9) only | A user guide with the layout, workflow, a complete tutorial and the extraction semantics |
| Templates | None | `cgs rules new language|bridge|project` writes a template with one passing test case |
| Validation | Errors only when an analysis loaded the file | `cgs rules validate`: syntax, schema, pattern limits, declared test files, before any analysis |
| Tests | Fixtures inside the source repository only | Each rule declares its own test cases; `cgs rules test` reports every missing and unexpected fact |
| Activation | By hand (status keys) or AI approval | `cgs rules activate`: validation, at least one test, all passing, unambiguous selection, then approval |
| Bridge rule files | AI rule files were never schema-validated | Bridge format 1 is validated (wrapper and rule schemas, patterns) |
| Pattern safety | Patterns only had to compile | Length, backreferences and nested quantifiers limited; rule files limited in size; keyword lists bounded |

## Acceptance

`test_a_language_package_is_created_and_tested_from_the_guide_alone` extracts the tutorial files from
`docs/rules/README.md` (blocks marked `<!-- file: ... -->`), writes them, validates, tests and activates the
package, then analyzes the tutorial's repository file and checks the calls the guide announces. The guide's
expected results were written by hand from the documented semantics and passed unchanged.

## Plan requirements → tests (`tests/unit/test_phase4_rule_workflow.py`)

| Requirement | Test |
| --- | --- |
| Documentation alone suffices to create and test a language package | `test_a_language_package_is_created_and_tested_from_the_guide_alone` |
| Documentation covers the required topics | `test_guide_documents_every_required_topic` |
| Templates, examples and validation | `test_language_template_is_valid_tested_and_proposed`, `test_bridge_template_tests_and_activation`, `test_project_pack_template_tests_and_activation` |
| Tests with expected results, clear failures | `test_failing_test_reports_missing_and_unexpected_facts`, `test_bridge_negative_expectation_fails_when_the_edge_exists` |
| Tests must pass before activation | `test_activation_requires_passing_tests_then_approves`, `test_activation_needs_at_least_one_test_and_a_valid_file` |
| No ambiguous activation | `test_activation_refuses_an_ambiguous_selection` |
| Resource limits for configurable patterns | `test_unsafe_patterns_are_rejected`, `test_ordinary_patterns_are_accepted`, `test_existing_packs_respect_the_limits`, `test_pack_with_an_unsafe_pattern_names_file_and_key`, `test_bridge_with_an_unsafe_declaration_pattern_is_invalid`, `test_oversized_rule_files_are_rejected` |
| Commands | `test_cli_rules_commands` |

The built-in packs and the Code_Aster pack satisfy the new pattern limits.

## Not covered by Phase 4

- The AI approval path (`cgs complete` / `set_rule_status`) does not run the new tests yet: that belongs to the AI
  lifecycle (Phase 9).
- Python cannot interrupt a regular expression: the limits remove the known catastrophic constructs, they do not
  bound every possible pattern. Pack patterns run in the analysis process, outside the per-file deadlines.
- Project pack tests check edges only; noise and data-access effects are not compared yet.
