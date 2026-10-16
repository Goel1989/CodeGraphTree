# Changelog

## Lot 0 — Squelette portable
- Structure du dépôt (§3.16), `pyproject.toml`, contrats import-linter (§3.4), `tools/check.py`.
- `cgs --version`, `cgs selftest` (Qt, grammaires tree-sitter, SQLite FTS5, dossier de données, jeux d'instructions CPU, garde réseau).
- Garde réseau (`core/netguard.py`) installée au démarrage de `cgs` et de l'application.
- Fenêtre PySide6 vide avec « À propos ».
- `tools/build_portable.py` + spécification PyInstaller à deux exécutables (mode dossier), conteneur Linux glibc 2.28, intégration continue Linux + Windows.
- Mesure : dossier portable Windows sans IA = 129 Mo.

## Lot 1 — Modèle de données et stockage
- `core/` : vocabulaire du modèle (§3.5), identités (`ids.py`), faits (§3.7) avec JSON canonique compressé, enregistrements du graphe, types du profil d'analyse.
- `store/` : schéma SQLite (§3.6) versionné, écriture groupée dans un fichier temporaire puis remplacement atomique, index en fin, mode WAL en incrémental (une transaction), cache des faits ; refus d'une version de schéma inconnue.
- `cgs export json` : export canonique trié.
- Mesure : 1 000 000 de sites d'appel écrits en 5,4 s (Windows, SSD).

## Lot 2 — Inventaire des langages et profil d'analyse
- `inventory/` : parcours (`.gitignore`, répertoires exclus, liens symboliques en boucle, fichiers illisibles), table des extensions configurable (`extensions.yaml`), binaires, signatures de contenu (`#!`, lignes de mode, mots-clés pondérés), contexte du dépôt (`.h` C/C++, `.inc` Fortran), chemins d'inclusion, variantes (fixe/libre, préprocesseur, Python 2), rapport de couverture.
- `analysis_profile.yaml` : chargement sûr (`yaml.safe_load`) et schéma JSON strict ; version incrémentée seulement si le contenu change.
- `cgs inventory <dossier>` (tableau ou `--json`) ; dossier de projet hors du dépôt (`core/project.py`).
- Fixture `inventory_mixed`.
- Mesure : inventaire de 15 000 fichiers en 13,9 s (Windows).

## Lot 3 — Mini-codes de référence
- 15 fixtures (Fortran x8, Python, C, C++ x2, mini_hybrid, partial_scope, robustness) avec `src/`, `expected_inventory.json` et `expected_graph.json` écrits à la main ; schémas JSON des fichiers attendus.
- Générateur de dépôt synthétique multi-langages déterministe (`tests/synthetic/generate.py`).
- Inventaire : un `.h` inclus uniquement par du Fortran est du Fortran.
- Annexe D de l'architecture : conventions d'extraction précisées.

## Lot 4 — Adaptateur Fortran
- Banc comparatif des parseurs (`tools/bench_fortran.py`, rapport `docs/bench/fortran_parsers.md`) ; décision D18 : analyseur d'instructions logiques du projet.
- `extract/fortran/` : préparation (formats fixe/libre, colonnes 1-72, continuations, `;`, chaînes masquées, branches `#if` conservées avec leurs conditions, `#include`/`INCLUDE` résolus), unités de programme (modules, procédures internes, interfaces génériques, types et procédures liées, variantes `#2`), symboles locaux (arguments, tableaux, `EXTERNAL`, `COMMON`, déclarations des fichiers inclus), règle `nom(...)` du §3.7, fonctions intrinsèques.
- Extracteur à motifs indépendant (repli et double extraction) ; test de fuzzing (hypothesis).
- Les 9 fixtures Fortran donnent exactement les faits attendus.

## Lot 5 — Adaptateurs Python, C et C++
- `extract/python/` : module `ast` (portées locales/englobantes/module/builtins, imports relatifs, décorateurs, héritage, propagation simple `x = Classe()` et `h = getattr(m, "f")`), repli tree-sitter pour Python 2 et fichiers invalides.
- `extract/cfamily.py` (C et C++, tree-sitter) : définitions avec identités du §3.5 (signatures C++ normalisées, `static` qualifiées par fichier, méthodes hors classe), héritage, expansion partielle des macros (fichier et en-têtes inclus), conditions du préprocesseur, types des arguments pour le choix des surcharges, blocs de macros (`PYBIND11_MODULE`) ; extracteur à motifs de repli.
- `extract/preproc.py` : conditions du préprocesseur partagées.
- Les fixtures Python, C, C++ et mini_hybrid donnent exactement les faits attendus ; fuzzing des adaptateurs.

## Lot 6 — Link, Index et commande `cgs scan`
- `algo/` : Tarjan itératif, condensation, taille d'impact par ensembles de bits, parcours en largeur bornés, k plus courts chemins simples ; étape Index (arêtes agrégées, `node_stats`, `file_edges`, `dir_edges`).
- `link/` : tables de symboles par langage (Fortran insensible à la casse, portées hôte/module/USE transitif, interfaces génériques, procédures liées à un type, variantes ; Python avec MRO ; C avec `static` par fichier ; C++ avec héritage, appels virtuels, choix des surcharges par arité et types), externes connus (intrinsèques, libc, MPI, BLAS/LAPACK, HDF5), état `out_of_scope`.
- `scan.py` et `cgs scan` : lecture du profil, inventaire, extraction parallèle avec délai par fichier, fichiers trop volumineux signalés, cache des faits (clé incluant les fichiers inclus), progression JSON, écriture atomique ou incrémentale.
- Les 15 fixtures donnent exactement leur graphe attendu ; deux analyses donnent un export identique.
- Mesures (Windows, 8 cœurs) : dépôt synthétique 15 000 routines / 3 000 fichiers / 121 387 sites analysé en 50 s ; ré-analyse après 50 modifications en 16,5 s ; taille d'impact de 15 000 nœuds en 0,06 s.
