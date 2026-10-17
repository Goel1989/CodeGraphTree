# Code_Aster validation report — `code_aster_start`

Reproducible validation of CodeGraph-Sci on a Code_Aster sample (corrective audit §10). Raw data:
`code_aster_start.json`. Regenerate with:

```bash
python tools/prepare_corpus.py tests/corpus/code_aster_start/manifest.yaml
cgs audit corpus tests/corpus/code_aster_start/manifest.yaml --json
cgs health --root <sources> --json
```

## Provenance

| Item | Value |
| :--- | :--- |
| Code_Aster version | 17.5.7 (tag verified: True) |
| Git commit | `14f751e2721ed772f20151a57f2ce6db050ba487` |
| Sources | sparse checkout of `bibfor/`, `bibcxx/`, `bibc/`, `code_aster/` (never stored in this repository) |
| Manifest | `tests/corpus/code_aster_start/manifest.yaml`, SHA-256 `7bc787eb13a94ded853be5bee59eaad9e5a65eaf14a2c5630848f1f4035448f4` |
| Expectations | `tests/corpus/code_aster_start/expectations.yaml`, SHA-256 `35c5f0aeb98041dcda254826860e7152ec0eae9b7b5e44246bcb33652b2fccfb` |
| Audit profile | SHA-256 `ecdc8d7325095c17f854626e12b988814a5692240b8d64602941298a8166516b` (rebuilt from the manifest) |
| CodeGraph-Sci | 0.1.0; adapters fortran 1.6, python 1.1, c 1.1, cpp 1.1 |
| Packs | generic_fortran 1.0, generic_noise 1.0, code_aster 0.3 |
| Machine | Windows-11-10.0.26200-SP0, 8 logical CPUs, Python 3.12.10 |
| Date | October 17, 2026 |

## Expectations: 16 PASS, 0 FAIL, 0 SKIP (exit code 0)

| Status | Expectation |
| :--- | :--- |
| PASS | `inventory.fortran` |
| PASS | `inventory.python` |
| PASS | `inventory.cpp` |
| PASS | `inventory.c` |
| PASS | `inventory.max_unknown_rate` |
| PASS | `node: f:mmbouc` |
| PASS | `node: f:nmstat` |
| PASS | `hidden: f:utmess` |
| PASS | `hidden: f:jemarq` |
| PASS | `no_call_to: ['f:zr', 'f:zi', 'f:zc', 'f:zl', 'f:zk8', 'f:zk16', 'f:zk24', 'f:zk32', 'f:zk80']` |
| PASS | `writes: {'routine': 'f:nmener', 'data': 'data:mem:*.VALE', 'key_kind': 'family'}` |
| PASS | `edge: {'src': 'cpp:BaseMesh::readMeshFile(const std::filesystem::path&,const std::string&,const int)', 'dst': 'f:execop', 'kind': 'bridges'}` |
| PASS | `path: {'from': 'entry:STAT_NON_LINE', 'to': 'f:op0070', 'max_len': 2, 'edge_kinds': 'call_path'}` |
| PASS | `dispatches: {'src': 'f:te0000', 'min_targets': 500}` |
| PASS | `dispatches: {'src': 'f:lc0000', 'min_targets': 50}` |
| PASS | `out_of_scope_allowed: ['f:op*', 'f:te*', 'f:lc*']` |

## Non-resolved references by category

144,896 reference sites in all (128,533 call-like sites). Every site not resolved to a routine
of the analysis scope is counted once, in the first matching category (`GraphQuery.reference_categories`):

| Category | Sites | Share of all references |
| :--- | ---: | ---: |
| `external_known` | 31,879 | 22.0% |
| `out_of_scope` | 8,094 | 5.6% |
| `ambiguous` | 14,465 | 10.0% |
| `dynamic` | 7,953 | 5.5% |
| `parser_limitation` | 3,411 | 2.4% |
| `unknown` | 12,814 | 8.8% |

The historical single figure — unresolved call sites over call-like sites — is
8.53% (target 2%): it is not met. The categories show where the gap is: `dynamic` (Python
attribute calls and procedure pointers, whose target is known only at run time), `parser_limitation` (mostly C++
member calls whose receiver type is not inferred), `ambiguous`, and `unknown` — on this sample mostly Python:
upper-case command names created at run time (`DEFI_*`, `CREA_*`…, 4,830 sites), calls into modules outside the
standard library (3,764) and imports not found (1,636); then C++ calls not found (1,513).

## Files

fallback: 4, ok: 3,216, outline: 15,218 (outline = outside the analysis scope,
definitions only).

## Not measured yet

- **Precision and recall** of the call graph: the manual review sheets (750 precision entries, 600 recall entries in
  `tests/corpus/code_aster_start/review/`) are not filled. No precision figure may be published before they are.
- The full corpus (`code_aster_full`) has no prepared sources and placeholder expectations.

## Performance

See `docs/bench/scan_benchmark.md`: cold full analysis 87.5 s, rescan after 50 changed files 25.9 s on the machine
above.
