# Real-World Corpora

Each real-world codebase defines two corpora (architecture §5.4): `<code>_start` (Lot 7) and `<code>_full` (Lot 14).
Source trees are never committed here: `manifest.yaml` specifies their local path and exact revision.

Validating a corpus (Lot 7 checkpoint):

1. Set `source.path` and `source.revision` in `manifest.yaml`.
2. `cgs audit corpus tests/corpus/code_aster_start/manifest.yaml`: runs analysis with the manifest scope and checks expectations.
3. `cgs audit sample <sources> -o precision.yaml` then `cgs audit review precision.yaml` (one keystroke per link).
4. `cgs audit recall-sample <sources> -o recall.yaml` then `cgs audit review recall.yaml`.
5. `cgs audit report <sources> --precision precision.yaml --recall recall.yaml --expectations .../expectations.yaml`.
6. `cgs audit accept precision.yaml .../reference_sample.yaml` (same for recall), then `cgs audit replay` on every subsequent change.
