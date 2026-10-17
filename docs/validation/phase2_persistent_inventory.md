# Phase 2: persistent inventory

Scope: Phase 2 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Complete persistent
inventory"; requirements 1–3, 22, 26). Base: branch `phase1/engine-reliability` (`6928b95`). Decision: D28 in
`docs/architecture.md`.

## Findings on the base

| Area | Before | After |
| --- | --- | --- |
| Persistence | The database stored only source files (`files`, `inventory`); skipped folders and non-code files lived in the scan statistics (non-code list capped at 5,000) | `inventory_entries` stores every discovered entry; `inventory_issues` stores discovery problems |
| Directories | Not recorded; empty directories invisible | Recorded with parent, walked or not, and the files below them |
| Unreadable files | Logged as a problem, then dropped from the inventory | Recorded as `unreadable`, with an issue |
| Broken links, special files | Broken links logged; special files silently skipped | Both recorded; broken links also as issues |
| Version-control metadata | Neither walked nor reported | Recorded as excluded (`version-control metadata`), never walked nor counted |
| Links outside the root | Followed silently | Still followed (no change to the analysis), recorded with their target and flagged as `external_link` |
| Excluded content | Only the excluded folder and its file count | Same by default; the `complete` policy records the content without reading it |
| Unknown files in `GraphQuery.inventory()` | Always empty (read from a table that holds only analyzed files) | Grouped by extension from the persistent inventory |

## Record

| Field | Meaning |
| --- | --- |
| `path`, `parent` | Relative path (`/`), `.` for the root; parent directory (none for the root) |
| `kind` | `file`, `directory`, `symlink` (broken link, not followed), `special` |
| `extension`, `size`, `files` | Extension as written; size in bytes (files); files below (directories, including counted content of folders not walked) |
| `lang`, `variant`, `confidence`, `evidence` | Detected language and how it was decided (`extension:.f90`, `shebang:python3`, `context:included_by_cpp`, …); excluded files use the extension only |
| `eligibility` | `eligible`, `excluded`, `not_source`, `unsupported_language`, `unreadable`, `not_applicable` (walked directory) |
| `status` | Files: `pending` (inventory only), then `ok`, `fallback`, `failed`, `timeout`, `outline`, `not_analyzed`; directories: `walked`, `not_walked` |
| `reason` | Why the entry is not (fully) analyzed: `default exclusion`, `.gitignore`, `profile`, `version-control metadata`, `symbolic link loop`, `ignored extension`, `ignored file name`, `ignored by the profile`, `binary content`, `unknown language`, `language not covered`, `unreadable`, `broken symbolic link`, `not a regular file`, `outside the analysis scope`, `extraction failed`, `deadline exceeded`, `no adapter for the language` |
| `link_target` | Target of a symbolic link, as written in the link |

## Policies

- **analysis** (default): exclusions respected; an excluded folder is one entry with its file count.
- **complete** (`inventory_policy: complete`, `cgs profile inventory-policy <folder> complete`): excluded folders
  are walked and their content recorded as `excluded`, never read nor parsed. The analysis selection and the
  skipped-folder report are identical under both policies. Version-control metadata is never walked.

The key is written to the profile only when it is not the default, so existing profiles keep their hash.

## Plan requirements → tests (`tests/unit/test_phase2_inventory.py`)

| Requirement | Test |
| --- | --- |
| Every discovered entry is accounted for, with the reason it was not analyzed | `test_every_discovered_entry_is_accounted_for` |
| Deterministic, sorted records | `test_items_are_sorted_and_deterministic` |
| Complete policy records excluded content without analyzing it | `test_complete_policy_records_excluded_content_without_analyzing_it` |
| `all_subfolders` makes excluded content eligible | `test_all_subfolders_makes_excluded_content_eligible` |
| Unreadable directories and files | `test_unreadable_directories_and_files_are_recorded` |
| Symbolic links: loop, outside the root, broken, alias | `test_symbolic_links` (skipped where links cannot be created, e.g. Windows without the privilege) |
| Profile policy, unchanged hash, CLI | `test_profile_inventory_policy_round_trip_and_unchanged_hash` |
| `cgs inventory --json --entries` accounting | `test_cli_inventory_json_accounts_for_entries` |
| Persistence, queries (filters, paging), export | `test_scan_persists_the_inventory_and_queries_it` |
| Analysis statuses (outline) with the complete policy | `test_scan_statuses_outline_and_complete_policy` |
| Schema-1 database rebuilt, facts cache reused | `test_database_of_the_previous_schema_is_rebuilt_and_keeps_its_cache` |

## Not covered by Phase 2

- The desktop Inventory view does not show the new records yet (UI work is outside this phase).
- The symbolic-link test did not run on the Windows development machine (no privilege to create links); its
  behaviour is covered by code review only there.
- `cgs audit corpus` still computes its unknown-file rate from the `inventory` table, unchanged on purpose, so
  existing corpus expectations keep their meaning.
