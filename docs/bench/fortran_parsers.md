# Banc comparatif des parseurs Fortran

Référence : faits du parseur d'instructions, eux-mêmes égaux aux graphes attendus écrits à la main (tests du lot 4). Appels : instructions `CALL` seulement (le seul type d'appel commun à tous).

| Candidat | Fichiers | Échecs | Rappel déf. | Précision déf. | Rappel CALL | Précision CALL | Temps (s) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| statement parser (retenu) | 23 | 1 | 100.0% | 100.0% | 100.0% | 100.0% | 0.013 |
| pattern extractor | 23 | 0 | 100.0% | 95.1% | 96.7% | 96.7% | 0.002 |
| tree-sitter-fortran | 23 | 5 | 87.2% | 94.4% | 86.7% | 100.0% | 0.026 |
| fparser | 23 | 4 | 97.4% | 97.4% | 93.3% | 100.0% | 0.313 |
| LFortran | 23 | non évalué (binaire absent) | - | - | - | - | - |
