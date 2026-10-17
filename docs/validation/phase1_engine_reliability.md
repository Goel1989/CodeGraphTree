# Phase 1: engine reliability

Scope: Phase 1 of `codegraphtree_requirements_assessment_and_implementation_plan_EN.md` (§6, "Correct engine
reliability"). Base checkout: `f6c95d6` (October 17, 2026). The plan's assessment was written on an older revision
(`44659bc`); several of its findings (2D graphs, Pro package, pool-inactivity timeouts, audit exit codes) had already
been fixed by the corrective audit. Later phases are not part of this change. Decision: D27 in
`docs/architecture.md`.

## Findings on the base checkout

| Area | Reproduction | Correction |
| --- | --- | --- |
| File identity | Two identical Python modules changed identities on a cached scan | Relative path in the cache identity; a cached blob must belong to the same file |
| Naming context | Adding a Python package marker reused stale module names | Effective module name in the key |
| Source form | An inventory variant override reused the previous extraction | Inventory variant in the key |
| Include precedence | Profile serialization and extraction parameters sorted the search paths | Order preserved everywhere |
| Include lookup | New, shadowing or formerly missing headers left stale cached facts | Every include lookup recorded (nested and unresolved too) and replayed to validate the cache |
| Reproducibility | Keyword versions and bridge sample partitions depended on Python's hash seed | Canonical SHA-256 digests |
| Deadlines | A busy parent could accept a result completed after its deadline | Workers acknowledge each task; the deadline runs from that acknowledgement; late results are refused |
| Deadline bypass | Zero, negative and non-finite timeouts bypassed enforcement | Finite, positive deadline required by the API and by `cgs scan --timeout` |
| Worker start | A failing worker initializer was respawned forever | The run stops with `WorkerStartError` |
| Cancellation | Cancellation during the write still replaced the valid database | Checked until the last moment before publishing; partial results are discarded |
| Keyword identities | Homonymous routines shared identifiers and lost call ownership | File- and scope-qualified identities; homonym calls become ambiguous |
| Python occurrences | Repeated definitions gave both bodies' calls to the last node | The owner of a call is the occurrence that contains its line |

## Plan requirements → tests

| Plan requirement | Test |
| --- | --- |
| Identical files retain distinct module identities | `test_identical_files_cold_cached_parallel` |
| Cold, cached and parallel scans yield equivalent graphs | `test_identical_files_cold_cached_parallel` |
| Package-marker changes invalidate Python naming context | `test_package_marker_changes_naming_context` |
| Include-search precedence changes invalidate results | `test_include_resolution_changes_invalidate_cache[precedence, shadow, missing, nested]` |
| One blocked extractor does not fail healthy files | `test_extract_timeouts.py` (blocked, slow, simultaneous, crash, late result, initializer) |
| Duplicate names and overloads do not silently merge | `test_keyword_homonyms_preserve_owners_and_ambiguous_targets`, `test_duplicate_python_definitions_keep_their_call_sites`; C/C++ overload and static-homonym fixtures unchanged |
| Cancellation preserves the previous valid database | `test_cancellation_preserves_committed_database[extract, write × incremental, full]` |
| Extraction vs linking dependencies | `test_link_settings_do_not_invalidate_extraction` |
| Stable digests | `test_keyword_version_is_stable_across_hash_seeds`, `test_bridge_partition_is_stable_across_hash_seeds` |
| Incompatible caches invalidated explicitly | `test_incompatible_and_damaged_facts_are_cache_misses` (facts format 2) |
| Deadlines are finite and positive | `test_scan_requires_finite_positive_deadline`, `test_cli_rejects_a_deadline_that_is_not_finite_and_positive` |

**Cancellation policy:** a cancelled scan raises `ScanCancelled`, stops its workers, discards every partial result
and leaves the previously committed database byte-for-byte unchanged. No incomplete run is ever recorded.

## Validation

- Ruff, strict mypy and the six import-linter contracts pass.
- Pytest on the final code: 262 passed, 1 failed in the full run (452 s). The failure is the timing assertion of
  `test_synthetic_full_size` under the load of the full suite (cold scan 61.6 s); its graph assertions pass, and the
  test passes on its own (cold 52.1 s, rescan after 50 changes 16.4 s, limit 30 s). The same test already failed
  under load before the Phase 1 code (cold 104.9 s, rescan 39.9 s, full suite 503 s), so it measures the machine.
- Same-machine comparison, `cgs benchmark` on the synthetic code base (3,000 files, 50 changed), alternating the
  base checkout and the Phase 1 code: rescan after 50 changes 14.3–14.5 s (base) vs 14.2 s (Phase 1); unchanged
  rescan 12.5–13.2 s vs 13.0–13.1 s; cache lookup 1.7–2.3 s vs 2.1–2.4 s. No measurable regression.
- Existing caches are rebuilt once (facts format 2); the database schema is unchanged.

## Not covered by Phase 1

- C/C++ declaration/definition unification and complete language-specific scope resolution for keyword languages:
  identities stay as documented in §3.5; keyword qualification is lexical.
- Other plan phases (inventory persistence, language packages, rule workflow, dependency tables, AI lifecycle, etc.).
