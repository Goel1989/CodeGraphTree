# Cas de test n°1 — Code_Aster (Domain Pack `code_aster`)

**Emplacement dans le dépôt :** `docs/packs/code_aster.md`  
**Pack :** `code_aster` (extension Pro, `src/codegraph_sci_pro/packs/code_aster/`)  
**Version du document :** 0.2 (16 octobre 2026) — intègre deux revues externes  
**Version de référence du code :** *(à fixer : v16, v17 ou les deux)*  
**Statut :** brouillon. Les points marqués *(à valider)* doivent être vérifiés sur la version de référence ; ceux marqués *(revue externe)* viennent d'une revue et n'ont pas encore été vérifiés dans le code.

> **Ce fichier est spécifique.** Il ne sert qu'à travailler sur le pack `code_aster` et sur ses corpus. Rien de ce qui suit ne doit apparaître dans le cœur (`src/codegraph_sci/`) : la règle d'isolation de `docs/architecture.md` (§6.4) s'applique. Si une règle ne peut pas s'exprimer dans le format de pack générique (`docs/architecture.md`, §3.8), on étend ce format **de façon générique**, jamais le cœur pour ce seul code.

---

## 1. Pourquoi ce cas de test

Code_Aster est un solveur éléments finis open source (sous GPL) qui réunit, dans un seul dépôt, toutes les difficultés visées par CodeGraph-Sci :

- les quatre langages de la première version (Python, C++, C, Fortran) et leurs ponts ;
- une taille réaliste (de l'ordre de 15 000 fichiers et subroutines) ;
- un gestionnaire mémoire maison (JEVEUX) dont les objets sont nommés à l'exécution, et des tableaux globaux (`zr`, `zi`…) dont l'accès ressemble à un appel de fonction ;
- des aiguillages par numéro et par catalogues (routines élémentaires, lois de comportement) ;
- des routines utilitaires omniprésentes qui rendent les graphes bruts illisibles ;
- une large base de cas-tests reliés aux commandes utilisateur.

---

## 2. Couches du code et extensions sollicitées

| Couche | Répertoire | Langage | Extensions CodeGraph-Sci sollicitées |
| :--- | :--- | :--- | :--- |
| Commandes et orchestration | `code_aster/` | Python | Adaptateur Python ; capacité `entry_points` (catalogues de commandes) |
| Liaisons | `bibcxx/` | C++ | Adaptateur C++ ; ponts `pybind11`, `python_extension`, `prefix_calls` |
| Couche C | `bibc/` | C | Adaptateur C ; pont `fortran_c` ; `external_symbols` (MED, HDF5, MPI) |
| Calcul | `bibfor/` | Fortran 90 préprocessé (`.F90`) | Adaptateur Fortran (symboles locaux, fichiers inclus) ; capacités `noise`, `extraction`, `memory_access`, `dispatch` |
| Catalogues | `catalo/` (Python déclaratif) ou `.cata` selon la version | Python / texte | Capacité `catalogs`, probablement `enrich.py` |
| Cas-tests | `astest/` | Fichiers de commandes `.comm` | Capacité `tests` |

---

## 3. Règles du pack

### 3.1. Routines utilitaires (bruit)

- **Masquées par défaut :** `jemarq`, `jedema`, `utmess`, `assert` (macro `ASSERT`), `infniv`.
- **Proposées au masquage :** `jeexin`, `jelira`, `dismoi`, `getv*`, et `rcvalb` / `rcvala` (lecture des propriétés matériaux, très appelées) *(revue externe, à valider)*.
- `jeveuo`, `wkvect`, `jecreo`, `jedetr` ne sont pas simplement masquées : elles sont **converties en accès aux données** (§3.3).
- La détection automatique des hubs (`generic_noise`) doit retrouver l'essentiel de cette liste : c'est un test du pack générique.

### 3.2. Tableaux globaux JEVEUX : `zi`, `zr`, `zc`, `zl`, `zk8`, `zk16`, `zk24`, `zk32`, `zk80`

- L'accès historique aux objets JEVEUX passe par ces tableaux : `zr(iad + k)`. Syntaxiquement, cela ressemble à un appel de fonction.
- Ils sont déclarés dans un fichier inclus (`#include "jeveux.h"`), sous forme de blocs `COMMON` *(à valider)*. La règle générique de l'architecture (§3.7 : tableau déclaré dans un fichier inclus ou un `COMMON` → accès à une donnée) les traite donc correctement, **à condition que `jeveux.h` soit trouvé** par les chemins d'inclusion du profil.
- Filet de sécurité si la déclaration est introuvable : `extraction.known_arrays` du pack (§4).
- **Pourquoi pas simplement les masquer comme du bruit :** le masquage cache des nœuds, mais les faux appels resteraient dans le graphe et fausseraient comptages, impact et chemins. Il faut qu'aucun site d'appel ne soit créé.
- Attente vérifiable : aucun site d'appel vers `f:zr`, `f:zi`… (§5).

### 3.3. Gestionnaire mémoire JEVEUX : objets à trois niveaux de précision

- **Accès :** `call jeveuo(nom, mode, ...)` avec `mode = 'L'` (lecture) ou `'E'` (écriture).
  - Forme historique : `call jeveuo(nom, 'L', iad)` puis accès via `zr(iad)`, `zi(iad)`…
  - Forme moderne : `call jeveuo(nom, 'E', vr=ptr)` avec des pointeurs Fortran (`vr=`, `vi=`, `vk8=`…).
- **Création / destruction :** `wkvect`, `jecreo`, `jecrec` → `creates` ; `jedetr` → `destroys`.
- **Noms d'objets :** ne garder que le suffixe (`.VALE`) regrouperait tous les champs de tout le code dans un seul nœud, devenu un hub inutilisable. On applique donc les trois niveaux de l'architecture (§3.5), dans cet ordre :

| Niveau | Exemple | Traitement |
| :--- | :--- | :--- |
| `literal` | Nom de travail entièrement écrit dans le code, de la forme `'&&OP0070.XXXX'` *(forme à valider)* | Objet précis ; le préfixe `&&` indique un objet de travail propre à la routine (`local_prefix_pattern: "^&&"`) |
| `symbolic` | `nomsd(1:19)//'.VALE'` | Expression conservée, propre à la routine |
| `family` | `*.VALE`, `*.DESC`, `*.REFE`… | Famille d'objets, toujours renseignée en plus ; traitée comme un hub, masquée par défaut dans les TreeGraph |

- Les variables intermédiaires (`vale = cham//'.VALE'` puis `jeveuo(vale, ...)`) sont suivies par la propagation simple des valeurs locales prévue dans les faits génériques.
- **Hors champ en première version :** relier un objet `symbolic` d'une routine à celui de ses appelants à travers les arguments (analyse de flux interprocédurale).

### 3.4. Aiguillages et catalogues

- **Routines élémentaires :** l'exécution des options de calcul passe par `calcul`, qui boucle sur les groupes d'éléments et appelle `te0000`, lequel aiguille vers les routines `te0xxx` par `SELECT CASE` *(revue externe, à valider ; variable de sélection à identifier)*.
- **Lois de comportement :** `lc0000` aiguille vers les routines `lc0xxx` *(variable de sélection à valider)*.
- **Catalogues :** dans les versions récentes, des modules Python déclaratifs dans `catalo/cataelem/` relient (option, type d'élément) au numéro de `te` ; les anciennes versions utilisaient des fichiers `.cata` *(concordant avec une revue externe, à valider)*. Une expression régulière ne suffira pas : prévoir un `enrich.py` qui lit ces fichiers avec le module `ast` de Python, sans les exécuter.
- Le pack est **versionné par version de Code_Aster** (clé `covers`).

### 3.5. Points d'entrée : commandes utilisateur

- Une commande (ex. `STAT_NON_LINE`) déclarée dans un catalogue Python avec un numéro d'opérateur (`op=70`) est reliée par `implements` à la routine Fortran `op0070` *(à valider)*.
- **Toutes les commandes n'ont pas d'opérateur Fortran** : dans les versions récentes, une partie est orchestrée directement en Python ou en C++ avant d'appeler des routines Fortran plus profondes *(revue externe, à valider)*. Dans ce cas, le point d'entrée est relié à son implémentation Python (`fallback_target`).
- Nœuds `entry:<COMMANDE>` (`kind: entry_point`, `subtype: command`). C'est le point de départ naturel de l'exploration pour un utilisateur de Code_Aster.

### 3.6. Ponts

- **C/C++ → Fortran :** macros d'interface `CALLO_<ROUTINE>` / `CALL_<ROUTINE>`.
  - Sémantique : `CALLO_JEVEUO(...)` → préfixe retiré (`JEVEUO`) → minuscules → cible `f:jeveuo` *(forme exacte à valider)*.
  - Les préfixes sont essayés du plus long au plus court : `CALLO_` avant `CALL_`.
  - **Tests négatifs** à constituer à partir du code : identifiants qui commencent par `CALL_` sans être des appels Fortran.
  - Les macros `DEFS*` **déclarent** les routines Fortran côté C/C++ : elles créent des nœuds `binding`, pas des sites d'appel.
  - C'est aussi le test de la complétion IA (§5).
- **Python → C++ :** module compilé `libaster` *(à valider)* → entrée `bridges` avec `extension_modules`.
- **Interfaces Fortran :** fichiers `#include "asterfort/<routine>.h"`, utilisables comme source de signatures *(à valider)*.
- **Préprocesseur :** macros de configuration du type `ASTER_HAVE_MPI` ; les deux branches sont conservées et les sites annotés par leur condition.

### 3.7. Lois de comportement externes (MFront)

- Certaines lois sont générées en C++ par MFront et appelées depuis Fortran : arête `bridges` Fortran → code généré, si le code généré est présent dans le dépôt analysé.

### 3.8. Cas-tests (`astest/`)

- Fichiers `.comm` : commandes utilisées → points d'entrée → routines atteignables (sur-approximation statique).
- Import optionnel de couverture `gcov` / `lcov` pour une correspondance exacte.
- Fonction clé à démontrer : **« quels cas-tests relancer après avoir modifié `mmalgo` ? »**

---

## 4. Brouillon de `rules.yaml` (format version 1)

```yaml
pack: code_aster
version: "0.2"
format_version: 1
covers: { code_aster: ">=16" }                     # à valider
identifiers: [jeveuo, jemarq, jedema, utmess, wkvect, te0000, lc0000, rcvalb,
              libaster, bibfor, bibcxx, bibc, astest, asterfort, CALLO_]
detect:
  all_path: ["bibfor/", "bibcxx/", "code_aster/"]
noise:
  hide: [jemarq, jedema, utmess, assert, infniv]
  optional: [jeexin, jelira, dismoi, "getv*", rcvalb, rcvala]   # rcvalb / rcvala : à valider
  auto_detect_hubs: { min_fan_in: 300, max_fan_out: 3 }
extraction:
  known_arrays: [zi, zr, zc, zl, zk8, zk16, zk24, zk32, zk80]  # filet si jeveux.h est introuvable
memory_access:
  - { routine: jeveuo, name_arg: 1, mode_arg: 2, modes: { "L": reads, "E": writes },
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
  - { routine: wkvect, name_arg: 1, effect: creates,
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
  - { routine: jecreo, name_arg: 1, effect: creates,
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
  - { routine: jedetr, name_arg: 1, effect: destroys,
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
dispatch:
  - { routine: te0000, select_on: "<variable à valider>", target_pattern: "te{case:04d}" }
  - { routine: lc0000, select_on: "<variable à valider>", target_pattern: "lc{case:04d}" }
entry_points:
  - kind: command
    glob: "code_aster/Cata/Commands/*.py"          # à valider
    pattern: 'nom\s*=\s*"(?P<name>\w+)".*?op\s*=\s*(?P<op>\d+)'
    multiline: true
    target: "f:op{op:04d}"
    fallback_target: "py:code_aster.Commands.{name_lower}"   # commandes sans opérateur Fortran ; forme à valider
bridges:
  - { from: cpp, to: fortran, call_prefixes: ["CALLO_", "CALL_"], name_transform: [strip_prefix, lowercase] }
  - { from: cpp, to: fortran, declaration_patterns: ['DEFS\w*\(\s*(?P<name>\w+)'] }   # à valider
  - { from: python, to: cpp, extension_modules: [libaster] }                          # à valider
tests:
  - { kind: regression_case, glob: "astest/*.comm", uses_entry_points: true, coverage: optional }
glossary: glossary_code_aster.md
```

Le lien entre catalogues d'éléments et routines `te0xxx` est fait par `enrich.py` (§3.4).

---

## 5. Corpus et attentes

Deux corpus, comme le prévoit l'architecture (§5.4) : un **corpus de démarrage** dont les attentes ne portent que sur son périmètre, et un **corpus complet** pour les parcours de bout en bout.

### 5.1. Corpus de démarrage (lot 7)

```yaml
# tests/corpus/code_aster_start/manifest.yaml
corpus: code_aster_start
source: { path: "<emplacement local des sources>", revision: "<tag exact de la version de référence>" }
license: GPL-3.0
packs: [code_aster]
scope: ["code_aster/", "bibcxx/", "bibc/", "bibfor/nonlinear/", "bibfor/contact/"]
# le reste du dépôt est indexé (définitions seulement) : les appels vers l'extérieur sont out_of_scope
```

```yaml
# tests/corpus/code_aster_start/expectations.yaml — à compléter par l'auteur
inventory:
  languages: { fortran: { min_files: 100 }, python: { min_files: 10 }, cpp: { min_files: 10 }, c: { min_files: 1 } }
  max_unknown_rate: 0.01
expect:
  - node: "f:mmalgo"
  - node: "f:nmstat"                              # à valider : présent dans le périmètre ?
  - hidden: "f:utmess"
  - hidden: "f:jemarq"
  - no_call_to: ["f:zr", "f:zi", "f:zc", "f:zl", "f:zk8", "f:zk16", "f:zk24", "f:zk32", "f:zk80"]
  - writes: { routine: "<routine choisie dans le périmètre>", data: "data:mem:*.VALE", key_kind: family }
  - edge: { src: "<fonction C++ choisie>", dst: "f:<routine Fortran appelée par CALLO_>", kind: bridges }
  - out_of_scope_allowed: ["f:op*", "f:te*", "f:lc*"]   # définis hors du périmètre de démarrage
metrics:
  min_recall_definitions: 0.99
  min_recall_call_sites: 0.97
  min_precision_resolved: 0.98                    # par langage
  min_precision_lower_bound: 0.95
  max_unresolved_rate: 0.02
  max_parse_failure_rate: 0.02
```

### 5.2. Corpus complet (lot 14)

```yaml
# tests/corpus/code_aster_full/manifest.yaml
corpus: code_aster_full
source: { path: "<emplacement local des sources>", revision: "<même tag exact>" }
license: GPL-3.0
packs: [code_aster]
scope: ["."]                                      # dépôt entier, catalogues et astest compris
```

```yaml
# tests/corpus/code_aster_full/expectations.yaml — à compléter par l'auteur
expect:
  - path: { from: "entry:STAT_NON_LINE", to: "f:op0070", max_len: 4, edge_kinds: call_path }   # à valider
  - dispatches: { src: "f:te0000", min_targets: 100 }                                          # ordre de grandeur à valider
  - dispatches: { src: "f:lc0000", min_targets: 10 }                                           # à valider
  - catalog_links: { min: 100 }                   # (option, élément) → te0xxx, via enrich.py
  - tests_for: { routine: "f:mmalgo", min_cases: 1 }
metrics:
  min_precision_bridges: 0.95
  min_precision_bridges_lower_bound: 0.90
```

### 5.3. Échantillon de référence

Les liens et emplacements vérifiés à la main (environ 150 par langage, plus un groupe « ponts ») sont enregistrés dans `reference_sample.yaml` de chaque corpus, avec la révision exacte du code, puis rejoués automatiquement.

### 5.4. Test de la complétion IA (lot 13 de l'architecture)

On retire du pack l'entrée `bridges` par préfixes, puis on lance la boucle de complétion. Attendu :

- l'IA propose d'elle-même les préfixes `CALLO_` / `CALL_` avec la transformation `strip_prefix` + `lowercase` (ou une règle équivalente) ;
- la proposition passe les contrôles automatiques, y compris les tests négatifs ;
- elle réduit d'au moins 80 % les appels C++ → Fortran non résolus ;
- son aperçu, puis le résultat, sont comparés à la règle écrite à la main au lot 14.

---

## 6. Parcours de démonstration

- **Périmètre de départ (lots 7 à 11) :** `code_aster/`, `bibcxx/`, `bibc/`, `bibfor/nonlinear/`, `bibfor/contact/` — Python, C++, C et Fortran, identifiés par l'inventaire.
- **Parcours :** inventaire des langages, exploration autour de `nmstat` et `mmalgo`, filtrage du bruit (avant / après), absence de faux appels vers `zr` / `zi`, santé de l'analyse.
- **Après les lots 8 et 14 :** chemin complet `STAT_NON_LINE` → routine Fortran feuille, accès JEVEUX par niveau de précision, cas-tests associés.

---

## 7. Licence et marque

- Code_Aster est distribué sous GPL par EDF. L'analyser ne pose aucun problème pour CodeGraph-Sci.
- **Démonstrations :** la révision exacte des sources est fixée ; la provenance de chaque extrait (fichier, ligne, révision) est enregistrée ; les extraits sont accompagnés de la notice de licence de Code_Aster ; la démonstration est publiée sous GPL, avec attribution, dans un dossier ou dépôt séparé du cœur.
- **Aucun code source de Code_Aster** n'est intégré à une distribution commerciale de CodeGraph-Sci sans revue préalable.
- Le nom Code_Aster appartient à EDF : usage nominatif (« compatible avec Code_Aster »), sans suggérer de partenariat.
- Un contact avec l'équipe de développement avant publication peut ouvrir des retours, voire une collaboration.

---

## 8. Points à valider

1. Version de référence : v16, v17 ou les deux.
2. Déclaration de `zi`, `zr`, `zc`, `zl`, `zk8`… dans `jeveux.h` (bloc `COMMON` ?) et chemin d'inclusion correspondant.
3. Forme des noms d'objets de travail (`'&&<ROUTINE>.xxx'`) et fiabilité du préfixe `&&` comme marqueur d'objet local.
4. Correspondance `op=NN` → `op00NN`, rôle du superviseur, et liste des commandes sans opérateur Fortran (avec leur implémentation Python ou C++).
5. Rôle de `calcul`, variables de sélection et étendue réelle de `te0000` et `lc0000`.
6. Format des catalogues pour la version retenue (`catalo/cataelem/` en Python ou `.cata`) et contenu de `enrich.py`.
7. Forme exacte des macros `CALLO_` / `CALL_` / `DEFS*` et transformation de nom vers la routine Fortran ; identifiants à utiliser comme tests négatifs.
8. Fichiers d'interface `asterfort/<routine>.h` comme source de signatures.
9. Nom du module Python compilé (`libaster`) et emplacement des catalogues de commandes.
10. Liste définitive des routines de bruit (dont `rcvalb` / `rcvala`), à confronter à la détection automatique des hubs.
11. Contact avec l'équipe Code_Aster d'EDF avant publication.

---

## 9. Glossaire propre au code

- **JEVEUX :** gestionnaire de mémoire et d'objets nommés de Code_Aster (vecteurs, collections, bases).
- **`zi`, `zr`, `zk8`… :** tableaux globaux par lesquels on accède au contenu des objets JEVEUX (forme historique).
- **SD :** structure de données Code_Aster, ensemble d'objets JEVEUX partageant un préfixe de nom.
- **`te0xxx` / `lc0xxx` :** routines élémentaires (calculs par élément fini) / routines d'intégration des lois de comportement.
- **`op0xxx` :** routines Fortran implémentant les opérateurs (commandes).
- **`.comm` :** fichier de commandes d'une étude ou d'un cas-test.

---

## 7. Vérifications sur la version 17.5.7 (16 octobre 2026)

- **Tableaux `zr`, `zi`…** : déclarés dans `jeveux.h` (blocs `COMMON`) ; aucun site d'appel n'est créé (attente `no_call_to` vérifiée).
- **`jeveuo`** : modes `'L'` (522 appels dans `bibfor/nonlinear`) et `'E'` (185).
- **Aiguillages** : `te0000` sélectionne sur `numc` (`select case (numc)`, 600 branches) ; `lc0000` sur `numlcEff`.
- **Commandes** : `code_aster/Cata/Commands/*.py`, forme `NOM = OPER(nom="NOM", op=70, …)` ; les commandes sans opérateur (`MACRO(`) sont reliées à `code_aster/CodeCommands/<fichier>.py`.
- **Ponts C/C++ → Fortran** : les macros `CALL_X` / `CALLO_X` sont des `#define` de `bibc/include/aster_fort_*.h` qui se développent en `F_FUNC(X, x)` → `x_` ; les fonctions C appelables depuis le Fortran sont déclarées par `DEFS…(X, x, …)`. Le développement générique des macros C (cœur) et le pont `fortran_c` suffisent : aucune règle de préfixe n'est nécessaire en v17 (elle reste dans le pack pour les versions sans en-têtes).
- **`mmalgo`** n'existe plus en v17 ; l'attente du corpus de démarrage utilise `mmbouc` (boucle de contact).
- **`libaster`** : module pybind11 défini par `PYBIND11_MODULE(libaster, mod)` dans `bibcxx/PythonBindings/LibAster.cxx`, dont les fonctions sont exposées dans d'autres fichiers (à traiter : liaisons pybind11 réparties sur plusieurs fichiers).
