# Migration Report — Corrective Audit (October 2026)

Implementation of the corrective audit `codegraphtree_corrective_audit_claudecode_EN.md` (October 17, 2026) on branch
`migration/single-product`, created from `master` at `a90c32e`. Work was done phase by phase, each phase approved by the
owner before the next one, in small thematic commits; `tools/check.py` (ruff, mypy strict, import-linter, pytest)
passed at the end of every phase.

## Summary

| Phase | Result | Commits |
| :--- | :--- | :--- |
| 0 — Baseline | Assessment `docs/repository_migration_assessment.md`: no secret, no analysed source in history, single-author provenance (to confirm), recommendation **KEEP_HISTORY** | `d626758` |
| 1 — One product | `codegraph_sci_pro` removed: AI in `codegraph_sci.ai` + `cli_ai.py`, `code_aster` pack in `packs/`; no feature gate existed; English-only content with an automated check; decision D24 | `4ba96c1`, `cf9af8a`, `952f41b`, `8509606` |
| 2 — Licensing | `LICENSE` (exact PolyForm Noncommercial 1.0.0 text), `NOTICE`, `LICENSING.md`, `COMMERCIAL_LICENSE.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md` (audit of every redistributed component), strict-rule draft for legal review, strategy v2.0 without tiers or license keys | `3a55135`, `e52d6f0`, `67e583c` |
| 3 — Engine reliability | Corpus audit PASS/FAIL/SKIP with exit codes 0/1/2/3 and an authoritative manifest; per-file deadlines in worker processes; real FULL/OUTLINE extraction; fix of a corrupted END SELECT regex; decision D25 | `b2a2e8e`, `f498e42`, `e98007e`, `8b75c60`, `b09500e` |
| 4 — Reproducibility and performance | Dependency locks; phase instrumentation and `cgs benchmark`; reference categories; corpus preparation script; benchmark and Code_Aster validation reports; decision D26 | `ffc2ff4`, `ba37af0`, `5f4cdef`, `824069c`, `52a3564`, `68c6896` |
| 5 — Final consistency | Precise offline wording, measured-only claims, repository tree and planned items, this report | `7e2bd68`, `6eeae8e`, this commit |

Before the migration, three batches requested earlier were committed on `master` (`62a8324` all subfolders,
`353714a` whole-project 3D view, `a90c32e` external review fixes) so that the migration started from a clean base.

## Main changes

**Product and packaging.** One package (`codegraph_sci`), one feature set; the wheel contains only that package and its
`LICENSE` and `NOTICE`. The `pro` entry point is gone; `cgs ai-worker`, `complete` and `ai-approve` are registered by
`cgs` itself. Domain packs are data in `packs/`, outside the core (rule 7), copied into the portable folder. Import
contract: the analysis (`scan`, `audit`, `corpus_audit`, `benchmark`) never imports the AI.

**Licensing.** Dual licensing is a legal distinction only: no license key, no activation, no telemetry. Commercial
contact and the CLA are explicitly "to be defined"; nothing claims legal certainty.

**Engine.**
- Extraction always runs in worker processes with a deadline per file; a stuck file is stored as `timeout` and never
  fails healthy files (it used to run without any deadline for small analyses or `jobs=1`, and the pool failed every
  running file when no future completed in the interval). Cost: about 0.6 s of worker start-up per analysis.
- Files outside the scope are extracted in OUTLINE mode (definitions and includes); the mode is part of the facts and
  of the cache key. Code_Aster: identical definitions on 3,000 sampled Fortran files, 39% less parsing time for them.
- Workers now honour `keep_all_branches` (part of the cache key, ignored by the parallel path before).
- A backspace character had replaced `\b` in the Fortran END SELECT pattern since lot 12: nested SELECT CASE values
  could be attributed to the wrong selector. Fixed (Fortran adapter 1.6), with a test against control characters.

**Validation and measurement.** `cgs audit corpus` can no longer succeed when required validation did not run; its
profile comes from the manifest only, the source revision is verified and the report carries hashes and versions.
`cgs benchmark` measures every phase; `cgs health` splits non-resolved references into six categories (unverified
externals are `unknown`, never known).

## Tests

| Moment | Tests |
| :--- | :--- |
| Baseline (phase 0) | 206 passed |
| End of phase 1 | 209 passed |
| End of phase 2 | 209 passed |
| End of phase 3 | 233 passed |
| End of phase 4 | 240 passed |

New test files: `test_english_only`, `test_corpus_audit`, `test_extract_timeouts`, `test_outline_extraction`,
`test_source_hygiene`, `test_dependency_lock`, `test_benchmark`, `test_prepare_corpus`; additions to `test_lot12_packs`
(pack location), `test_review_fixes` (nested SELECT CASE, reference categories).

Code_Aster 17.5.7 sample after phase 3 and phase 4: audit exit code 0, 16 PASS / 0 FAIL / 0 SKIP, revision verified;
call graph identical before and after the engine changes (47,161 call edges, same sites per resolution).

## Definition of Done (audit §15)

| Criterion | Status |
| :--- | :--- |
| One product package exists, with all functionality | Done |
| `codegraph_sci_pro` gone without functional regression | Done (same commands and tests) |
| Dual licensing documented unambiguously | Done, with legal review pending (below) |
| No license mechanism unlocks functionality | Done (none exists) |
| Project-owned content in English | Done, checked by `test_english_only` (exception: the owner's original root documents, below) |
| French owner instructions do not produce French content | Done (rule 15, CONTRIBUTING) |
| Corpus audit cannot succeed when required validation did not run | Done |
| Manifest produces a reproducible audit context | Done |
| FULL and OUTLINE genuinely distinct and tested | Done |
| Timeouts per task and tested | Done |
| Release dependencies reproducible | Partly: exact pins and CI from the locks; **hashes** to be added at release time (network needed) |
| Code_Aster metrics with provenance and error categories | Done (`docs/validation/code_aster_start.md`); precision/recall not measured |
| Packaged offline behaviour tested | **Not done** (Lot 16: network-less machines, child processes) |
| CI passes | Not verified here: CI now installs from the locks; to be confirmed on the first push |
| Architecture documentation matches the implementation | Done for the changed areas (tree, contracts, D24–D26, measured column) |
| Migration report | This document |

## Remaining risks

- **Precision unknown.** The 750 precision and 600 recall review entries of `tests/corpus/code_aster_start/review/`
  are unfilled: no precision figure may be published. Lot 7 is therefore not fully validated, although later lots were
  built on it.
- **Unresolved rate** 8.53% of call sites on Code_Aster (target 2%), mainly Python dynamic commands, modules outside
  the standard library and C++ member calls whose receiver type is not inferred.
- **Performance** is measured on one 8-CPU development machine only, not on the 4-core reference machine; incremental
  rescans are dominated by the full rebuild after extraction.
- **Worker start-up** adds about 0.6 s to every analysis (the price of per-file deadlines).
- **OUTLINE** skips work only in the Fortran parser; other adapters still parse fully and reduce their output.
- **Offline**: the socket guard is Python-level, not an operating-system sandbox; the packaged application has not
  been tested on a machine without network.
- **AI** is tested with the mock model only; `models.lock` does not exist yet (Lot 15).
- **Public history** still contains the former `codegraph_sci_pro` code, Pro strategy and the review sheets.

## Legal-review items

From `LICENSING.md`, `docs/licensing_strategy.md` §4 and `docs/legal/community_license_strict_DRAFT.md`: exact
copyright holder; definitions of business, commercial use, for-profit entity and affiliate; freelancers, non-profits,
company-funded laboratories, consultants, internal enterprise use, evaluation; redistribution and modifications;
patents; CLA or DCO; third-party compatibility (LGPL Qt/PySide6 obligations and source offer, Chromium notices,
PyInstaller bootloader exception, runtime hooks); local AI model licenses; governing law; warranty and liability;
support terms; the Code_Aster (GPL-3.0) excerpts quoted by the review sheets.

## Decisions pending with the owner

1. The original root documents `architecture_codegraph_sci_v7.md`, `pack_code_aster.md` and `strategie_licence.md`
   duplicate `docs/` and still describe the Free/Pro split and license keys: keep, move to an archive folder with a
   "superseded" note, or delete (rule 16: not changed without the owner's decision).
2. The audit instructions `codegraphtree_corrective_audit_claudecode_EN.md` (untracked at the root): commit them under
   `docs/` for traceability, or keep them outside the repository.
3. The review sheets quoting Code_Aster lines: keep them tracked or regenerate them locally only.
4. Commercial contact channel, CLA text, and confirmation that both Git identities are the same author.
5. Merge of `migration/single-product` into `master` and push.
