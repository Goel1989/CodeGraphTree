# Phase 3: unified language packages

Scope: Phase 3 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Introduce unified
language packages"; requirements 3–5, 10–11, 18, 20). Base: Phase 2 working tree on `phase1/engine-reliability`.
Decision: D29 in `docs/architecture.md`.

## Findings on the base

| Area | Before | After |
| --- | --- | --- |
| Registration | Hard-coded `native_adapters()` in `scan.py`; keyword profiles loaded only when the profile mapped the language to `keywords:<language>` | `extract/registry.py` selects one package per language from documented levels |
| Contract | Native adapters had no declaration; keyword profiles declared rules only | One package format for both backends: version, extensions, hints, dialects, naming, relationships, resolution capabilities, limitations, tests, provenance |
| Parser extensions | None outside the source tree | `native:<name>` backends installed separately through the `codegraph_sci.language_backends` entry point group |
| Precedence | Native always won; a keyword profile for a native language was silently ignored | builtin < user < project < explicit; replacing requires `overrides: true`; ambiguity is an error |
| Inventory | Keyword extensions came after "known but not covered" (a `.jl` package could never apply) | Package extensions, file names and shebangs are applied; package extensions win over "known but not covered" |
| Workers | Re-read keyword profile files by path | Receive the selected package specifications |

## Contract

Package format 1 (`extract/language_package.schema.json`), loaded with `yaml.safe_load` and validated; errors name
the file, the key and the value. Keyword rules (`rules`) are additionally validated against the keyword-profile
schema of §3.9. Declared test cases must exist next to a non-built-in package (running them belongs to the rule
workflow of Phase 4). The built-in manifests (`extract/languages/`) describe the four native adapters; their
extensions are checked against the inventory table.

## Precedence and ambiguity

| Situation | Result |
| --- | --- |
| Package with `status` other than `approved` | Inactive, listed by `cgs languages` |
| Project package whose language the analysis profile marks `proposed` or `rejected` | Inactive (AI proposals need approval) |
| Two active packages of one level for the same language | Error naming both files |
| Higher-level package for a language already provided, without `overrides: true` | Error naming both files |
| Same, with `overrides: true` | Higher level selected; the other listed as replaced |
| Two languages claiming one extension, file name or shebang | Error naming both files |
| A package claiming an extension decided by content (`.h`, `.inc`, `.fi`, `.fh`) | Error |
| `native:<name>` backend neither built in nor installed (or installed twice) | Error |

## Behaviour changes (please confirm)

- An approved package placed in `<project>/rules/languages/` is active even if the analysis profile has no entry
  for its language; before, the profile had to map the language to `keywords:<language>`. This is what makes a
  language installable without other steps. AI proposals keep needing approval (file status and profile status).
- A package claiming an extension listed as "known but not covered" (`.jl`, `.rs`, `.go`…) now takes it.
- A keyword profile (or package without `overrides: true`) for a built-in language is an error instead of being
  silently ignored.

## Plan requirements → tests (`tests/unit/test_phase3_language_packages.py`)

| Requirement | Test |
| --- | --- |
| A new example language is installed and analyzed without modifying the core | `test_a_new_language_is_installed_and_analyzed_without_changing_the_core` |
| Native parsers packaged behind the contract | `test_builtin_packages_describe_the_native_adapters` |
| Extensions and detection hints (file names, shebangs); user level | `test_user_level_package_covers_a_language_known_but_not_covered` |
| Earlier keyword profiles remain valid, same adapter version | `test_legacy_keyword_profile_is_read_as_a_keyword_package` |
| Precedence between built-in, user and project packages | `test_precedence_and_explicit_override` |
| Ambiguous package selection rejected | `test_ambiguous_or_invalid_selection_is_rejected` (7 cases) |
| Structured, safe configuration with clear errors | `test_invalid_packages_name_the_file_and_key` |
| Approval lifecycle respected | `test_unapproved_packages_stay_inactive` |
| Separate, explicitly installed adapter interface | `test_installed_native_backend_through_the_entry_point_group` |
| `cgs languages` | `test_cli_languages_lists_packages_with_their_level` |

The keyword-language fixture (`tests/fixtures/keywords_language`) and every existing fixture run unchanged
through the registry.

## Not covered by Phase 3

- Running the declared package test cases, templates and the documented rule workflow (Phase 4).
- The entry-point backend test replaces the entry point lookup in the test process; a real separately installed
  distribution was not built.
- Linking keeps its language-specific rules for the four native languages; the linking of references produced by
  an installed native backend was not validated (the test stops at extraction).
