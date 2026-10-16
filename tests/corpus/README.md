# Corpus réels

Chaque code réel donne deux corpus (architecture §5.4) : `<code>_start` (lot 7) et `<code>_full` (lot 14).
Les sources ne sont jamais versionnées ici : `manifest.yaml` indique leur emplacement local et la révision exacte.

Validation d'un corpus (lot 7, point d'arrêt) :

1. Renseigner `source.path` et `source.revision` dans `manifest.yaml`.
2. `cgs audit corpus tests/corpus/code_aster_start/manifest.yaml` : analyse avec le périmètre du manifeste, puis attentes.
3. `cgs audit sample <sources> -o precision.yaml` puis `cgs audit review precision.yaml` (une touche par lien).
4. `cgs audit recall-sample <sources> -o recall.yaml` puis `cgs audit review recall.yaml`.
5. `cgs audit report <sources> --precision precision.yaml --recall recall.yaml --expectations .../expectations.yaml`.
6. `cgs audit accept precision.yaml .../reference_sample.yaml` (idem pour le rappel), puis `cgs audit replay` à chaque évolution.
