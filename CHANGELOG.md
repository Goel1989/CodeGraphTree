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
