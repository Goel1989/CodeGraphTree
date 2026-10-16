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

## Lot 7 — Outils de validation sur un code réel (point d'arrêt)
- `audit/` et `cgs audit` : `inventory` (cohérence), `baseline` (référence textuelle indépendante), `diff` (double extraction par langage), `invariants` (doublons, sites non résolus regroupés par motif, routines jamais appelées, échecs), `sample` / `recall-sample` (échantillons stratifiés à graine fixe), `review` (une touche par entrée), `report` (métriques du §2.1 avec bornes de Wilson), `accept` + `replay` (`reference_sample.yaml` rejoué automatiquement), `corpus` (manifeste + attentes).
- Gabarits `tests/corpus/code_aster_start` et `code_aster_full` (à compléter : emplacement et révision des sources).
- **Validation réelle non faite** : elle exige les sources du cas de test n°1 et la vérification manuelle des échantillons.

## Lot 8 — Ponts inter-langages
- Extraction des liaisons : modules pybind11 (`m.def`), extensions de l'API C de Python, noms `BIND(C, NAME=)` des routines et des interfaces Fortran.
- `link/bridges/` : ponts natifs `pybind11`, `python_extension`, `c_cpp`, `fortran_c` (souligné final, majuscules, double souligné g77, `BIND(C)`) ; règles `prefix_calls` (préfixes du plus long au plus court, `name_transform` explicite) et `declaration_patterns` (nœuds `binding`, jamais de site d'appel) ; règles approuvées du profil (`rules/r-<n>.yaml`).
- Arêtes `binds` / `bridges`, nœuds externes devenus inutiles supprimés ; groupe « ponts » dans l'échantillon de précision.
- Fixtures `bridge_pybind11`, `bridge_fortran_c`, `bridge_prefix_negative` et `mini_hybrid` avec ponts : graphes exacts, chaîne Python → C++ → C → Fortran retrouvée, plus aucun site non résolu.

## Lot 9 — API de requêtes et ligne de commande
- `query/` : `GraphQuery` (§3.10) — `inventory`, `find` (recherche floue FTS5 + noms), `resolve`, `node`, `callers` / `callees` (nombre d'appelants distincts, fichiers, sites ligne par ligne, masquage du bruit), `children` (routine, fichier, répertoire ; paginé), `file_links`, `call_sites`, `paths` (k chemins simples bornés, étapes d'aiguillage « possibles »), `impact` (appelants transitifs bornés, points d'entrée), `data_accesses`, `unresolved` (groupes par motif), `scan_health`, `source` (contrôle de fraîcheur : taille/date puis SHA-256).
- Commandes `cgs callers`, `callees`, `find`, `file-links`, `path`, `impact`, `data`, `unresolved`, `health` (tableau ou `--json`).
- Index ajoutés : `call_site_candidates(dst_node)`, `nodes(display_name)`.
- Mesures sur le dépôt synthétique (15 000 routines) : appelants d'un hub 11 ms, dépliage 2 ms, recherche 7 ms, impact à profondeur 3 en 197 ms.

## Validation Code_Aster (lot 7, en cours) — corrections génériques
- Corpus `code_aster_start` : Code_Aster 17.5.7, téléchargement partiel (bibfor, bibcxx, bibc, code_aster ; 18 446 fichiers) dans `corpus_src/` (non versionné) ; manifeste adapté (contact v17 : `cont_*`).
- Inventaire : chemin d'inclusion déduit du texte inclus (`#include "asterfort/x.h"` → `bibfor/include`).
- Fortran : développement des macros du préprocesseur (fichier et en-têtes inclus, récursivement) dans chaque instruction, position de la macro conservée : types définis par macro, macros-fonctions, macros-instructions.
- Python : limite de récursion relevée pendant l'extraction ; imports étoilés, réexportations et instances appelables suivis par Link.
- C/C++ : API C de Python et espaces `py::`, `pybind11::`, `boost::`, `Eigen::` externes ; pointeurs intelligents (`shared_ptr<X>`, `XxxPtr`) ; repli par nom de méthode quand la classe n'est pas trouvée.

## Lot 10 — Application de bureau (premier jet)
- Fenêtre principale (§3.11) : inventaire (forcer un langage, ignorer une extension → `cgs profile`), recherche, panneau Appelants / Appelés avec sites, inspecteur de code coloré (sites surlignés, double-clic → routine appelée, bandeau « fichier modifié » + Ré-analyser), explorateur de fichiers, liste arborescente paresseuse (pages de 50, « +N autres », « ↺ déjà vu »), santé de l'analyse, filtres (utilitaires, confiance, liens IA, ambigus).
- Requêtes dans le pool de threads Qt ; inventaire, analyse et profil en sous-processus `cgs` avec progression JSON et annulation.
- Tests pytest-qt : scénarios S1, S2, S10 et modèles.

## Lot 12 — Packs, profils de langage par mots-clés, filtrage du bruit
- `enrich/` : schéma strict des packs (§3.8) et chargement sûr ; packs intégrés `generic_noise` (hubs) et `generic_fortran` (COMMON, variables de module) ; moteur de règles : `memory_access` (clés littérales, locales, symboliques et familles, propagation simple des affectations de chaînes), `dispatch` (`SELECT CASE`), `catalogs`, `entry_points` (cible de repli), `tests` ; `noise.hide` / `optional` / `auto_detect_hubs`.
- `extract/keywords/` : adaptateur par mots-clés (§3.9) et schéma des profils ; fixture `keywords_language` (profil écrit à la main, couverture mesurée 100 %).
- Fortran : accès aux données (lecture/écriture), branches `SELECT CASE`, interfaces imbriquées dans un corps d'interface.
- Fixtures `pack_acme` et `fortran_data` (avec pack) exactes ; test d'isolation du cœur (§6.4).
- Code_Aster 17.5.7 (corpus de démarrage) : 0 échec, rappel des définitions 99,6 %, rappel des `CALL` Fortran 100 %, non-résolus 9,2 % (idiomes Python/C++ relevant du pack).

## Validation Code_Aster — suite
- C/C++ : vrai développement des macros du préprocesseur (`extract/cmacro.py` : paramètres, `#`, `##`, `__VA_ARGS__`, première définition gagnante) ; fonctions déclarées par macro nommées d'après leur développement (`DEFS(X, x, …)` → `x_`). Effet sur Code_Aster : 720 appels C/C++ → Fortran reliés par le pont `fortran_c` (macros `CALL_*`/`CALLO_*`).
- Link : au-delà de 8 candidats, un site ambigu ne garde aucun candidat (fin des faux hubs `get`).
- Mesures (corpus de démarrage 17.5.7, packs génériques) : 0 échec, rappel des définitions 99,2 %, rappel des `CALL` Fortran 100 %, non-résolus 8,5 % ; ré-analyse incrémentale ~50 s. Hubs détectés : `assert`, `utmess`, `jeveuo`, `jemarq`, `jedema`… Fiches de vérification régénérées (`tests/corpus/code_aster_start/review/`).
