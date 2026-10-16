# Fortran Parser Benchmark

Reference: statement parser facts, matching the hand-written expected graphs (Lot 4 tests). Calls: `CALL` statements only (the only call kind common to all parsers).

| Candidate | Files | Failures | Def. Recall | Def. Precision | CALL Recall | CALL Precision | Time (s) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| statement parser (selected) | 23 | 1 | 100.0% | 100.0% | 100.0% | 100.0% | 0.013 |
| pattern extractor | 23 | 0 | 100.0% | 95.1% | 96.7% | 96.7% | 0.002 |
| tree-sitter-fortran | 23 | 5 | 87.2% | 94.4% | 86.7% | 100.0% | 0.026 |
| fparser | 23 | 4 | 97.4% | 97.4% | 93.3% | 100.0% | 0.313 |
| LFortran | 23 | not evaluated (binary missing) | - | - | - | - | - |
