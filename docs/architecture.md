# CodeGraph-Sci — Architecture et plan de réalisation

**Version :** 7.0 — document d'exécution (16 octobre 2026)  
**Auteur :** Marian Bogdan Neagoe, PhD  
**Objet :** application de bureau, 100 % hors ligne, qui identifie les langages d'un dépôt de code scientifique ou industriel (Fortran, Python, C, C++ au départ), construit le graphe « qui appelle qui » à travers ces langages, et répond à la question « qui appelle quoi, et où ? ».

> **Comment utiliser ce document.**
>
> - **§0 à §2 :** ce que l'application doit faire, et les verrous techniques à lever en premier.
> - **§3 :** l'architecture, avec les contrats que le code doit respecter.
> - **§4 et §5 :** le plan de réalisation en **lots** numérotés, chacun avec son test de validation, puis la stratégie de test.
> - **§6 à §8 et annexes :** extensibilité, contraintes de licence, décisions, consignes pour l'agent de développement (Annexe C, à copier dans `AGENTS.md`).
>
> Ce document est **générique** : aucune règle propre à un code analysé n'y figure. Chaque code est un cas de test décrit dans `docs/packs/<code>.md`. La stratégie commerciale et de licence est dans `docs/strategie_licence.md`.

---

## 0. En une page

**Ce que fait l'application.** On lui donne un dossier de code source.

1. Elle **identifie les langages** présents, fichier par fichier, et vérifie qu'elle sait tous les analyser.
2. Si un langage ou une liaison entre langages lui est inconnu, l'**IA locale définit les mots-clés manquants** (définitions de fonctions et de subroutines, appels, inclusions, liaisons entre langages). Ses propositions sont contrôlées automatiquement, montrées à l'utilisateur avec leur effet sur le graphe, puis enregistrées dans le **profil d'analyse** du projet.
3. L'analyse, **entièrement déterministe**, construit le graphe d'appels à partir de ce profil et le stocke dans une base locale. Chaque appel constaté dans le code est conservé comme un **site d'appel** (fichier, ligne, colonne, condition, origine).
4. Une fenêtre de bureau permet de l'explorer : pour chaque routine, **combien de routines l'appellent et lesquelles**, ce qu'elle appelle, les liens entre fichiers, le chemin entre deux routines, l'impact d'une modification.

**Contraintes non négociables**

| # | Contrainte | Conséquence technique |
| :--- | :--- | :--- |
| C1 | Application de bureau, pas d'application web | Interface Python + Qt (PySide6) ; ni navigateur, ni serveur |
| C2 | 100 % hors ligne | Aucun accès réseau, aucun port ouvert, vérifié sur l'application distribuée |
| C3 | Version complète transférable sur clé USB | Dossier portable avec Python embarqué, un par système : Linux x86_64 (cible : Ubuntu) et Windows x64 |
| C4 | Machine modeste, CPU seul | L'interface ne charge jamais tout le graphe ; tout est précalculé et paginé ; l'IA n'est appelée que sur des échantillons |
| C5 | Structuration déterministe | Même dépôt + même profil d'analyse + mêmes versions = même graphe ; l'IA prépare le profil, elle n'intervient jamais pendant l'analyse |
| C6 | Dépôts multi-langages dès le départ | Le premier cas de test mélange Fortran, Python et C ou C++ : l'inventaire des langages et les quatre adaptateurs arrivent dans les premiers lots |
| C7 | Extensible | Nouveaux langages et nouveaux codes ajoutés par plugins ou par profils de mots-clés, sans modifier le cœur |
| C8 | Pas de compilateur disponible | Validation de l'analyse sans compilation, par échantillons vérifiés (§2.1) |

**Ordre de réalisation.** On construit de bas en haut ; chaque lot se termine par un test qui doit passer avant de commencer le suivant (détail au §4). Le lot 7 est un **point d'arrêt** : tant que la justesse du graphe n'est pas démontrée, on ne développe pas l'interface.

| Lot | Titre | Dépend de |
| :--- | :--- | :--- |
| 0 | Squelette portable (clé USB, hors ligne) | — |
| 1 | Modèle de données et stockage | 0 |
| 2 | Inventaire des langages et profil d'analyse | 1 |
| 3 | Mini-codes de référence (tests écrits avant le code) | 2 |
| 4 | Adaptateur Fortran (avec banc comparatif des parseurs) | 3 |
| 5 | Adaptateurs Python, C et C++ | 3 |
| 6 | Link, Index et commande `cgs scan` | 4, 5 |
| 7 | Validation sur un code réel (verrou V1, point d'arrêt) | 6 |
| 8 | Ponts inter-langages | 6 |
| 9 | API de requêtes et ligne de commande | 7, 8 |
| 10 | Application de bureau : inventaire, recherche, appelants, inspecteur | 9 |
| 11 | TreeGraph fichiers et fonctions | 10 |
| 12 | Packs, profils de langage par mots-clés, filtrage du bruit | 11 |
| 13 | IA : identification des langages et complétion des mots-clés | 12 |
| 14 | Pack du cas de test n°1 | 13 |
| 15 | IA : explications | 13 |
| 16 | Édition Pro, conformité des licences et version finale | 14, 15 |

---

## 1. Ce que l'application doit faire

### 1.1. Questions auxquelles elle répond

| Priorité | Question | Exemple de réponse |
| :--- | :--- | :--- |
| **À l'ouverture** | Quels langages contient ce dépôt, et sont-ils tous couverts ? | « Fortran 9 120 fichiers, Python 2 400, C++ 1 830, C 210 — tous couverts ; 40 fichiers `.xyz` : langage inconnu, mots-clés proposés par l'IA » |
| **Défaut** | Combien de routines appellent `X`, et lesquelles ? | « `X` est appelée par 37 routines dans 21 fichiers » + liste (routine, fichier, ligne de chaque appel) |
| 1 | Qu'appelle `X` ? | Liste des routines appelées, avec les lignes des appels |
| 1 | Quels fichiers sont liés à ce fichier ? | Fichiers appelés et appelants, avec le nombre d'appels |
| 2 | Comment `A` atteint-il `B` ? | Chemins d'appel possibles de `A` à `B`, à travers les langages, avec la nature de chaque étape |
| 2 | Si je modifie `X`, qu'est-ce qui est concerné ? | Appelants transitifs, points d'entrée, tests |
| 3 | Quelles données `X` lit-elle ou écrit-elle ? | Blocs `COMMON`, variables de module, objets mémoire décrits par un pack, avec leur degré de précision |
| 3 | Quels tests relancer après une modification ? | Liste classée (avec un pack qui décrit les tests du code) |

### 1.2. Vues de l'application

| Vue | Contenu | Usage |
| :--- | :--- | :--- |
| **Inventaire des langages** | Par langage : nombre de fichiers et de lignes, adaptateur utilisé (natif, profil de mots-clés, aucun) ; fichiers non reconnus ; propositions de l'IA et leur état | Savoir ce qui est analysé, et comment |
| **Recherche** | Champ unique : routines, fichiers, modules (recherche floue) | Point de départ de toute exploration |
| **Panneau Appelants / Appelés** | Nombre + liste triable ; double-clic → code à la ligne de l'appel | Réponse à la question par défaut |
| **TreeGraph fonctions** | Arbre dessiné des appels depuis une routine (vers les appelés ou vers les appelants), dépliable nœud par nœud | Comprendre une chaîne d'appels |
| **TreeGraph fichiers** | Même principe au niveau des fichiers et des répertoires : un lien = au moins un appel, épaisseur = nombre d'appels ; double-clic sur un lien → appels détaillés | Comprendre l'architecture d'un module |
| **Explorateur de fichiers** | Arborescence du dépôt avec, par fichier, son langage, le nombre de routines et de liens | Navigation classique |
| **Inspecteur de code** | Source en lecture seule, colorée, lignes des appels surlignées ; clic sur un appel → routine appelée ; alerte si le fichier a changé depuis l'analyse | Lire le code |
| **Santé de l'analyse** | Fichiers analysés, en repli, en échec ; sites ambigus et non résolus, regroupés ; métriques de validation | Savoir si l'on peut faire confiance au graphe |

Dans les deux TreeGraph, une routine ou un fichier déjà affiché ailleurs dans l'arbre est marqué « ↺ déjà vu » et n'est pas redéplié automatiquement : c'est ce qui rend lisibles les cycles et les appels partagés.

### 1.3. Exigences non fonctionnelles

Machine de référence : portable 4 cœurs, 8 Go de mémoire vive, sans carte graphique dédiée. Ces cibles sont des **objectifs à mesurer** (lots 2, 6, 7, 9, 11, 13) ; elles seront ajustées d'après les mesures réelles.

| Mesure | Cible |
| :--- | :--- |
| Inventaire des langages d'un dépôt d'environ 15 000 fichiers | < 1 min |
| Analyse complète du même dépôt | < 15 min |
| Ré-analyse après modification de 50 fichiers au plus | < 30 s |
| Préparation assistée par IA (identification + complétion) | Au plus 3 itérations de 10 appels au modèle ; chaque appel < 60 s |
| Ouverture d'un projet déjà analysé | < 3 s |
| Appelants d'une routine (nombre + liste) | < 100 ms |
| Dépliage d'un nœud dans un TreeGraph | < 200 ms |
| Nœuds dessinés simultanément | 300 par défaut (réglable) ; au-delà, regroupement « +N » |
| Mémoire vive de l'application, sans IA | < 1,5 Go sur le cas de test n°1 |
| Interface pendant une analyse | Reste utilisable (analyse dans un processus séparé) |

### 1.4. Ce que l'analyse statique peut dire, et ce qu'elle ne peut pas dire

- Elle donne les **chemins d'exécution possibles** : tout ce que le code *peut* appeler.
- Le chemin **réellement suivi** pendant un calcul dépend des données d'entrée : un `SELECT CASE` choisit une branche à l'exécution. Les étapes d'un chemin qui passent par un aiguillage sont affichées comme « possibles ». Un pack peut restreindre les chemins à partir d'un point d'entrée ou d'une option ; il ne peut pas les deviner sans exécuter le code.
- Chaque lien affiché a un **niveau de confiance** (`exact`, `resolved`, `heuristic`, `ambiguous`), une **origine** (adaptateur natif, profil de mots-clés, pont, règle proposée par l'IA…) et des preuves (sites d'appel) : l'utilisateur sait toujours sur quoi repose ce qu'il voit.
- Pour les données, **mieux vaut un lien approximatif signalé comme tel qu'une fausse précision** : un accès dont l'objet exact est inconnu est rattaché à une famille d'objets, et marqué comme tel (§3.5).

### 1.5. Rôle de l'IA

L'IA locale a trois rôles, dans cet ordre de priorité :

1. **Identifier les langages** que l'inventaire déterministe n'a pas su reconnaître (extension inconnue ou ambiguë, fichier sans extension), à partir de l'extension et du contenu de quelques fichiers d'exemple.
2. **Vérifier qu'on a tous les éléments pour construire le graphe et, sinon, définir elle-même les mots-clés manquants :**
   - pour un langage sans adaptateur : mots-clés de définition (fonction, subroutine, procédure…), d'appel, d'inclusion, marqueurs de commentaires et de chaînes → un **profil de langage par mots-clés** (§3.9) ;
   - pour des appels restés non résolus : préfixes ou mots-clés de liaison entre langages (par exemple un préfixe de macro qui appelle une routine Fortran depuis du C++) → une **règle de liaison**.
   L'IA peut s'appuyer sur un document technique fourni par l'utilisateur ; sinon, sur ce qu'elle connaît déjà des langages.
3. **Expliquer** une routine à partir de ce que le graphe fournit, avec des citations vérifiées.

**Comment l'IA reste compatible avec le déterminisme et la justesse**

- Ses propositions sont **contrôlées automatiquement** (§3.13). Ces contrôles mesurent la plausibilité, pas la vérité : une cible qui existe n'est pas forcément la bonne. C'est pourquoi, par défaut, l'utilisateur **valide en un clic** après avoir vu l'aperçu des liens ajoutés et retirés. Un mode d'adoption automatique existe, activable par projet (§3.13).
- Une proposition adoptée est **écrite dans le profil d'analyse** du projet, un fichier figé et versionné. L'analyse ne lit que ce profil : elle n'appelle jamais l'IA.
- Les liens issus d'une règle proposée par l'IA restent **marqués comme tels** (`origin`, confiance `heuristic`) et peuvent être masqués d'un clic.
- **Sans modèle** (édition sans IA), tout fonctionne : les langages inconnus sont signalés, et leurs profils de mots-clés peuvent être écrits à la main.

---

## 2. Les verrous techniques et comment les lever

### 2.1. Verrou V1 — Extraction juste dans un dépôt multi-langages, sans compilateur

**Pourquoi c'est difficile**

- **Reconnaître le langage de chaque fichier :** `.h` peut être du C ou du C++, `.inc` du Fortran ou autre chose, certains fichiers n'ont pas d'extension, `.F90` doit passer par le préprocesseur, `.f` est souvent en format fixe.
- **Fortran :** préprocesseur (`#ifdef`, `#include`) ; formats fixe et libre ; `x = f(i)` est soit un appel de fonction, soit un accès à un tableau, et la déclaration du tableau se trouve souvent dans un fichier inclus ou un bloc `COMMON` ; fonctions intrinsèques ; interfaces génériques, procédures passées en argument ; « call x » dans un commentaire ou une chaîne.
- **C et C++ :** macros qui masquent des appels, surcharges (deux méthodes de même nom), fonctions `static` de même nom dans des fichiers différents, templates.
- **Python :** appels dynamiques ; anciens fichiers en Python 2, que le module `ast` de Python 3 ne lit pas.
- **Partout :** encodages anciens (Latin-1 avec commentaires accentués), fins de ligne Windows, fichiers très volumineux ou malformés.

**Comment prouver que c'est juste, sans compilateur.** Contrôles automatisés dans `cgs audit` (lot 7) :

| Contrôle | Principe | Ce qu'il mesure |
| :--- | :--- | :--- |
| Mini-codes de référence | Petits dépôts écrits à la main, dont l'inventaire et le graphe attendus sont connus exactement | Exactitude sur chaque piège |
| Cohérence de l'inventaire | Langage de chaque fichier confronté au contexte : un `.h` inclus par des fichiers C++ est du C++, un `.inc` inclus par du Fortran est du Fortran | Fichiers mal attribués |
| Référence textuelle indépendante | Recherche simple, ligne par ligne, des définitions (`SUBROUTINE`, `FUNCTION`, `def`, `class`…) et des instructions `CALL`, hors commentaires et chaînes | **Contre-vérification** du rappel. Cette référence est elle-même imparfaite : ses écarts avec le graphe sont examinés, pas pris pour la vérité |
| Double extraction | Deux extracteurs différents par langage (parseur et extracteur à motifs) ; chaque désaccord est listé et classé | Erreurs propres à l'un des deux |
| **Échantillon de précision** | Tirage stratifié de liens résolus : un groupe par langage, plus un groupe « ponts » ; environ 150 liens par groupe (graine fixe), vérifiés à la main dans une fiche (une touche par lien) | **Précision**, avec intervalle de confiance |
| **Échantillon de rappel** | Tirage d'emplacements de code au hasard (lignes susceptibles de contenir un appel) ; la personne indique les appels réellement présents ; comparaison avec les sites d'appel extraits | **Rappel** des sites d'appel, avec intervalle de confiance |
| Invariants | Définitions en double, sites non résolus, routines jamais appelées, fichiers en échec | Cohérence globale |

Les échantillons vérifiés à la main sont **enregistrés** (`reference_sample.yaml` du corpus). Ils deviennent un test de non-régression automatique : l'effort manuel (quelques heures) n'est fait qu'une fois par corpus.

**Métriques et seuils** (sur le cas de test n°1, pour chacun de ses langages ; bornes basses = intervalle de Wilson à 95 %) :

| Métrique | Définition | Seuil |
| :--- | :--- | :--- |
| Attribution des fichiers | Fichiers source attribués à un langage couvert ou explicitement classés (ignorés, inconnus) | ≥ 99 % |
| Fichiers en échec | Ni parseur ni repli | ≤ 2 % |
| Rappel des définitions | Définitions trouvées par rapport à la référence textuelle, écarts examinés | ≥ 99 % |
| Rappel des sites d'appel | Estimé par l'échantillon de rappel | ≥ 97 %, borne basse ≥ 93 % |
| Précision des liens résolus | Estimée par l'échantillon de précision | ≥ 98 %, borne basse ≥ 95 % |
| Précision des ponts | Groupe « ponts » de l'échantillon (après le lot 8) | ≥ 95 %, borne basse ≥ 90 % |
| Sites ambigus | Sites à plusieurs cibles possibles | Mesurés et expliqués |
| Sites non résolus (hors externes connus et hors périmètre) | — | ≤ 2 %, tous regroupés et expliqués |

Avec 150 liens et au plus 2 erreurs, la borne basse de la précision dépasse 95 % : c'est ce qui fixe la taille des échantillons.

**Plan B** si les critères ne sont pas atteints : changer de parseur principal parmi les candidats sous licence permissive évalués au lot 4 (§3.15), renforcer l'extracteur à motifs, ou ajouter des règles au pack. fxtran, sous licence GPL-3.0, n'est envisageable qu'en outil externe après revue de licence (§7). La décision est consignée au §8.

Si un compilateur devient disponible plus tard, il apportera un contrôle de plus (symboles des fichiers objets) ; il n'est pas nécessaire.

### 2.2. Verrou V2 — Fonctionner depuis une clé USB, sans Internet

Levé **dès le lot 0**, avant toute fonctionnalité : un dossier contenant Python, Qt et les bibliothèques, qui démarre sur une machine vierge sans réseau. Points de vigilance connus :

- Un *venv* n'est pas déplaçable (il contient des chemins absolus) : on utilise un Python embarqué dans le dossier (PyInstaller, mode « dossier »).
- Le mode « fichier unique » est exclu : il se décompresse à chaque lancement, ce qui est très lent depuis une clé.
- **Compatibilité Linux :** un exécutable ne démarre que sur des systèmes dont la bibliothèque C (glibc) est au moins aussi récente que celle de la machine de construction. La version Linux est donc construite dans un conteneur à glibc 2.28 (AlmaLinux ou Rocky Linux 8) : elle démarre sur Ubuntu 20.04 et suivants, et aussi sur les stations RHEL/Rocky 8 fréquentes dans l'industrie. Attention : les Python des images `manylinux` ne conviennent pas, car PyInstaller exige une bibliothèque Python partagée ; utiliser un Python compilé avec bibliothèque partagée (à vérifier au lot 0).
- Ubuntu 22.04 : Qt 6.5 et suivants ont besoin de `libxcb-cursor0`, absente par défaut ; la bibliothèque est embarquée dans le dossier, ou son absence est détectée avec un message clair.
- **Processeurs anciens :** une bibliothèque d'inférence compilée pour AVX2 ou AVX-512 plante (« instruction illégale ») sur un processeur qui ne les a pas. llama.cpp est donc compilé avec choix des instructions au démarrage (variantes multiples du moteur CPU), ou livré en deux variantes (base et AVX2) ; `cgs selftest` affiche les jeux d'instructions détectés.
- **Windows :** chemins de plus de 260 caractères (application déclarée compatible avec les chemins longs) ; un exécutable non signé peut déclencher SmartScreen ou un antivirus (signature prévue au lot 16).

### 2.3. Verrou V3 — Fluidité sur une machine modeste

L'interface ne manipule jamais le graphe entier. Les stratégies sont détaillées au §3.12 : précalculs pendant l'analyse, requêtes paginées, nombre de nœuds dessinés plafonné, regroupement, mise en page en arrière-plan, niveau de détail selon le zoom. Côté écriture, la base est construite par insertions groupées, index créés à la fin (§3.6).

### 2.4. Verrou V4 — Une IA utile sur CPU, sans casser le déterminisme

**Difficultés :** un petit modèle sur CPU est lent et se trompe facilement ; on ne peut pas lui faire lire 15 000 fichiers ; et une règle plausible n'est pas forcément juste.

**Parades :**

- **Le déterministe d'abord :** l'inventaire par extensions et signatures de contenu traite l'immense majorité des fichiers ; l'IA ne voit que les groupes de fichiers restés inconnus et les sites restés non résolus.
- **Échantillons courts et regroupés :** l'IA reçoit un résumé (comptages, quelques extraits de code) par groupe, jamais le dépôt entier.
- **Des mots-clés, pas du code :** l'IA remplit des gabarits simples (listes de mots-clés, préfixes, transformations de noms, marqueurs de commentaires) plutôt que d'écrire des expressions régulières ; c'est le cœur qui les transforme en règles.
- **Génération contrainte par le schéma :** la réponse du modèle est toujours un fichier valide.
- **Contrôles automatiques chiffrés**, puis **aperçu des changements et validation en un clic** (§3.13) ; nombre d'appels au modèle borné (§1.3).
- **Tests sans modèle :** en intégration continue, un modèle factice renvoie des réponses enregistrées ; la chaîne complète est testée de façon déterministe. Les tests avec le vrai modèle tournent sur la machine de développement.

---

## 3. Architecture

### 3.1. Vue d'ensemble

```text
┌────────────────────────────────────────────────────────────────┐
│ APPLICATION DE BUREAU (PySide6) — processus principal          │
│ Inventaire · Recherche · Appelants · TreeGraph                 │
│ Inspecteur de code · Santé de l'analyse · IA (Pro)             │
└──────┬────────────────────────┬────────────────────────┬───────┘
       │ threads                │ sous-processus         │ tubes
       │ (lecture)              │ (progression)          │ (JSON)
┌──────▼──────┐   ┌─────────────▼─────────────┐   ┌──────▼───────┐
│ API de      │   │ cgs inventory             │   │ Worker IA    │
│ requêtes    │   │ cgs scan (déterministe)   │   │ (Pro)        │
│ query/      │   │ lit le profil             │   │ modèle GGUF  │
└──────┬──────┘   └─────────────┬─────────────┘   └──────┬───────┘
       │ lit                    │ écrit                  │ propose
       └───────────┬────────────┘                        │
          ┌────────▼────────┐               ┌────────────▼───────┐
          │ <projet>.sqlite │               │ profil d'analyse   │
          └─────────────────┘               └────────────────────┘

Aucun port réseau, aucune connexion : uniquement des fichiers, des appels
de fonctions, des sous-processus et des tubes. cgs scan n'appelle jamais l'IA.
```

- **Processus principal :** l'interface Qt. Il ne lit jamais les fichiers source pour l'analyse et n'exécute lui-même aucune requête longue.
- **Threads de requêtes :** chaque requête (appelants, dépliage, recherche) s'exécute dans un thread du pool Qt, avec sa propre connexion SQLite en lecture seule, puis renvoie son résultat par signal.
- **Processus d'analyse :** l'interface lance `cgs inventory` puis `cgs scan` (le même programme qu'en ligne de commande) comme sous-processus, lit leur progression (une ligne JSON par événement) et peut les interrompre. Un plantage de parseur ne peut pas faire tomber l'interface ; un fichier qui dépasse son délai d'analyse est marqué en échec, et l'analyse continue.
- **Processus IA (Pro) :** sous-processus dédié qui charge le modèle ; il dialogue par l'entrée et la sortie standard (un message JSON par ligne). **Aucun port réseau**, même en interne. Il n'est jamais appelé par `cgs scan`.
- **Fichiers du projet :** le profil d'analyse (`analysis_profile.yaml`, les règles adoptées) et la base SQLite.

### 3.2. Inventaire des langages et profil d'analyse

**Étape déterministe : `cgs inventory <dossier>`**

1. **Parcours du dépôt :** respect du `.gitignore` et des exclusions configurées (répertoires de construction, `.git`) ; les fichiers binaires (octets nuls) sont ignorés ; les liens symboliques en boucle et les fichiers illisibles sont signalés sans bloquer le parcours.
2. **Table des extensions** (configurable) :

| Extensions | Langage | Particularité |
| :--- | :--- | :--- |
| `.f`, `.for`, `.f77`, `.ftn` | Fortran | Format fixe par défaut |
| `.f90`, `.f95`, `.f03`, `.f08` | Fortran | Format libre |
| `.F`, `.F90`, `.FOR`… (majuscule) | Fortran | Passage par le préprocesseur |
| `.py` | Python | Python 2 détecté et signalé |
| `.c` | C | — |
| `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx` | C++ | — |
| `.h` | **C ou C++** | Tranché à l'étape 4 |
| `.inc`, `.fi`, `.fh` | **Fortran ou autre** | Tranché à l'étape 4 |
| Autres (`.pyx`, `.cu`, `.m`…) | Connu mais non couvert en première version | Signalé dans l'inventaire |

3. **Signatures de contenu**, pour les fichiers sans extension ou ambigus : ligne `#!` (ex. `#!/usr/bin/env python`), lignes de mode d'éditeur (`-*- mode: f90 -*-`), et score de mots-clés caractéristiques sur les premières lignes, avec des poids fixes (ex. `subroutine`, `end do` pour Fortran ; `namespace`, `template`, `::` pour C++ ; `def`, `import` pour Python).
4. **Contexte du dépôt :** un `.h` inclus par des fichiers C++, ou qui contient `class`, `namespace` ou `template`, est du C++ ; sinon du C. Un `.inc` inclus par des fichiers Fortran est du Fortran. Les répertoires qui contiennent des fichiers inclus forment les **chemins d'inclusion** du profil.
5. **Résultat par fichier :** langage, variante (format fixe ou libre, préprocesseur, Python 2), confiance, règle qui a décidé. Les fichiers non reconnus sont regroupés par extension.
6. **Rapport de couverture :** par langage, nombre de fichiers et de lignes, et adaptateur disponible — natif, profil de mots-clés, ou aucun.

**Étape IA, optionnelle (lot 13) :** pour chaque groupe de fichiers non reconnus, l'IA reçoit l'extension et le début de trois fichiers d'exemple, et répond : langage, adaptateur existant à utiliser (ex. `.ftn` → Fortran) ou besoin d'un profil de mots-clés (§3.9). Puis, après une première analyse, elle examine les sites non résolus (§3.13).

**Le profil d'analyse** rassemble toutes ces décisions dans un fichier du projet. L'analyse ne lit que lui :

```yaml
# <projet>/analysis_profile.yaml
profile_version: 4
scope: { include: ["src/"], exclude: ["src/third_party/"] }    # périmètre analysé en détail
languages:
  fortran: { files: 9120, adapter: native:fortran, variants: [fixed, free, preprocessed] }
  python:  { files: 2400, adapter: native:python }
  cpp:     { files: 1830, adapter: native:cpp }
  c:       { files: 210,  adapter: native:c }
  acme_script: { files: 40, adapter: keywords:acme_script, source: ai, status: approved }
include_paths: ["include/", "src/common/"]
preprocessor: { defines: { HAVE_MPI: "1" }, keep_all_branches: true }
file_overrides:
  - { glob: "include/*.h", language: cpp, reason: "inclus par des fichiers C++" }
  - { glob: "legacy/*.inc", language: fortran, reason: "inclus par des fichiers Fortran" }
ignored:
  - { ext: ".dat", files: 300, reason: "données" }
packs: [generic_noise, generic_fortran]
rules:
  - { id: r-0001, kind: bridge, source: ai, status: approved, file: rules/r-0001.yaml }
history:
  - { version: 4, change: "règle r-0001 approuvée", by: "utilisateur" }
```

- Le profil est versionné ; chaque analyse enregistre l'empreinte du profil utilisé.
- L'utilisateur peut modifier le profil dans l'interface (forcer un langage, ignorer un groupe de fichiers, approuver ou refuser une règle) ; chaque modification crée une nouvelle version.

### 3.3. Le pipeline d'analyse

```text
 cgs inventory ──► profil d'analyse ◄──── IA (optionnelle, lot 13) :
                         │                 langages inconnus, mots-clés manquants
                         ▼                               ▲
   Extract → Link → Enrich → Index ──► Diagnostic ───────┘
   └──────────── cgs scan : déterministe ───────────┘
```

| Étape | Entrée | Sortie | Où | Propriétés |
| :--- | :--- | :--- | :--- | :--- |
| **Inventory** | Le dépôt | Langage de chaque fichier, chemins d'inclusion, rapport de couverture | `inventory/` | Déterministe ; < 1 min |
| **Extract** | Un fichier + son langage + ses fichiers inclus | *Faits* : définitions avec leurs symboles locaux, sites d'appel non résolus, accès aux données, directives, inclusions | `extract/` (un adaptateur par langage, ou adaptateur par mots-clés) | Fichier par fichier, en parallèle, avec délai maximal ; cache (§3.6) |
| **Link** | Tous les faits | Sites d'appel résolus, ambigus, externes, hors périmètre ou non résolus ; nœuds | `link/` (table de symboles + ponts) | Global ; normalise les noms (casse, décoration) |
| **Enrich** | Graphe | Masquages, accès aux données, aiguillages, points d'entrée, tests | `enrich/` (packs) | Règles déclaratives figées |
| **Index** | Graphe enrichi | Arêtes agrégées, comptages, liens entre fichiers et répertoires, taille d'impact, recherche plein texte | `store/`, `algo/` | Algorithmes en Python standard (§3.6) |
| **Diagnostic** | Base | Santé de l'analyse ; sites non résolus et ambigus regroupés par motif | `audit/` | Sert à l'utilisateur et, s'il est activé, à l'IA |

- **Ré-analyse :** l'étape Extract n'est refaite que pour les fichiers dont la clé de cache a changé (le fichier, un fichier qu'il inclut, son adaptateur ou les paramètres d'extraction) ; les étapes suivantes sont refaites en entier, ce qui est rapide.
- **Analyse partielle :** si le profil limite le périmètre (`scope`), une passe légère indexe quand même les **définitions** de tout le dépôt (noms seulement). Un appel vers une routine définie hors du périmètre pointe vers un nœud marqué `out_of_scope` : il n'est pas compté comme « non résolu ».
- **Calculs de l'étape Index :** composantes fortement connexes (algorithme de Tarjan, en version itérative pour éviter la limite de récursion de Python), graphe condensé, puis taille d'impact de chaque nœud par propagation d'ensembles de bits (entiers Python) dans l'ordre topologique ; sur le graphe brut et sur le graphe filtré.

### 3.4. Découpage en paquets et règles de dépendance

| Paquet | Rôle | Peut importer |
| :--- | :--- | :--- |
| `core` | Modèle de données, identifiants, profil d'analyse (types), versions des formats | (rien d'interne) |
| `algo` | Algorithmes de graphe : Tarjan itératif, condensation, ensembles de bits, parcours bornés | `core` |
| `inventory` | Détection des langages, rapport de couverture, lecture et écriture du profil | `core` |
| `extract` | Adaptateurs natifs et adaptateur par mots-clés | `core` |
| `link` | Table de symboles, ponts inter-langages | `core` |
| `enrich` | Moteur de packs, schémas, packs génériques | `core` |
| `store` | Schéma SQLite, écriture, lecture, cache | `core` |
| `query` | API de requêtes (§3.10) | `core`, `store`, `algo` |
| `layout` | Mise en page des TreeGraph | `core` |
| `audit` | Diagnostic et contrôles de validation (§2.1) | `core`, `inventory`, `extract`, `store`, `query` |
| `scan` | Orchestration du pipeline | `core`, `algo`, `inventory`, `extract`, `link`, `enrich`, `store` |
| `cli` | Commande `cgs` | `inventory`, `scan`, `query`, `audit` |
| `ui` | Application de bureau | `core`, `query`, `layout` — **jamais** `extract`, `link`, `enrich` ni `store` directement |
| `codegraph_sci_pro` | IA, packs de codes, licence | tout le cœur ; le cœur ne l'importe jamais |

Ces règles sont vérifiées automatiquement par `import-linter` dès le lot 0.

### 3.5. Modèle de données

**Identité des symboles.** Chaque symbole a un `uid` stable et unique, utilisé partout en interne, et un `display_name` lisible pour l'interface.

| Langage | Forme du `uid` | Remarques |
| :--- | :--- | :--- |
| Fortran | `f:<nom>` ; procédure de module `f:<module>::<nom>` | En minuscules (langage insensible à la casse) |
| C | `c:<nom>` ; fonction `static` : `c:<nom>@<fichier>` | Deux fonctions `static` de même nom dans deux fichiers sont deux symboles |
| C++ | `cpp:<ns>::<Classe>::<méthode>(<types des paramètres normalisés>)` | La signature fait partie de l'identité ; le `display_name` ne la montre pas |
| Python | `py:<module>.<nom qualifié>` | — |
| Profil de mots-clés | `kw:<langage>:<nom>` | — |
| Autres | `file:<chemin>`, `entry:<nom>`, `data:<clé>`, `test:<id>`, `ext:<bibliothèque>:<nom>` | Chemins relatifs à la racine du dépôt, avec des `/` |

- **Variantes préprocesseur :** si une même routine est définie dans plusieurs branches `#ifdef`, chaque définition reçoit un suffixe `#2`, `#3`… et garde sa condition.
- **Surcharges et interfaces génériques :** quand l'appel ne permet pas de choisir (types inconnus en analyse statique), le site d'appel garde **toutes les cibles candidates** et devient `ambiguous`.

**Identité des sites d'appel.** Chaque appel ou usage constaté dans le code est un **site** : fichier, ligne, colonne, routine appelante, texte de la cible tel qu'écrit. Le site garde sa condition préprocesseur, son origine, sa confiance et son état de résolution :

| État (`resolution`) | Sens |
| :--- | :--- |
| `resolved` | Une cible unique dans le dépôt |
| `ambiguous` | Plusieurs cibles candidates |
| `external` | Bibliothèque connue hors dépôt (MPI, BLAS…) ou fonction intrinsèque |
| `out_of_scope` | Cible définie dans le dépôt, hors du périmètre analysé |
| `unresolved` | Aucune cible trouvée |

Une **arête** du graphe est l'agrégation des sites de même (appelant, appelé, type) : elle porte leur nombre, la confiance la plus faible, l'ensemble des origines et des conditions. Les requêtes rapides utilisent les arêtes ; la navigation ligne par ligne utilise les sites.

**Types de nœuds :** `kind` prend une valeur d'une liste fixe ; `subtype` est libre et fourni par les plugins.

| `kind` | Signification | `subtype` (exemples) |
| :--- | :--- | :--- |
| `file` | Fichier source | — |
| `module` | Module, paquet, espace de noms | `py_module`, `f_module`, `cpp_namespace` |
| `type` | Classe, structure, type dérivé | `py_class`, `cpp_class`, `f_derived_type` |
| `routine` | Fonction, subroutine, méthode, procédure, programme | `f_subroutine`, `f_function`, `f_program`, `cpp_method`, `py_function`, `kw_routine` |
| `interface` | Interface générique ou abstraite | `f_generic_interface` |
| `binding` | Exposition ou déclaration d'un symbole dans un autre langage | `pybind11_def`, `bind_c`, `macro_declaration` |
| `data` | Donnée partagée | `common_block`, `module_variable`, `c_global`, `memory_object` |
| `entry_point` | Point d'entrée utilisateur ou externe | `command`, `program_main`, `external_callback` |
| `dispatch_target` | Entrée de catalogue ou branche d'aiguillage | `catalog_entry`, `case_branch` |
| `test_case` | Test ou cas-test | `unit_test`, `regression_case` |
| `external` | Symbole hors dépôt | `mpi`, `blas`, `intrinsic`, `system` |

**Types d'arêtes :** `contains`, `calls`, `uses`, `inherits`, `binds`, `bridges`, `implements`, `dispatches`, `reads`, `writes`, `creates`, `destroys`, `exercises`.

**Données partagées : trois niveaux de précision.** Un accès à une donnée (bloc `COMMON`, variable de module, objet d'un gestionnaire mémoire décrit par un pack) est rattaché à l'objet le plus précis qu'on sache identifier, et toujours à sa famille :

| Niveau (`key_kind`) | Exemple fictif | Sens |
| :--- | :--- | :--- |
| `literal` | `data:mem:solver.state.VALUES` | Nom entièrement connu dans le code |
| `symbolic` | `data:mem:f:update_state:name//'.VALUES'` | Nom calculé à l'exécution : l'expression est conservée, propre à la routine |
| `family` | `data:mem:*.VALUES` | Famille d'objets de même suffixe ; utile pour les vues d'ensemble ; traitée automatiquement comme un hub (masquée par défaut dans les TreeGraph) |

Chaque accès porte son niveau (`resolution` de l'accès) : l'interface distingue « écrit l'objet X » de « écrit un objet de la famille X ».

### 3.6. Schéma SQLite

```sql
-- Contenu analysé
files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, lang, variant, sha256, size, encoding,
      parse_status, adapter, adapter_version, error)
inventory(file_id, lang, variant, confidence, decided_by)
nodes(id INTEGER PRIMARY KEY, uid TEXT UNIQUE, display_name, kind, subtype, lang,
      file_id, line_start, line_end, in_scope, attrs JSON)
conditions(id INTEGER PRIMARY KEY, expr TEXT UNIQUE)              -- gardes préprocesseur
call_sites(id INTEGER PRIMARY KEY, src_node, file_id, line, col, ref_kind, target_text,
           dst_node, resolution, confidence, origin, condition_id)  -- un site = une ligne
call_site_candidates(site_id, dst_node)                            -- cibles des sites ambigus
data_accesses(id INTEGER PRIMARY KEY, src_node, data_node, family_node, mode,
              key_kind, file_id, line, origin)
facts_cache(cache_key TEXT PRIMARY KEY, facts BLOB)                -- JSON canonique compressé (zlib)

-- Précalculs pour l'interface (étape Index)
edges(src, dst, kind, site_count, min_confidence, origins JSON, conditions JSON)
node_stats(node_id, fan_in, fan_out, fan_in_filtered, fan_out_filtered,
           impact_size, impact_size_filtered, is_noise, noise_reason)
file_edges(src_file, dst_file, kind, count)       -- TreeGraph fichiers
dir_edges(src_dir, dst_dir, kind, count)          -- regroupement par répertoire
search_fts                                        -- FTS5 : noms, chemins, commentaires d'en-tête

-- Traçabilité
plugins(name, type, version)
scan_runs(id, started_at, finished_at, root, git_rev, profile_version, profile_sha256,
          plugins JSON, stats JSON)

-- Plus tard
summaries(node_id, content_hash, model_id, prompt_version, text)   -- lot 15
layout_cache(key, layout_version, data JSON)                        -- lot 11
```

**Index** (créés **après** les insertions) : `call_sites(src_node)`, `call_sites(dst_node)`, `call_sites(file_id, line)`, `call_sites(resolution, target_text)`, `data_accesses(src_node)`, `data_accesses(data_node)`, `edges(src, kind)`, `edges(dst, kind)`, `nodes(file_id)`.

**Écriture et performance**

- **Analyse complète :** la base est construite dans un fichier temporaire (`<projet>.sqlite.tmp`), journal désactivé pendant la construction (`PRAGMA journal_mode=OFF`, `PRAGMA synchronous=OFF`), insertions groupées (`executemany` par lots de 50 000 lignes), index créés à la fin, puis `ANALYZE` et remplacement atomique du fichier : l'interface ne voit jamais une base à moitié écrite.
- **Ré-analyse incrémentale :** mode WAL (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`) ; l'interface continue de lire pendant l'écriture.
- **Volume :** de l'ordre du million de sites d'appel pour 15 000 fichiers. Une ligne par site, composée d'entiers, représente quelques dizaines de Mo, s'écrit en quelques secondes par insertions groupées, et se lit par index pour la navigation ligne par ligne de l'inspecteur.
- **Cache des faits :** clé = SHA-256 du fichier + SHA-256 de **tous les fichiers qu'il inclut** (récursivement) + nom et version de l'adaptateur + paramètres du profil qui influencent l'extraction (langage, variante, macros du préprocesseur, chemins d'inclusion). Contenu : JSON canonique compressé avec `zlib` (bibliothèque standard). **Jamais `pickle`** (risques de sécurité et d'incompatibilité entre versions).
- Le schéma porte un numéro de version ; une base d'une version antérieure est migrée ou ré-analysée.

### 3.7. Contrats des plugins et faits

```python
class LanguageAdapter(Protocol):
    name: str                      # "fortran", "python", "c", "cpp", "keywords:<langage>"
    version: str
    languages: list[str]           # langages de l'inventaire qu'il sait lire
    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts: ...
        # ctx : chemins d'inclusion, macros, délai maximal, noms connus comme tableaux

class Bridge(Protocol):
    name: str                      # "pybind11", "fortran_c", "prefix_calls", ...
    version: str
    languages: tuple[str, str]
    def link(self, symbols: SymbolTable, facts: Iterable[FileFacts],
             params: dict) -> Iterable[SiteResolution]: ...

class DomainPack(Protocol):
    name: str
    version: str
    def detect(self, repo: RepoInfo) -> float: ...           # 0..1
    def rules(self) -> PackRules: ...                        # rules.yaml chargé et validé
    def enrich(self, graph: GraphView) -> GraphPatch: ...    # optionnel

@dataclass
class SourceFile:
    path: str; lang: str; variant: str | None; encoding: str; text: str

@dataclass
class LocalSymbol:     # déclaration visible dans une routine (surtout Fortran)
    name: str
    role: str          # "array", "scalar", "dummy", "dummy_procedure", "external",
                       # "function", "intrinsic", "parameter"
    source: str        # "local", "include:<chemin>", "common:<bloc>", "module:<nom>"

@dataclass
class Definition:      # routine, type, module, donnée...
    uid: str; display_name: str; kind: str; subtype: str; name: str
    span: tuple[int, int]; signature: str | None; doc: str | None
    local_symbols: list[LocalSymbol]

@dataclass
class Reference:       # un site d'appel ou d'usage, non résolu à ce stade
    src: str; target_text: str
    kind: str          # "call", "maybe_call", "use", "include", ...
    line: int; col: int; args: list[ArgFact]     # arguments, avec valeur littérale si connue
    condition: str | None                        # garde préprocesseur

@dataclass
class IncludeRef:
    text: str; resolved_path: str | None; sha256: str | None

@dataclass
class FileFacts:
    path: str; lang: str; encoding: str; adapter: str; adapter_version: str
    definitions: list[Definition]
    references: list[Reference]
    data_accesses: list[DataAccess]              # COMMON, globales, INTENT...
    directives: list[Directive]                  # #ifdef...
    includes: list[IncludeRef]                   # pour la clé de cache et les déclarations
    errors: list[ParseError]
    used_fallback: bool
```

- Le langage de chaque fichier vient de l'inventaire (profil) ; l'adaptateur ne le devine pas.
- Les faits ont la même forme pour tous les langages : le cœur ne connaît que ce format.
- Les arguments littéraux (chaînes, constantes, valeurs obtenues par propagation simple des variables locales) sont conservés. C'est ce qui permet à un pack ou à une règle d'interpréter des appels particuliers (gestionnaire mémoire, macros) sans réanalyser le code.
- Les faits sont **triés** (par ligne, colonne, puis nom) avant d'être stockés : c'est une condition du déterminisme.

**Règle Fortran pour `nom(...)` dans une expression** (appliquée par l'adaptateur, puis par Link) :

1. `nom` déclaré comme tableau — localement, en argument, dans un bloc `COMMON`, dans un fichier inclus ou dans un module utilisé — → **accès à une donnée**, pas un appel ;
2. `nom` est une fonction intrinsèque Fortran (liste fixe : `sin`, `max`, `size`…) → site `external` (`ext:intrinsic:<nom>`), masqué par défaut ;
3. `nom` déclaré `EXTERNAL` ou comme fonction → site `call` ;
4. `nom` figure dans la liste `extraction.known_arrays` d'un pack (déclaration introuvable) → accès à une donnée ;
5. sinon → site `maybe_call`, tranché par Link : fonction définie dans le dépôt → appel ; tableau d'un module → donnée ; sinon site `ambiguous`, classé à part dans le diagnostic pour ne pas noyer les vrais non résolus.

### 3.8. Format des Domain Packs

Un pack est d'abord un fichier déclaratif `rules.yaml` ; du Python (`enrich`) ne s'ajoute que si le format ne suffit pas.

**Chargement :** `yaml.safe_load` uniquement, puis validation par un schéma JSON (`enrich/schemas/pack.schema.json`). Une clé inconnue, un type invalide ou une version de format inconnue font échouer le chargement avec un message qui indique le fichier, la clé et la valeur fautive. Les mêmes règles s'appliquent aux profils de langage (§3.9), aux règles de liaison et au profil d'analyse.

**Spécification du format, version 1**

| Clé | Type | Obligatoire | Sens précis |
| :--- | :--- | :--- | :--- |
| `pack` | texte | oui | Nom du pack (minuscules et `_`) |
| `version` | texte `MAJ.MIN` | oui | Version du pack |
| `format_version` | entier | oui | Version du format ; une version inconnue est refusée |
| `identifiers` | liste de textes | oui | Identifiants caractéristiques du code, interdits dans le cœur (§6.4) |
| `covers` | `{code: intervalle}` | non | Versions du code analysé couvertes, ex. `">=16,<18"` |
| `detect.any_path` | liste de chemins | non | Pack proposé si **au moins un** chemin existe |
| `detect.all_path` | liste de chemins | non | Pack proposé si **tous** les chemins existent ; si les deux clés sont données, les deux conditions doivent être vraies |
| `noise.hide` | liste de noms (motifs `*` admis) | non | Routines masquées par défaut (badge « +N », réaffichables) |
| `noise.optional` | liste de noms | non | Routines **proposées** au masquage, visibles par défaut |
| `noise.auto_detect_hubs` | `{min_fan_in, max_fan_out}` | non | Seuils de détection des hubs, proposés au masquage |
| `extraction.known_arrays` | liste de noms | non | Noms toujours traités comme des tableaux (jamais comme des appels) quand leur déclaration est introuvable |
| `memory_access[]` | objets (ci-dessous) | non | Appels à un gestionnaire mémoire → accès aux données |
| `dispatch[]` | `{routine, select_on, target_pattern}` | non | Chaque branche du `SELECT CASE` sur `select_on` → arête `dispatches` vers `target_pattern` (`{case}` = valeur de la branche, ex. `elem_{case:03d}`) |
| `catalogs[]` | `{glob, format, entry, target}` | non | Chaque entrée d'un fichier de configuration (`yaml`, `json`, `python`) → cible |
| `entry_points[]` | `{kind, glob, pattern, multiline, target, fallback_target}` | non | Points d'entrée ; `fallback_target` est utilisé si `target` n'existe pas dans le dépôt |
| `bridges[]` | objets (ci-dessous) | non | Liaisons entre langages |
| `tests[]` | `{kind, glob, uses_entry_points, coverage}` | non | Découverte des tests |
| `glossary` | chemin | non | Vocabulaire métier pour l'IA |

**`memory_access[]`** — `{routine, name_arg, mode_arg, modes, effect, object_key, local_prefix_pattern}` :

- soit `mode_arg` + `modes` (valeur littérale de l'argument → `reads` ou `writes`), soit `effect` (`creates` ou `destroys`) ;
- `object_key` : liste **ordonnée** de stratégies essayées dans l'ordre — `literal` (nom entièrement connu), `local_prefix` (nom qui commence par `local_prefix_pattern`, propre à la routine), `symbolic` (expression conservée), `family` (suffixe statique) ; l'accès est relié à l'objet le plus précis trouvé **et** à sa famille.

**`bridges[]`** — `{from, to, call_prefixes, name_transform, declaration_patterns, extension_modules}` :

- `call_prefixes` : essayés **du plus long au plus court** ; un appel `PREFIXE` + `NOM(...)` produit un site vers la cible obtenue en appliquant `name_transform` ;
- `name_transform` : liste ordonnée d'opérations parmi `strip_prefix` (par défaut, en premier), `lowercase`, `uppercase`, `append_underscore`, `strip_underscore` ;
- `declaration_patterns` : motifs qui **déclarent** une routine de l'autre langage (prototype, macro de déclaration). Ils créent des nœuds `binding`, **jamais des sites d'appel** ;
- `extension_modules` : modules compilés exposés à Python.

Toute règle de liaison s'accompagne de tests positifs **et négatifs** (identifiants qui ressemblent au préfixe sans en être, fixture `bridge_prefix_negative`).

```yaml
# Exemple fictif
pack: acme_solver
version: "0.1"
format_version: 1
identifiers: [mem_get, elem_dispatch, acme_core, FCALL_]
covers: { acme_solver: ">=3,<5" }
detect: { all_path: ["src/kernels/", "acme/"] }
noise:
  hide: [log_msg, check_err]
  optional: [get_property]
  auto_detect_hubs: { min_fan_in: 300, max_fan_out: 3 }
extraction:
  known_arrays: [rbuf, ibuf]
memory_access:
  - { routine: mem_get, name_arg: 1, mode_arg: 2, modes: { "R": reads, "W": writes },
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^TMP_" }
dispatch:
  - { routine: elem_dispatch, select_on: itype, target_pattern: "elem_{case:03d}" }
entry_points:
  - { kind: command, glob: "acme/commands/*.py",
      pattern: 'Command\(name="(?P<name>\w+)", routine="(?P<target>\w+)"\)',
      target: "f:{target}", fallback_target: "py:acme.commands.{name}" }
bridges:
  - { from: cpp, to: fortran, call_prefixes: ["FCALL_"], name_transform: [strip_prefix, lowercase] }
  - { from: cpp, to: fortran, declaration_patterns: ['FDECL\((?P<name>\w+)'] }
  - { from: python, to: cpp, extension_modules: [acme_core] }
tests:
  - { kind: regression_case, glob: "tests/cases/*.inp", uses_entry_points: true }
glossary: docs/glossary.md
```

Les **règles de liaison proposées par l'IA** utilisent exactement le format d'une entrée `bridges`, dans un fichier à part (`rules/r-<n>.yaml`) référencé par le profil.

### 3.9. Profils de langage par mots-clés

Pour un langage sans adaptateur natif, l'**adaptateur par mots-clés** (`extract/keywords/`) lit un profil qui ne contient que des listes de mots-clés et de marqueurs. C'est le cœur qui les transforme en règles d'extraction, de façon déterministe. Un profil peut être écrit à la main ou proposé par l'IA.

```yaml
# <projet>/rules/languages/acme_script.yaml — exemple fictif
language: acme_script
version: 1
format_version: 1
source: ai                    # ai | manual
status: approved              # proposed | approved | rejected
extensions: [".acs"]
case_sensitive: false
comments: { line: ["#"], block: [["/*", "*/"]] }
strings: ['"', "'"]
line_continuation: "\\"
definitions:
  - { keywords: ["proc", "function"], name: after_keyword, end_keywords: ["endproc", "endfunction"], kind: routine }
calls:
  - { keywords: ["run"], name: after_keyword }            # run nom(...)
  - { style: name_then_paren, only_known_names: true }    # nom(...) si nom est défini quelque part
includes:
  - { keywords: ["use"], target: after_keyword }
coverage:                     # mesurée, jamais supposée
  sample_files: 12
  definitions_recall: 0.97
  calls_precision: 0.93
evidence:
  document: "docs/acme_script_manual.pdf"                 # document technique fourni, s'il existe
  samples: ["scripts/a.acs", "scripts/b.acs"]
```

- **Portée limitée, assumée :** un profil de mots-clés est une extraction **heuristique**. Il ne résout ni les portées, ni les imbrications complexes, ni les surcharges. Ses liens ont la confiance `heuristic`.
- **Couverture mesurée :** un profil n'est jugé utilisable qu'avec une couverture mesurée sur une fixture ou un échantillon vérifié (bloc `coverage`) ; sinon l'interface l'affiche « non mesuré ».
- `only_known_names: true` évite de prendre n'importe quelle parenthèse pour un appel : seuls les noms définis dans le dépôt (ou déclarés externes) sont retenus.

### 3.10. API de requêtes (contrat entre le moteur, la ligne de commande et l'interface)

```python
CALL_PATH = {"calls", "bridges", "binds", "implements", "dispatches"}   # chemins d'exécution
FILE_DEPENDENCY = {"uses", "contains"}                                   # dépendances de fichiers

class GraphQuery:
    def __init__(self, db_path: Path, *, read_only: bool = True): ...
    def inventory(self) -> InventoryReport: ...
    def find(self, text: str, kinds: set[str] | None = None, limit: int = 50) -> list[NodeSummary]: ...
    def node(self, uid: str) -> NodeDetail: ...
    def callers(self, uid: str, *, hide_noise: bool = True) -> CallerReport: ...
        # CallerReport : count, file_count, items = [(caller, sites=[CallSite])]
    def callees(self, uid: str, *, hide_noise: bool = True) -> CalleeReport: ...
    def children(self, uid: str, *, direction: Direction, level: Level,
                 edge_kinds: set[str] = CALL_PATH, offset: int = 0, limit: int = 50,
                 hide_noise: bool = True) -> Page[TreeItem]: ...
        # direction : CALLERS ou CALLEES ; level : ROUTINE, FILE ou DIRECTORY
    def file_links(self, file_uid: str, *, direction: Direction) -> list[FileLink]: ...
    def call_sites(self, src_uid: str, dst_uid: str) -> list[CallSite]: ...
        # CallSite : file, line, col, condition, origin, confidence, resolution
    def paths(self, src_uid: str, dst_uid: str, *, edge_kinds: set[str] = CALL_PATH,
              k: int = 5, max_len: int = 15) -> list[Path]: ...
        # Path = étapes (uid, type d'arête, confiance, possible: bool) ; possible=True pour un aiguillage
    def impact(self, uid: str, *, edge_kinds: set[str] = CALL_PATH,
               max_depth: int | None = None) -> ImpactReport: ...
    def data_accesses(self, uid: str) -> list[DataAccessView]: ...   # avec niveau literal/symbolic/family
    def unresolved(self, *, group_by: str = "pattern", include_ambiguous: bool = False,
                   limit: int = 50) -> list[SiteGroup]: ...
    def source(self, file_uid: str, start: int, end: int) -> SourceExcerpt: ...
        # SourceExcerpt.stale = True si le fichier sur disque a changé depuis l'analyse
    def scan_health(self) -> ScanHealth: ...
```

- Toutes les listes sont **paginées** (`offset`, `limit`) et triées de façon stable.
- Les requêtes de base (`callers`, `callees`, `children`, `file_links`) sont de simples requêtes SQL indexées sur les tables précalculées : aucune ne charge le graphe en mémoire.
- `paths` et `impact` utilisent explicitement un ensemble de types d'arêtes (chemin d'exécution, ou dépendance de fichiers) ; ils parcourent le graphe en largeur avec des bornes (profondeur, nombre de nœuds), s'arrêtent proprement à la limite et le signalent.
- `source` compare l'empreinte du fichier sur disque à celle de l'analyse (taille et date d'abord, puis SHA-256 si besoin) : une ligne affichée correspond toujours à la preuve qui a servi à construire le lien, ou l'interface prévient qu'elle ne correspond plus.
- La ligne de commande et l'interface utilisent exactement cette API : ce qui est testé en ligne de commande est ce que l'interface affiche.

### 3.11. Application de bureau

**Fenêtre principale**

| Zone | Contenu |
| :--- | :--- |
| Barre du haut | Choix du projet, champ de recherche, bouton « Analyser », filtres (masquer les utilitaires, confiance minimale, masquer les liens issus de l'IA, masquer les sites ambigus) |
| Gauche | Explorateur de fichiers du dépôt (avec le langage de chaque fichier) |
| Centre (onglets) | Inventaire · TreeGraph fonctions · TreeGraph fichiers · Liste arborescente (version texte du TreeGraph) |
| Droite | Inspecteur de code ; en dessous, panneau Appelants (N) / Appelés (M) |
| Barre d'état | Analyse en cours, santé de l'analyse, filtres actifs |

**Composants Qt**

- Listes et arbres texte : `QAbstractItemModel` paresseux (`canFetchMore` / `fetchMore`) qui demande les enfants par pages de 50 à `GraphQuery.children`.
- TreeGraph : `QGraphicsView` + `QGraphicsScene` ; un `NodeItem` par nœud, un `EdgeItem` par lien ; la mise en page est calculée par `layout/` dans un thread, puis appliquée.
- Inspecteur : `QPlainTextEdit` en lecture seule + `QSyntaxHighlighter` par langage (règles fournies par l'adaptateur ; pour un profil de mots-clés, coloration de ses mots-clés). Si `SourceExcerpt.stale` est vrai : bandeau « Ce fichier a changé depuis l'analyse » et bouton « Ré-analyser ».
- Vue d'un chemin : chaque étape affiche son type (appel, pont, aiguillage) ; les étapes d'aiguillage sont marquées « possible ».
- Travaux en arrière-plan : `QThreadPool` pour les requêtes ; `QProcess` pour l'inventaire, l'analyse et l'IA.
- Réglages : `QSettings` au format INI, dans le dossier de données (§3.14).

**Parcours à l'ouverture d'un dossier :** inventaire → affichage des langages et de leur couverture → si des éléments manquent et que l'IA est disponible, proposition « Compléter avec l'IA » → analyse → recherche d'une routine → panneau Appelants rempli automatiquement → clic sur un appelant → inspecteur positionné sur la ligne de l'appel → « Ouvrir dans le TreeGraph ».

### 3.12. Stratégies d'allègement graphique (CPU seul)

1. **Jamais le graphe entier dans l'interface :** uniquement ce qui est affiché, demandé à la base.
2. **Précalculs pendant l'analyse :** nombres d'appelants et d'appelés (bruts et filtrés), taille d'impact, liens entre fichiers et entre répertoires (`file_edges`, `dir_edges`).
3. **Pagination :** 50 enfants par dépliage ; au-delà, un nœud « +N autres » qui se déplie à la demande.
4. **Plafond de nœuds dessinés** (300 par défaut) : au-delà, l'application propose de passer au niveau fichier ou répertoire.
5. **Niveaux d'agrégation :** répertoire → fichier → routine ; on descend d'un niveau par double-clic.
6. **Hubs et familles de données masqués par défaut** dans les TreeGraph, avec badge « +N ».
7. **Mise en page en arbre** (algorithme linéaire, déterministe), calculée dans un thread et mise en cache ; les nœuds déjà placés ne bougent pas lors d'un dépliage.
8. **Niveau de détail selon le zoom :** sous un seuil, les étiquettes ne sont plus dessinées et les nœuds deviennent de simples rectangles.
9. **Rendu sobre sur les grandes vues :** pas d'anticrénelage au-delà de 200 éléments, arêtes en segments droits, cache de rendu des éléments (`ItemCoordinateCache`).
10. **Analyse discrète :** processus d'analyse en priorité basse, nombre de processus de travail = cœurs − 1, faits écrits dans la base au fil de l'eau.
11. **Analyse partielle :** possibilité de limiter l'analyse détaillée à certains répertoires (§3.3).

### 3.13. IA locale (extension Pro)

**Exécution :** sous-processus `cgs ai-worker` qui charge un modèle GGUF avec `llama-cpp-python`, sur CPU (threads = cœurs − 1), avec un contexte de 4 à 8 k tokens. Dialogue en JSON sur l'entrée et la sortie standard ; réponses envoyées au fil de l'eau ; température nulle et graine fixe. La bibliothèque d'inférence choisit au démarrage les instructions disponibles sur le processeur (§2.2).

**Modèles :** uniquement sous licence Apache 2.0 ou MIT, listés dans `models.lock` (fichier, empreinte SHA-256, licence). Candidats de départ pour CPU : Qwen2.5-Coder-1.5B-Instruct (Apache 2.0) et Phi-4-mini-instruct (MIT), quantifiés en Q4. Le choix final se fait sur le banc d'évaluation du lot 13.

**Rôle 1 — Identifier les langages inconnus (lot 13)**

- Entrée, par groupe de fichiers non reconnus : extension, nombre de fichiers, début de trois fichiers, liste des langages déjà couverts.
- Sortie (contrainte par le schéma) : nom du langage, adaptateur existant à utiliser, ou demande de profil de mots-clés ; justification courte.
- Contrôle automatique : si un adaptateur existant est proposé, il doit lire les fichiers d'exemple sans erreur et y trouver des définitions.

**Rôle 2 — Définir les mots-clés manquants (lot 13)**

La boucle de complétion :

1. Une première analyse est faite avec le profil courant.
2. Le diagnostic (`GraphQuery.unresolved`, `scan_health`) résume ce qui manque, de façon déterministe : langages sans adaptateur ; sites non résolus regroupés par motif (même préfixe, même langage source, mêmes fichiers), avec quelques lignes de code d'exemple ; fichiers sans aucune définition trouvée.
3. L'IA reçoit ce résumé (et, s'il existe, le document technique fourni par l'utilisateur) et remplit un gabarit : profil de langage par mots-clés (§3.9) ou règle de liaison (format `bridges`, §3.8).
4. **Contrôles automatiques**, en rejouant les étapes Link à Index sur les faits déjà extraits (rapide) :

| Contrôle | Seuil (réglable) |
| :--- | :--- |
| Fichier conforme au schéma | Obligatoire |
| Gain : sites non résolus du groupe visé désormais résolus | ≥ 50 % |
| Pas d'explosion : nouveaux sites par ligne de code | Sous un plafond fixé |
| Pas de régression : arêtes existantes inchangées, fixtures toujours au vert | Obligatoire |
| Cibles plausibles : nouveaux sites vers des définitions existantes | ≥ 90 % |
| Stabilité : mêmes taux sur un second échantillon de fichiers | Écart < 10 points |
| Tests négatifs : la règle ne s'applique pas aux exemples qui ressemblent au motif sans en être | Obligatoire |

5. **Adoption**
   - **Mode par défaut — validation en un clic :** l'interface montre l'aperçu des changements (nombre de liens ajoutés et retirés, avec quelques exemples dans le code) ; l'utilisateur approuve ou refuse.
   - **Mode automatique**, activable par projet : adoption dès que les contrôles passent, liens marqués « IA ».
   - Le mode automatique ne devient le réglage par défaut que si le banc d'évaluation montre, sur des corpus de référence, une précision des règles adoptées d'au moins 98 % (borne basse ≥ 95 %).
   - Une proposition qui échoue aux contrôles est **rejetée**, avec la raison affichée.
6. Au plus 3 itérations ; la boucle s'arrête aussi quand plus rien ne progresse.
7. L'analyse finale est relancée avec le profil validé : elle est déterministe.

**Rôle 3 — Expliquer (lot 15)**

- Contexte assemblé de façon déterministe, dans un budget de tokens : code de la routine, liste des appelants, résumés des appelés, données lues ou écrites, glossaire du pack.
- Citations obligatoires (`[f:assemble_matrix L120]`) ; l'interface vérifie que chaque identifiant cité existe et signale ceux qui n'existent pas.
- Les chiffres (nombre d'appelants, impact) viennent toujours des requêtes, jamais du modèle.
- Résumés précalculés des feuilles vers la racine, en tâche de fond, mis en cache par empreinte du code.

**Tests :** un **modèle factice** (réponses enregistrées) permet de tester toute la chaîne en intégration continue, de façon déterministe ; le vrai modèle est testé sur la machine de développement, sur le banc d'évaluation.

### 3.14. Version portable (clé USB)

```text
CodeGraph-Sci-1.0-linux-x86_64/          (ou -windows-x64)
├── CodeGraph-Sci                         application de bureau (CodeGraph-Sci.exe sous Windows)
├── cgs                                   ligne de commande (cgs.exe sous Windows)
├── _internal/                            Python embarqué, Qt, bibliothèques
├── packs/                                packs installés (rules.yaml)
├── models/                               édition IA : modèle .gguf + sa licence + provenance.json
├── licenses/                             licences et avis de tous les composants, offre de sources LGPL
├── data/                                 projets et réglages (mode portable)
└── LISEZ-MOI.txt
```

- **Deux éditions :** sans IA (environ 300 Mo, à mesurer au lot 0) et avec IA (1 à 3 Go de plus selon le modèle).
- **Deux exécutables** partageant le même dossier `_internal/`, produits par une seule spécification PyInstaller : l'application de bureau et la ligne de commande.
- **Emplacement des données :** par défaut sur le disque local (`~/.codegraph-sci/` sous Linux, `%LOCALAPPDATA%\CodeGraph-Sci\` sous Windows), car une base SQLite est lente sur clé USB. Option « mode portable » qui écrit dans `data/`, à côté de l'application.
- **Construction :** `tools/build_portable.py` (PyInstaller) produit le dossier, une archive et son empreinte SHA-256. Linux : conteneur à glibc 2.28 (§2.2) ; Windows : machine Windows de l'intégration continue. Le réseau n'est utilisé qu'au moment de la construction ; le dossier final ne fait aucun accès réseau.
- **Modèle inclus :** l'édition IA contient le fichier du modèle et le texte de sa licence, comme l'exigent Apache 2.0 et MIT (§7).

### 3.15. Choix techniques et dépendances

| Composant | Usage | Licence |
| :--- | :--- | :--- |
| Python 3.12 | Langage unique de l'application | PSF |
| PySide6 (Qt 6) | Interface de bureau | LGPL-3.0 (obligations détaillées au §7) |
| py-tree-sitter + grammaires Fortran, C, C++, Python | Parseurs (Python 2 : repli sur la grammaire tree-sitter) | MIT (roue `tree-sitter-fortran` à vérifier ; sinon `tree-sitter-language-pack` ou compilation à la construction) |
| `ast` (bibliothèque standard) | Parseur Python 3 | PSF |
| sqlite3 + FTS5, `zlib`, `json` (bibliothèque standard) | Base du projet, recherche plein texte, cache compressé | Domaine public / PSF |
| Algorithmes de graphe maison (`algo/`) | Tarjan itératif, condensation, ensembles de bits, parcours bornés | — (code du projet ; NetworkX n'est plus nécessaire) |
| PyYAML (`safe_load` uniquement), jsonschema | Profils, packs et leur validation stricte | MIT |
| fparser, LFortran *(candidats du banc Fortran, lot 4)* | Parseurs Fortran alternatifs | BSD-3 |
| fxtran *(hors distribution par défaut)* | Parseur Fortran, seulement en outil externe après revue de licence | GPL-3.0 |
| PyInstaller | Construction du dossier portable | GPL-2.0 avec exception autorisant la distribution d'applications propriétaires |
| llama-cpp-python *(lot 13)* | Exécution du modèle sur CPU | MIT |
| pypdf *(lot 13)* | Lecture des documents techniques fournis | BSD-3 |
| cryptography *(lot 16)* | Clés de licence Ed25519 | Apache-2.0 / BSD |
| pytest, pytest-qt, pytest-socket, hypothesis, ruff, mypy, import-linter | Développement et tests | MIT / BSD / MPL-2.0 (hypothesis) |

Toute nouvelle dépendance passe par cette liste et par le contrôle de licences (lot 16).

### 3.16. Structure du dépôt

```text
codegraph-sci/                         dépôt de développement (privé jusqu'à la publication)
├── AGENTS.md                          consignes pour l'agent (Annexe C)
├── CHANGELOG.md
├── pyproject.toml
├── requirements.lock                  dépendances épinglées avec empreintes
├── models.lock                        modèles autorisés (Apache 2.0 / MIT)
├── docs/
│   ├── architecture.md                ce document
│   ├── strategie_licence.md
│   └── packs/<code>.md                un fichier par code analysé
├── src/
│   ├── codegraph_sci/                 cœur (publié sous PolyForm NC)
│   │   ├── core/
│   │   ├── algo/                      tarjan.py, closure.py, paths.py
│   │   ├── inventory/                 extensions.yaml, signatures, contexte, profil
│   │   ├── extract/                   fortran/  python/  c/  cpp/  keywords/
│   │   ├── link/                      symbols.py, bridges/
│   │   ├── enrich/                    moteur de packs, schemas/, generic_noise/, generic_fortran/
│   │   ├── store/                     schema.sql, writer.py, reader.py, cache.py
│   │   ├── query/
│   │   ├── layout/
│   │   ├── audit/                     baseline, diff, sample, recall_sample, invariants
│   │   ├── scan.py
│   │   ├── cli.py
│   │   └── ui/                        app.py, main_window.py, models/, views/, workers.py
│   └── codegraph_sci_pro/             extensions Pro (dépôt privé à terme)
│       ├── packs/<code>/
│       ├── ai/                        worker.py, identify.py, complete.py, explain.py, prompts/
│       └── license/
├── tests/
│   ├── unit/
│   ├── fixtures/<nom>/                src/ + expected_inventory.json + expected_graph.json
│   ├── synthetic/generate.py
│   ├── corpus/<code>/                 manifest.yaml + expectations.yaml + reference_sample.yaml
│   ├── ai/                            réponses enregistrées du modèle factice
│   ├── robustness/                    fichiers malformés, chemins difficiles, fuzzing
│   ├── ui/                            pytest-qt
│   └── portable/                      contrôles du dossier portable (réseau, ports, glibc)
├── tools/
│   ├── check.py                       ruff + mypy + import-linter + pytest (réseau bloqué)
│   └── build_portable.py
└── packaging/
    ├── codegraph_sci.spec
    ├── linux-glibc228.Containerfile
    └── licenses/
```

---

## 4. Plan de réalisation par lots

### 4.0. Mode d'emploi

**Règles communes à tous les lots (« définition de terminé »)**

- Les tests du lot passent, ainsi que `python tools/check.py` (ruff, mypy strict, import-linter, pytest avec réseau bloqué par pytest-socket).
- Aucune dépendance hors de la liste du §3.15 ; aucun accès réseau ; aucun identifiant propre à un code analysé dans le cœur.
- Si un contrat (§3.5 à §3.10) change, ce document est mis à jour dans le même lot.
- Une ligne est ajoutée au `CHANGELOG.md`.

**Consigne type à donner à l'agent de développement**

```text
Lis AGENTS.md, puis docs/architecture.md (§3 et le lot N du §4).
Réalise uniquement le lot N « <titre> ».
Respecte les contrats des §3.5 à §3.10 et les règles de dépendance du §3.4.
Le lot est terminé quand ses tests de validation et `python tools/check.py` passent.
Ne commence pas le lot suivant.
```

### Lot 0 — Squelette portable

- **Objectif :** lever le verrou V2 avant toute fonctionnalité.
- **À produire :** structure du dépôt (§3.16), `pyproject.toml`, `tools/check.py`, contrats `import-linter` ; commandes `cgs --version` et `cgs selftest` ; fenêtre PySide6 vide avec « À propos » ; `tools/build_portable.py`, spécification PyInstaller à deux exécutables, conteneur de construction Linux à glibc 2.28 ; intégration continue Linux + Windows.
- **`cgs selftest` vérifie :** chargement de Qt, d'une grammaire tree-sitter, de SQLite avec FTS5 ; écriture dans le dossier de données ; jeux d'instructions du processeur ; absence de tout accès réseau.
- **Tests de validation :** `tools/check.py` passe ; le dossier construit, copié sur une clé USB, démarre sur une machine (ou machine virtuelle) **sans réseau** sous Ubuntu 22.04, Ubuntu 24.04 et Windows 10/11 (et, si possible, Rocky Linux 8) ; `cgs selftest` passe dans tous les cas ; sous Linux, l'application démarre dans un espace de noms sans réseau (`unshare -n`).
- **Dépend de :** —.

### Lot 1 — Modèle de données et stockage

- **Objectif :** le format commun à tout le reste.
- **À produire :** `core/` (identités du §3.5, faits du §3.7, type du profil d'analyse, numéros de version) ; `store/` (schéma du §3.6 avec `call_sites`, écriture groupée dans un fichier temporaire puis remplacement atomique, index créés à la fin, mode WAL pour l'incrémental, cache JSON compressé) ; export canonique en JSON trié (`cgs export json`).
- **Tests de validation :** aller-retour faits → base → export sans perte ; deux écritures des mêmes faits donnent un export identique ; une analyse interrompue ne laisse jamais une base à moitié écrite ; refus propre d'une base de version inconnue ; écriture d'un million de sites synthétiques dans le temps cible (mesuré et consigné).
- **Dépend de :** lot 0.

### Lot 2 — Inventaire des langages et profil d'analyse

- **Objectif :** savoir, avant toute analyse, quels langages contient le dépôt et lesquels sont couverts.
- **À produire :** `inventory/` (§3.2) : parcours du dépôt, détection des binaires, table des extensions configurable, signatures de contenu, règles de contexte (`.h`, `.inc`), chemins d'inclusion, regroupement des fichiers non reconnus, rapport de couverture ; lecture et écriture de `analysis_profile.yaml` (chargement sûr, schéma strict) ; commande `cgs inventory <dossier>` (tableau ou JSON) ; fixture `inventory_mixed` (§5.2).
- **Tests de validation :** sur `inventory_mixed`, chaque fichier reçoit exactement le langage et la variante attendus (y compris `.h` en C et en C++, `.inc` Fortran, fichier sans extension avec ligne `#!`, fichier binaire ignoré, extension inconnue regroupée, lien symbolique en boucle signalé) ; deux inventaires du même dépôt donnent le même profil ; inventaire du dépôt synthétique (§5.3) en moins d'une minute.
- **Dépend de :** lot 1.

### Lot 3 — Mini-codes de référence (avant les extracteurs)

- **Objectif :** écrire les réponses attendues avant le code qui doit les trouver, pour les quatre langages et leur mélange.
- **À produire :** les fixtures du §5.2 marquées « lot 3 », chacune avec `src/`, `expected_inventory.json` et `expected_graph.json` (sites d'appel compris) écrits à la main ; générateur de dépôt synthétique multi-langages (§5.3).
- **Tests de validation :** chaque fichier attendu respecte son schéma ; l'inventaire (lot 2) de chaque fixture correspond à `expected_inventory.json` ; le générateur produit le même dépôt pour la même graine.
- **Dépend de :** lot 2.

### Lot 4 — Adaptateur Fortran

- **Objectif :** produire les faits d'un fichier Fortran.
- **À produire :**
  - d'abord un **banc comparatif** des parseurs Fortran sous licence permissive (tree-sitter-fortran, fparser, LFortran) sur les fixtures et sur un échantillon de fichiers réels du cas de test (format fixe, préprocesseur compris) : taux d'échec, temps, exactitude des définitions et des sites ; le parseur principal est choisi d'après ce banc et le choix consigné au §8 ;
  - puis `extract/fortran/` : décodage (UTF-8, sinon Latin-1, consigné) ; formats fixe et libre ; préprocesseur (branches `#ifdef` conservées avec leur condition, `#include` résolus par les chemins d'inclusion) ; **symboles locaux** de chaque routine (tableaux, arguments, `EXTERNAL`, `COMMON`, déclarations des fichiers inclus) ; règle `nom(...)` du §3.7 avec la liste des fonctions intrinsèques ; **extracteur à motifs indépendant**, utilisé en repli et pour la double extraction ; délai maximal par fichier.
- **Tests de validation :** pour chaque fixture Fortran, les faits produits correspondent exactement aux attendus (définitions, symboles locaux, sites, lignes, colonnes, conditions) ; dans `fortran_arrays_includes`, aucun tableau déclaré dans un fichier inclus ou un `COMMON` ne produit de site d'appel, et les intrinsèques sont classées `external` ; un fichier volontairement illisible bascule sur le repli sans interrompre l'analyse ; le rapport du banc est consigné.
- **Dépend de :** lot 3.

### Lot 5 — Adaptateurs Python, C et C++

- **Objectif :** couvrir les autres langages du premier cas de test.
- **À produire :** `extract/python/` (`ast` pour Python 3, repli tree-sitter pour Python 2 ou les fichiers invalides) ; `extract/c/` et `extract/cpp/` (tree-sitter, expansion partielle des macros, extracteur à motifs de repli) ; identités du §3.5 (signatures C++, fonctions `static` qualifiées par fichier) ; candidats multiples pour les appels de surcharges non tranchables.
- **Tests de validation :** pour chaque fixture Python, C et C++, les faits produits correspondent exactement aux attendus ; dans `cpp_overloads`, deux surcharges ont deux identités distinctes et un appel non tranchable produit un site `ambiguous` avec ses deux candidats ; deux fonctions `static` homonymes restent distinctes ; un fichier Python 2 est lu par le repli et signalé.
- **Dépend de :** lot 3.

### Lot 6 — Link, Index et commande `cgs scan`

- **Objectif :** passer d'un dossier de code multi-langages à une base complète.
- **À produire :** `link/` (table de symboles par langage — insensible à la casse pour le Fortran —, résolution des sites, tranchage des `maybe_call`, interfaces génériques, symboles externes et intrinsèques, index léger des définitions hors périmètre et état `out_of_scope`) ; `algo/` (Tarjan itératif, condensation, taille d'impact par ensembles de bits, parcours bornés) ; étape Index (arêtes agrégées, `node_stats`, `file_edges`, `dir_edges`, FTS5) ; `scan.py` (lecture du profil, parallélisme, délai par fichier, cache avec clé incluant les fichiers inclus, progression en JSON) ; commande `cgs scan <dossier>`.
- **Tests de validation :** chaque fixture, y compris `mini_hybrid` sans les ponts, donne un graphe et des sites exactement égaux à son `expected_graph.json` ; deux analyses successives donnent un export identique ; une ré-analyse sans modification ne ré-extrait aucun fichier ; modifier un fichier n'en fait ré-extraire qu'un, **modifier un fichier inclus fait ré-extraire tous ceux qui l'incluent** ; `partial_scope` : les appels vers l'extérieur du périmètre sont `out_of_scope`, pas `unresolved` ; `robustness` : aucun fichier ne bloque l'analyse ; le dépôt synthétique est analysé dans le temps cible (§1.3), et la taille d'impact calculée sur 15 000 routines dans un temps et une mémoire consignés.
- **Dépend de :** lots 4 et 5.

### Lot 7 — Validation sur un code réel (verrou V1, point d'arrêt)

- **Objectif :** prouver, sans compilateur, que l'inventaire et le graphe de chaque langage sont justes à l'échelle d'un code réel.
- **À produire :** `audit/` et les commandes `cgs audit inventory` (cohérence de l'inventaire), `cgs audit baseline` (référence textuelle), `cgs audit diff` (double extraction), `cgs audit sample` (échantillon de précision stratifié, fiche à vérifier, une touche par lien), `cgs audit recall-sample` (échantillon de rappel), `cgs audit invariants`, `cgs audit report` (métriques du §2.1 avec bornes de confiance) ; enregistrement des vérifications dans `reference_sample.yaml` et rejeu automatique ; manifeste et attentes du **corpus de démarrage** n°1 (§5.4).
- **Tests de validation :** les critères du §2.1 sont atteints sur le corpus de démarrage n°1, pour chacun de ses langages ; le rejeu de `reference_sample.yaml` passe automatiquement. Sinon : plan B (§2.1), puis nouvelle mesure.
- **Point d'arrêt :** tant que ces critères ne sont pas atteints, on ne commence pas les lots d'interface (10 et suivants).
- **Dépend de :** lot 6.

### Lot 8 — Ponts inter-langages

- **Objectif :** suivre un appel d'un langage à l'autre.
- **À produire :** ponts `python_extension`, `pybind11`, `fortran_c` (décoration des noms, `BIND(C)`), `prefix_calls` (préfixes du plus long au plus court, `name_transform` explicite, déclarations distinctes des appels, §3.8), `external_symbols` ; fixtures `bridge_pybind11`, `bridge_fortran_c` et `bridge_prefix_negative` ; groupe « ponts » ajouté à l'échantillon de précision.
- **Tests de validation :** chaque fixture de pont donne ses sites attendus ; `bridge_prefix_negative` ne produit aucun faux lien ; une macro de déclaration crée un nœud `binding` et aucun site d'appel ; dans `mini_hybrid`, le chemin Python → C++ → C → Fortran est retrouvé et les sites non résolus tombent à zéro ; précision des ponts conforme au §2.1 sur le corpus de démarrage.
- **Dépend de :** lot 6.

### Lot 9 — API de requêtes et ligne de commande

- **Objectif :** répondre aux questions du §1.1 sans interface.
- **À produire :** `query/` (§3.10, avec types d'arêtes explicites, chemins détaillés, contrôle de fraîcheur des sources) ; commandes `cgs callers <routine>` (question par défaut : nombre + liste avec fichiers et lignes), `cgs callees`, `cgs file-links`, `cgs path`, `cgs impact`, `cgs find`, `cgs data`, `cgs unresolved`, `cgs health` ; sorties en tableau ou en JSON.
- **Tests de validation :** réponses exactes sur toutes les fixtures ; un chemin traversant un aiguillage marque l'étape « possible » ; un fichier modifié après l'analyse est signalé périmé par `source` ; temps conformes au §1.3 sur le corpus de démarrage et sur le dépôt synthétique ; `paths` et `impact` s'arrêtent proprement à leurs bornes.
- **Dépend de :** lots 7 et 8.

### Lot 10 — Application de bureau : inventaire, recherche, appelants, inspecteur

- **Objectif :** la question par défaut, dans une fenêtre, sur un dépôt multi-langages.
- **À produire :** fenêtre principale (§3.11) ; création d'un projet, inventaire et analyse en sous-processus, avec progression et annulation ; vue Inventaire (avec forçage d'un langage et exclusion d'un groupe de fichiers, enregistrés dans le profil) ; recherche ; panneau Appelants / Appelés ; inspecteur de code avec bandeau « fichier modifié » ; explorateur de fichiers ; liste arborescente paresseuse ; panneau Santé de l'analyse (avec les métriques du lot 7).
- **Tests de validation :** tests pytest-qt des modèles ; scénarios S1, S2, S7, S8 et S10 du §5.6 ; l'interface reste réactive pendant l'analyse du corpus de démarrage.
- **Dépend de :** lot 9.

### Lot 11 — TreeGraph fichiers et fonctions

- **Objectif :** les deux vues dessinées.
- **À produire :** `layout/tree.py` (mise en page en arbre, déterministe) ; vue TreeGraph (`QGraphicsView`) dans les deux sens (appelés, appelants) et aux niveaux routine, fichier et répertoire ; couleur par langage ; pagination « +N », marques « ↺ déjà vu », hubs et familles de données masqués par défaut, niveaux de détail, cache de mise en page.
- **Tests de validation :** la même entrée donne les mêmes positions ; dépliage < 200 ms ; 300 nœuds affichés de façon fluide sur la machine de référence ; scénarios S3, S4 et S5.
- **Dépend de :** lot 10.

### Lot 12 — Packs, profils de langage par mots-clés, filtrage du bruit

- **Objectif :** accueillir la connaissance propre à chaque code et les langages sans adaptateur natif.
- **À produire :** `enrich/` : schémas JSON du §3.8 (pack, règle de liaison, profil de langage, profil d'analyse), chargement sûr et messages d'erreur précis ; pack `generic_noise` (détection des hubs) ; pack `generic_fortran` (COMMON, variables de module, `INTENT`) ; accès aux données à trois niveaux (§3.5) ; `extract/keywords/` : adaptateur par mots-clés avec mesure de couverture (§3.9) ; badge « +N utilitaires masqués » et filtre « liens issus de l'IA » dans l'interface ; test d'isolation (§6.4).
- **Tests de validation :** la fixture `pack_acme` donne les accès aux données (avec leur niveau) et les aiguillages attendus ; un pack contenant une clé inconnue, un mauvais type ou une balise YAML d'objet Python est refusé avec un message précis ; la fixture `keywords_language`, avec un profil écrit à la main, donne son graphe attendu et sa couverture mesurée ; sur le corpus de démarrage, les utilitaires connus sont proposés comme hubs ; test d'isolation au vert.
- **Dépend de :** lot 11.

### Lot 13 — IA : identification des langages et complétion des mots-clés

- **Objectif :** que l'IA identifie ce que l'inventaire ne reconnaît pas et définisse elle-même les mots-clés manquants, sans casser le déterminisme ni la justesse.
- **À produire :** `cgs ai-worker` (sous-processus, JSON sur entrée/sortie standard, génération contrainte par le schéma, choix des instructions CPU au démarrage) ; rôle 1 (identification) et rôle 2 (boucle de complétion) du §3.13, avec leurs contrôles automatiques, l'aperçu des changements, la validation en un clic, le mode automatique optionnel et l'écriture dans le profil ; lecture des documents techniques fournis (texte, Markdown, PDF) ; vue « Propositions de l'IA » ; commande `cgs complete` ; modèle factice et réponses enregistrées pour les tests ; banc d'évaluation des modèles candidats, qui mesure aussi la précision des règles adoptées.
- **Tests de validation :**
  - avec le modèle factice (intégration continue) : la chaîne complète produit exactement le profil attendu ; une proposition qui échoue à un contrôle, y compris aux tests négatifs, est rejetée ; l'aperçu montre exactement les liens ajoutés et retirés ; deux analyses avec le même profil donnent le même graphe ; aucun port réseau ouvert ;
  - avec le vrai modèle (machine de développement) : sur `unknown_extension`, le langage est identifié ; sur `keywords_language` sans profil, le profil proposé reproduit au moins 90 % des arêtes attendues ; sur `bridge_unknown_prefix`, le préfixe de liaison est trouvé et les sites non résolus baissent d'au moins 80 % ; chaque appel au modèle prend moins de 60 s sur la machine de référence ; l'IA démarre sur un processeur sans AVX2.
- **Dépend de :** lot 12.

### Lot 14 — Pack du cas de test n°1

- **Objectif :** valider le cœur sur un code réel complet.
- **À produire :** le pack décrit dans `docs/packs/<code>.md` (règles, éventuel `enrich.py`) ; attentes du **corpus complet** n°1 (§5.4) ; comparaison entre les règles de liaison écrites à la main et celles proposées par l'IA (lot 13) sur ce code.
- **Tests de validation :** toutes les attentes des corpus de démarrage et complet passent ; aucune régression sur les fixtures ; test d'isolation au vert ; rapport de comparaison IA / main consigné.
- **Dépend de :** lot 13.

### Lot 15 — IA : explications

- **À produire :** assemblage du contexte (§3.13, rôle 3) ; vérification des citations ; résumés en tâche de fond ; panneau IA dans l'interface ; extension du banc d'évaluation (30 à 50 routines annotées).
- **Tests de validation :** 100 % des identifiants cités vérifiés ; premiers mots en moins de 15 s et réponse complète en moins de 60 s sur la machine de référence ; scores du banc consignés pour chaque modèle candidat.
- **Dépend de :** lot 13.

### Lot 16 — Édition Pro, conformité des licences et version finale

- **À produire :**
  - séparation du paquet `codegraph_sci_pro` (dépôt privé, code compilé) ; clé de licence Ed25519 (voir `docs/strategie_licence.md`) ;
  - **conformité, comme tâche explicite** : contrôle automatique des licences des dépendances ; inventaire des composants (SBOM) ; dossier `licenses/` complet (textes de licence et avis de chaque composant embarqué, `NOTICE` des composants Apache 2.0, licence du modèle) ; obligations LGPL de Qt/PySide6 (§7) ; vérification qu'aucun outil GPL n'est embarqué par défaut ; revue des extraits de codes analysés présents dans les démonstrations ;
  - éditions portables avec et sans IA ; signature des exécutables Windows.
- **Tests de validation :** installation sur machines vierges sans réseau (Ubuntu 22.04 et 24.04, Windows 10 et 11, et si possible Rocky Linux 8) ; aucun trafic réseau ni port à l'écoute pendant l'analyse, l'utilisation de l'interface et l'exécution du modèle, vérifié sur l'application distribuée ; l'absence ou l'expiration de la licence ne bloque jamais le cœur ; liste de conformité entièrement cochée.
- **Dépend de :** lots 14 et 15.

---

## 5. Stratégie de test

### 5.1. Niveaux de tests

| Niveau | Contenu | Quand |
| :--- | :--- | :--- |
| Unitaires | Fonctions isolées (détection de langage, normalisation des noms, décodage, algorithmes de graphe, mise en page…) | À chaque modification |
| Fixtures | Mini-dépôts à inventaire, graphe et sites attendus exacts (§5.2) | À chaque modification |
| Robustesse | Fichiers malformés, très volumineux, chemins difficiles, données aléatoires (fuzzing) | À chaque modification des adaptateurs |
| Synthétique | Dépôt multi-langages généré de grande taille (§5.3) | Tests de performance, à chaque lot concerné |
| IA (modèle factice) | Chaîne d'identification et de complétion avec réponses enregistrées | À chaque modification des lots 13 et 15 |
| IA (vrai modèle) | Banc d'évaluation et fixtures IA | Sur la machine de développement, à chaque changement de modèle ou de gabarit |
| Corpus réels | Cas de test, attentes partielles et échantillons de référence (§5.4) | Régulièrement, et à la fin des lots 7, 8, 14 et 16 |
| Interface | Modèles Qt et scénarios utilisateur (§5.6) | À chaque lot d'interface |
| Application distribuée | Dossier construit, sur machines vierges sans réseau, contrôle du réseau et des ports | Lots 0 et 16, puis à chaque version |

### 5.2. Catalogue des fixtures

| Fixture | Ce qu'elle vérifie | Lot |
| :--- | :--- | :--- |
| `inventory_mixed` | `.f`, `.f90`, `.F90`, `.py`, `.c`, `.cpp`, `.h` (C et C++), `.inc` (Fortran), fichier sans extension avec `#!`, fichier binaire, extension inconnue, lien symbolique en boucle | 2 |
| `fortran_basic` | `SUBROUTINE`, `FUNCTION`, `MODULE`, `PROGRAM`, `CALL`, `USE` | 3 |
| `fortran_fixed_form` | Format fixe F77 : colonnes, continuation en colonne 6, commentaires `C` et `*` | 3 |
| `fortran_preproc` | `#ifdef` / `#else`, `#include`, macros ; conditions portées par les sites ; même routine dans deux branches | 3 |
| `fortran_ambiguity` | `f(i)` fonction ou tableau, `EXTERNAL`, interfaces explicites | 3 |
| `fortran_arrays_includes` | Tableaux déclarés dans un fichier inclus et dans un `COMMON`, fonctions intrinsèques, `known_arrays` | 3 |
| `fortran_advanced` | Interfaces génériques, procédures liées à un type, pointeurs de procédure, `RECURSIVE` | 3 |
| `fortran_data` | `COMMON`, variables de module, `INTENT` | 3 |
| `fortran_traps` | « call x » dans un commentaire ou une chaîne, majuscules et minuscules, Latin-1, fins de ligne Windows | 3 |
| `python_basic` | Imports relatifs, classes, méthodes, décorateurs, appels dynamiques (`heuristic`), un fichier Python 2 | 3 |
| `c_basic` | Fonctions, macros, deux fonctions `static` homonymes dans deux fichiers | 3 |
| `cpp_basic`, `cpp_overloads` | Classes, macros ; surcharges distinctes, appel non tranchable → site ambigu | 3 |
| `mini_hybrid` | Dépôt Python + C++ + C + Fortran : inventaire, graphes par langage, puis chaîne complète avec les ponts | 3, 8 |
| `partial_scope` | Analyse limitée à un répertoire : appels vers l'extérieur `out_of_scope` | 3 |
| `robustness` | Fichier malformé, fichier très volumineux, chemins avec espaces, accents ou > 260 caractères, fichier illisible | 3 |
| `bridge_pybind11` | Module pybind11 et son appel depuis Python | 8 |
| `bridge_fortran_c` | `BIND(C)`, décoration des noms | 8 |
| `bridge_prefix_negative` | Identifiants qui ressemblent à un préfixe de liaison sans en être ; macros de déclaration | 8 |
| `pack_acme` | Gestionnaire mémoire (trois niveaux de clés), aiguillage, catalogue, points d'entrée avec cible de repli | 12 |
| `keywords_language` | Langage fictif + document technique décrivant ses mots-clés ; profil écrit à la main (lot 12), puis proposé par l'IA (lot 13) | 12, 13 |
| `unknown_extension` | Fichiers d'un langage connu sous une extension inhabituelle | 13 |
| `bridge_unknown_prefix` | Appels C++ → Fortran par un préfixe de macro non déclaré | 13 |

Chaque fixture contient `src/` (quelques fichiers aux noms neutres), `expected_inventory.json` et `expected_graph.json` (nœuds, sites et arêtes attendus, avec lignes, colonnes, confiance et origine), écrits à la main.

### 5.3. Dépôt synthétique

`tests/synthetic/generate.py --routines 15000 --files 3000 --langs fortran,python,cpp,c --seed 42` génère un dépôt multi-langages, avec des appels entre langages et des routines très appelées (hubs), dont l'inventaire et le graphe sont connus par construction ; mêmes paramètres, même dépôt. Il sert aux tests de performance (§1.3), y compris l'écriture d'environ un million de sites, sans dépendre d'un code réel, et vérifie que le graphe extrait est exactement celui qui a été généré.

### 5.4. Corpus réels

Chaque code réel donne **deux corpus** :

- un **corpus de démarrage**, à périmètre réduit, dont les attentes ne portent que sur ce que le périmètre contient (lot 7) ;
- un **corpus complet**, qui inclut toutes les définitions, catalogues et cibles nécessaires aux parcours de bout en bout (lot 14).

```yaml
# tests/corpus/<code>_start/manifest.yaml
corpus: <code>_start
source: { path: "<emplacement local du code>", revision: "<tag ou commit exact>" }
license: "<licence du code analysé>"
packs: [<nom_du_pack>]
scope: ["<sous-répertoires analysés en détail>"]   # le reste du dépôt est indexé (définitions seulement)
```

```yaml
# tests/corpus/<code>_start/expectations.yaml — exemple fictif
inventory:
  languages: { fortran: { min_files: 100 }, python: { min_files: 10 }, cpp: { min_files: 10 } }
  max_unknown_rate: 0.01
expect:
  - node: "f:assemble_matrix"
  - callers_count: { node: "f:assemble_matrix", min: 10, max: 15 }
  - edge: { src: "py:solver.api.run", dst: "cpp:Solver::run()", kind: binds }
  - path: { from: "entry:RUN", to: "f:assemble_matrix", max_len: 12, edge_kinds: call_path }
  - no_call_to: ["f:rbuf"]                         # tableaux, jamais des appels
  - hidden: "f:log_msg"
  - writes: { routine: "f:update_state", data: "data:mem:*.VALUES", key_kind: family }
metrics:
  min_recall_definitions: 0.99
  min_recall_call_sites: 0.97                       # échantillon de rappel
  min_precision_resolved: 0.98                      # échantillon de précision, par langage
  min_precision_lower_bound: 0.95
  max_unresolved_rate: 0.02
  max_parse_failure_rate: 0.02
```

- `reference_sample.yaml` enregistre les liens et emplacements vérifiés à la main (avec la révision du code) ; ils sont rejoués automatiquement.
- Les sources des corpus ne sont jamais versionnées dans le dépôt ; le manifeste indique où les trouver localement, avec la révision exacte. Tous les corpus sont relancés régulièrement : l'ajout d'un nouveau code ne doit en dégrader aucun.

### 5.5. Tests transverses

| Test | Principe |
| :--- | :--- |
| Déterminisme | Même dépôt + même profil → exports canoniques identiques, sous Linux comme sous Windows |
| IA hors de l'analyse | `cgs scan` ne lance jamais le processus IA (vérifié) |
| Hors ligne, au niveau du code | Toute la suite tourne avec le réseau bloqué (pytest-socket) |
| Hors ligne, au niveau de l'application distribuée | Sous Linux, l'application démarre et fonctionne dans un espace de noms sans réseau (`unshare -n`) ; sous Linux et Windows, aucun port n'est à l'écoute pendant l'analyse, l'utilisation de l'interface et l'exécution du modèle |
| Chargement sûr | `yaml.safe_load` uniquement ; un fichier YAML contenant une balise d'objet Python est refusé ; schémas stricts ; aucun `pickle` |
| Robustesse | Sources malformées, fichiers très volumineux (au-delà d'un seuil, analyse limitée et signalée), chemins difficiles, liens symboliques en boucle, fichiers illisibles, délai dépassé ; données aléatoires envoyées aux adaptateurs (fuzzing avec hypothesis) sans plantage |
| Cohérence de l'inspecteur | Un fichier modifié après l'analyse est signalé « périmé » |
| Cache | Modifier un fichier inclus invalide les fichiers qui l'incluent |
| Isolation | Aucun identifiant déclaré par un pack dans le cœur (§6.4) |
| Dépendances entre paquets | Règles du §3.4 vérifiées par import-linter |
| Performance | Cibles du §1.3 mesurées sur le dépôt synthétique et sur le corpus de démarrage |
| Licences | Toutes les dépendances dans la liste du §3.15 (contrôle automatique au lot 16) |

### 5.6. Scénarios utilisateur

| # | Scénario | Résultat attendu |
| :--- | :--- | :--- |
| S1 | Ouvrir un dossier multi-langages, lancer l'inventaire puis l'analyse, annuler, relancer | Langages affichés avec leur couverture ; progression visible ; annulation propre ; interface réactive |
| S2 | Rechercher une routine | « Appelée par N routines dans M fichiers » ; double-clic → code à la ligne de l'appel |
| S3 | TreeGraph fonctions sur 4 niveaux d'appelés | Dépliages en moins de 200 ms, cycles marqués « ↺ » |
| S4 | TreeGraph fichiers d'un fichier, puis descente au niveau des routines | Liens pondérés, couleur par langage, détail des appels sur double-clic |
| S5 | Masquer puis réafficher les utilitaires | Badge « +N », graphe allégé |
| S6 | Chemin entre deux routines de langages différents | Chemin affiché et surligné, type de chaque étape visible, aiguillages marqués « possible » |
| S7 | Modifier un fichier, ré-analyser | Ré-analyse en moins de 30 s, vues mises à jour |
| S8 | Lancer l'application depuis la clé USB, réseau coupé | Démarrage et fonctionnement complets |
| S9 | Dépôt contenant un langage inconnu ; « Compléter avec l'IA » | Langage identifié, profil de mots-clés proposé avec l'aperçu de ses effets ; approuvé ou refusé ; liens marqués « IA » |
| S10 | Modifier un fichier sans ré-analyser, puis l'ouvrir dans l'inspecteur | Bandeau « Ce fichier a changé depuis l'analyse » et bouton « Ré-analyser » |

---

## 6. Extensibilité

### 6.1. Ajouter un langage

1. **Par l'IA (le plus rapide) :** l'inventaire signale le langage inconnu ; la boucle de complétion propose un profil de mots-clés (§3.9), contrôlé, montré, puis approuvé. Fournir un document technique sur le langage améliore la proposition. La couverture du profil est mesurée avant qu'on s'y fie.
2. **À la main :** écrire le profil de mots-clés soi-même.
3. **Adaptateur natif** (meilleure précision), s'il existe une grammaire tree-sitter sous licence permissive : créer `extract/<langage>/` implémentant `LanguageAdapter`, ajouter le langage à la table des extensions, créer la fixture `tests/fixtures/<langage>/`, déclarer les sous-types, la couleur et la coloration syntaxique.

### 6.2. Ajouter un pont

- Le plus souvent, une entrée `bridges` par préfixes et transformation de nom suffit (§3.8) : écrite à la main ou proposée par l'IA, toujours avec des tests positifs et négatifs.
- Sinon, créer `link/bridges/<pont>/` implémentant `Bridge`, avec une fixture à deux langages ; chaque site produit porte `origin = "bridge:<pont>"`.

### 6.3. Ajouter un code

1. Rédiger `docs/packs/<code>.md` : architecture du code, conventions, règles, points à valider, licence.
2. Lancer l'inventaire, puis la boucle de complétion IA ; reprendre ses propositions dans `rules.yaml` (§3.8) ; n'ajouter `enrich.py` que si nécessaire.
3. Déclarer les deux corpus (démarrage et complet) avec leurs attentes, puis constituer l'échantillon de référence.
4. **Critère d'acceptation :** attentes au vert, métriques du §2.1 atteintes, aucune régression, cœur inchangé — ou étendu de façon générique et documentée ici.

### 6.4. Règle d'isolation

Le cœur (`src/codegraph_sci/`, hors packs génériques) ne contient aucun identifiant propre à un code analysé. Chaque pack déclare ses identifiants (`identifiers`) ; un test fait échouer la construction s'ils apparaissent dans le cœur. Les fixtures utilisent des noms neutres. Les règles proposées par l'IA pour un projet vivent dans le dossier de ce projet, jamais dans le cœur.

---

## 7. Contraintes de licence qui touchent le code

- **Code public sous PolyForm Noncommercial 1.0.0**, présenté comme « code source public (source-available) sous licence non commerciale, avec licence commerciale distincte », jamais comme « open source ». Les extensions Pro vivent dans `codegraph_sci_pro`, que le cœur n'importe jamais.
- **Dépendances :** uniquement celles du §3.15, ou des licences équivalentes (MIT, BSD, Apache 2.0, ISC, PSF, MPL-2.0 pour les outils de test, LGPL avec bibliothèques séparées) ; jamais de GPL ou d'AGPL importée par le code ni embarquée par défaut. fxtran (GPL-3.0) ne peut être utilisé qu'en outil externe installé séparément, après revue de licence.
- **PySide6 et Qt (LGPL-3.0) :** garder les bibliothèques Qt en fichiers séparés et remplaçables dans `_internal/` (aucune liaison statique) ; fournir le texte de la LGPL et les avis de Qt dans `licenses/` ; fournir les sources de Qt et de PySide6 utilisées, ou une offre écrite de les fournir ; ne pas interdire leur remplacement par l'utilisateur. Ce découpage est nécessaire mais ne suffit pas à lui seul : la liste complète des obligations est vérifiée au lot 16.
- **Modèles IA :** uniquement Apache 2.0 ou MIT. L'édition IA contient le fichier du modèle **et le texte de sa licence** (ainsi que le fichier `NOTICE` s'il existe) : c'est la condition de redistribution de ces licences.
- **Codes analysés :** la révision exacte et la provenance de tout extrait utilisé dans une démonstration sont enregistrées, avec la notice de licence du code ; aucun code source d'un code analysé n'est intégré à une distribution commerciale sans revue préalable.
- **Documents techniques fournis par l'utilisateur :** lus localement, jamais copiés dans les règles au-delà de courts extraits de justification.
- **Contributions externes :** accord de contribution (CLA) signé avant toute intégration.
- **Clé de licence :** elle ne bloque jamais le cœur ni les données (lot 16).
- Détails commerciaux et juridiques : `docs/strategie_licence.md`.

---

## 8. Décisions et questions ouvertes

### 8.1. Décisions prises (16 octobre 2026)

| # | Décision |
| :--- | :--- |
| D1 | Application de bureau Python + Qt (PySide6) ; pas d'application web |
| D2 | Systèmes : Linux x86_64 (cible : Ubuntu) et Windows x64 |
| D3 | Fonctionnement 100 % hors ligne ; version complète transférable sur clé USB |
| D4 | Machines modestes, CPU seul : allègement graphique obligatoire |
| D5 | Graphe déterministe pour un profil d'analyse donné ; l'IA prépare le profil, elle n'intervient jamais pendant l'analyse |
| D6 | Question par défaut : combien de routines appellent une routine, et lesquelles |
| D7 | Deux vues TreeGraph : fichiers et fonctions |
| D8 | Pas de compilateur : validation sans compilation, par échantillons vérifiés (§2.1) |
| D9 | Double licence PolyForm NC + licence commerciale |
| D10 | L'édition IA de la version portable inclut le modèle et sa licence — *hypothèse à confirmer* |
| D11 | Le premier cas de test mélange Fortran, Python et C ou C++ : inventaire des langages et quatre adaptateurs dès les lots 2 à 5 |
| D12 | *(modifiée en v7, à confirmer)* L'IA identifie les langages non reconnus et définit elle-même les mots-clés manquants ; par défaut, l'utilisateur valide en un clic après l'aperçu des liens ajoutés et retirés ; un mode d'adoption automatique est activable par projet |
| D13 | Le plan ne comporte que des lots et leurs dépendances, sans jalons ni durées |
| D14 | Chaque appel constaté est conservé comme un site d'appel (une ligne en base) ; les arêtes sont des agrégats de sites |
| D15 | Construction Linux sur une base glibc 2.28 : compatible Ubuntu 20.04+ et RHEL/Rocky 8+ |
| D16 | Algorithmes de graphe écrits dans le projet (Tarjan itératif, ensembles de bits) ; NetworkX retiré |
| D17 | Parseur Fortran choisi par un banc comparatif sur fichiers réels, parmi des candidats sous licence permissive ; fxtran (GPL-3.0) exclu de la distribution par défaut |
| D18 | *(lot 4)* Parseur Fortran principal : **analyseur d'instructions logiques écrit dans le projet** (formats fixe et libre, continuations, branches du préprocesseur conservées, positions exactes). Banc sur les fixtures (`docs/bench/fortran_parsers.md`) : seul candidat à 100 % de rappel et de précision ; tree-sitter-fortran échoue sur le format fixe (texte au-delà de la colonne 72, commentaires `C`/`*`) et ne garde pas les branches `#ifdef` ; fparser échoue sur 4 fichiers sur 23 et est 25 fois plus lent ; LFortran non évalué (binaire absent). Repli et double extraction : extracteur à motifs indépendant. **À confirmer sur un échantillon de fichiers réels du cas de test n°1** (`python tools/bench_fortran.py <dossier>`) |
| D19 | *(lot 0)* Grammaires tree-sitter : roues individuelles `tree-sitter-fortran`, `-python`, `-c`, `-cpp` ; `tree-sitter-language-pack` ≥ 1.0 est exclu car il télécharge les grammaires à l'exécution (contraire à C2) |

### 8.2. Questions ouvertes

1. Confirmer D10, ou préférer que le client ajoute lui-même le modèle dans `models/`.
2. Confirmer D12 (validation en un clic par défaut, adoption automatique en option).
3. Pack `generic_fortran` : dans le cœur (attractivité) ou dans Pro (valeur) ?
4. Identification et complétion par l'IA : dans Pro seulement (choix actuel), ou une version limitée dans le cœur ?
5. Prise en charge officielle de RHEL/Rocky 8, ou seulement Ubuntu (la construction permet les deux) ?
6. Cas de test n°2 : quel code, et quel nouvel axe doit-il solliciter ?
7. Une machine Windows est-elle disponible pour les tests du lot 0, ou faut-il une machine virtuelle ?
8. Disponibilité du nom « CodeGraph-Sci » (marque, nom de domaine, PyPI).

---

## Annexe A — Historique des versions

| Version | Contenu |
| :--- | :--- |
| v1 | Architecture initiale autour du premier cas de test |
| v2 | Modèle de données, pipeline, sécurité, licence, tests, feuille de route |
| v3 | Double licence ; installation par l'utilisateur ; modèles Apache 2.0 / MIT |
| v4 | Document générique : extensions (langages, ponts, packs) ; cas de test séparés |
| v5 | Document d'exécution : application de bureau PySide6, hors ligne, portable ; verrous ; validation sans compilateur ; plan en lots |
| v6 | Inventaire des langages et profil d'analyse ; dépôts multi-langages dès le départ ; IA qui identifie les langages et définit les mots-clés manquants ; profils par mots-clés ; plan en 17 lots sans jalons |
| **v7** | **Intégration de deux revues externes :** sites d'appel comme vérité de base et identité des symboles (signatures C++, fonctions `static`, variantes) ; écriture SQLite groupée, index en fin, remplacement atomique, WAL en incrémental ; cache JSON compressé tenant compte des fichiers inclus ; symboles locaux et règle Fortran `nom(...)` (tableaux des fichiers inclus et des `COMMON`, intrinsèques) ; données à trois niveaux de précision ; spécification stricte du format de pack et chargement sûr ; sémantique explicite des préfixes de liaison et tests négatifs ; analyse partielle avec état `out_of_scope` ; métriques séparées et échantillons stratifiés avec bornes de confiance, échantillon de référence rejoué ; point d'arrêt au lot 7 ; banc comparatif des parseurs Fortran sous licence permissive, fxtran (GPL-3.0) exclu par défaut ; construction Linux sur glibc 2.28 et IA compatible avec les processeurs anciens ; NetworkX remplacé par des algorithmes maison ; types d'arêtes explicites pour les chemins ; contrôle de fraîcheur dans l'inspecteur ; validation en un clic des propositions de l'IA par défaut ; tests de robustesse, de chargement sûr et de réseau sur l'application distribuée ; conformité des licences comme tâche explicite du lot 16 |

## Annexe B — Glossaire

- **Inventaire :** détection du langage de chaque fichier du dépôt et rapport de couverture.
- **Profil d'analyse :** fichier du projet qui fixe le périmètre, les langages, les adaptateurs, les chemins d'inclusion, les packs et les règles utilisés ; l'analyse ne lit que lui.
- **Site d'appel :** un appel ou un usage constaté à un endroit précis du code (fichier, ligne, colonne), avec sa condition, son origine et son état de résolution.
- **Arête :** agrégation des sites d'appel de même appelant, même appelé et même type.
- **Hors périmètre (`out_of_scope`) :** cible définie dans le dépôt mais en dehors des répertoires analysés en détail.
- **Adaptateur de langage :** plugin qui lit les fichiers d'un langage et produit des faits ; natif (parseur) ou par mots-clés.
- **Profil de langage par mots-clés :** description d'un langage par ses mots-clés de définition, d'appel, d'inclusion et ses marqueurs ; extraction heuristique, à couverture mesurée.
- **Pont :** règle ou plugin qui relie un symbole d'un langage à sa cible dans un autre.
- **Boucle de complétion :** analyse → diagnostic → propositions de l'IA → contrôles automatiques → aperçu et validation → profil mis à jour → nouvelle analyse.
- **Domain Pack :** règles, surtout déclaratives, qui décrivent les conventions d'un code.
- **Faits :** ce qu'on extrait d'un fichier avant de relier les fichiers entre eux.
- **Fixture :** mini-dépôt de test dont l'inventaire et le graphe attendus sont écrits à la main.
- **Corpus de démarrage / complet :** code réel utilisé comme cas de test, d'abord à périmètre réduit, puis en entier.
- **Échantillon de référence :** liens et emplacements vérifiés à la main, enregistrés et rejoués automatiquement.
- **Hub :** routine (ou famille de données) reliée à un très grand nombre d'autres, typiquement un utilitaire.
- **TreeGraph :** vue en arbre dessiné, dépliable nœud par nœud, au niveau des fonctions ou des fichiers.
- **Dossier portable :** dossier autonome (Python embarqué compris) qui fonctionne copié n'importe où, y compris sur une clé USB.
- **Modèle factice :** remplaçant du modèle IA qui renvoie des réponses enregistrées, pour tester sans modèle.
- **GGUF :** format de fichier des modèles exécutés par llama.cpp.

## Annexe C — Consignes pour l'agent de développement (à copier dans `AGENTS.md`)

1. Lire `docs/architecture.md` (§3 et le lot demandé) avant de coder. Ne lire un `docs/packs/<code>.md` que pour travailler sur ce pack.
2. Ne réaliser **qu'un lot à la fois** ; s'arrêter quand ses tests de validation passent. Ne pas commencer les lots d'interface tant que le lot 7 n'est pas validé.
3. Respecter les contrats (§3.5 à §3.10) et les dépendances entre paquets (§3.4). Tout changement de contrat est reporté dans `docs/architecture.md`.
4. Écrire ou compléter les tests **avant** le code qui doit les faire passer.
5. Aucun accès réseau ni port ouvert, dans le code comme dans les tests.
6. Aucune dépendance hors de la liste du §3.15.
7. Aucun identifiant propre à un code analysé dans `src/codegraph_sci/`.
8. Déterminisme : trier toute collection avant de l'écrire ; pas d'horodatage dans les faits ; chemins relatifs avec `/` ; l'analyse ne lit que le profil d'analyse et n'appelle jamais l'IA.
9. Le langage d'un fichier vient de l'inventaire ; aucun adaptateur ne le devine.
10. Chaque appel constaté devient un site d'appel avec fichier, ligne, colonne, condition et origine ; ne jamais fusionner deux sites en perdant ces informations.
11. Fichiers de configuration : `yaml.safe_load` et validation par schéma uniquement ; jamais `pickle`.
12. Chaque fichier analysé a un délai maximal ; un échec est consigné, jamais bloquant.
13. L'interface n'accède aux données que par `GraphQuery` ; aucune requête longue dans le thread principal.
14. Toute fonction IA doit être testable avec le modèle factice.
15. Python 3.12 typé (mypy strict), formaté avec ruff ; identifiants, code et commentaires en anglais.

## Annexe D — Conventions d'extraction précisées (lot 3)

Ces conventions complètent les §3.5 et §3.7 ; les graphes attendus des fixtures (`tests/fixtures/*/expected_graph.json`) les appliquent.

- **Identités complémentaires :** module Fortran `fmod:<module>` (distinct des procédures, qui peuvent porter le même nom) ; type dérivé, interface générique et procédure interne `f:<hôte>::<nom>` ; méthode Python `py:<module>.<Classe>.<méthode>`, fonction imbriquée `py:<module>.<fonction>.<interne>` ; externes `ext:intrinsic:<nom>`, `ext:libc:<nom>`, `ext:python:<module>[.<nom>]`, `ext:mpi:<nom>`, `ext:blas:<nom>`.
- **Nœuds :** chaque fichier source a un nœud `file:<chemin>` ; les déclarations (prototypes C/C++, blocs `INTERFACE` explicites ou abstraits, fonctions virtuelles pures) ne créent pas de définition. Un bloc de macro au niveau fichier (ex. `PYBIND11_MODULE(...) { }`) n'est pas une fonction : ses appels ont pour source le nœud fichier.
- **Position d'un site :** ligne et colonne (à partir de 1) du début du texte de la cible tel qu'écrit (`target_text`) : `ELEMK`, `c%area`, `self.check`, `ops::scale`. Pour un appel masqué par une macro, position de la macro et `target_text` = fonction appelée après expansion. Pour une inclusion, position du nom de fichier inclus ; la source est le nœud fichier.
- **Confiance :** `exact` = cible unique trouvée par son nom ; `resolved` = cible choisie par une règle (type du receveur, arité ou types des arguments, `maybe_call` tranché par Link, macro, variantes préprocesseur) ; `heuristic` = appel dynamique (variable, `getattr`) ou site non résolu ; `ambiguous` = plusieurs candidats.
- **Variantes préprocesseur :** un appel vers une routine définie en plusieurs variantes (`f:x`, `f:x#2`) est `resolved` vers la première, avec toutes les variantes en candidats ; une arête est créée vers chaque variante.
- **Conditions :** `#ifdef X` → `defined(X)`, `#ifndef X` / `#else` → `!defined(X)`, `#if E` → `E` (espaces normalisés) ; conditions imbriquées jointes par ` && `.
- **Appels sans cible statique :** procédure reçue en argument, pointeur de procédure, variable Python → `dynamic_call`, `unresolved` (ou `resolved`/`heuristic` si une propagation simple trouve la cible, ex. `h = getattr(m, "f")`).
- **Bibliothèques :** appel Python vers un module hors dépôt → `external` vers `ext:python:…` ; appel de méthode sur un receveur inconnu sans aucune méthode de ce nom dans le dépôt → `external` sans nœud cible.
- **Arêtes :** `calls` (sites `call`, `maybe_call`, `dynamic_call` ayant une cible, y compris `external`, `out_of_scope` et chaque candidat d'un site ambigu), `uses` (`use`, `include`), `inherits`, `implements` (interface générique → procédures spécifiques, sans site), `contains` (structure).
- **Liaisons (lot 8) :** nœuds `binding` extraits des sources — `bind:pybind11:<module>[.<nom>]` (`PYBIND11_MODULE`, `m.def`), `bind:pyext:<module>[.<nom>]` (API C de Python : `PyInit_<module>`, tables `PyMethodDef`), `bind:decl:<nom>@<fichier>` (motifs de déclaration d'une règle). Un site résolu par un pont garde son `ref_kind` et prend l'origine `bridge:<pont>` (`bridge:prefix_calls@<règle>` pour une règle du profil) et la confiance `resolved` ; son arête est `binds` pour `pybind11` et `python_extension` (Python → code compilé), `bridges` pour `fortran_c`, `c_cpp` et `prefix_calls`. Une arête structurelle `binds` relie chaque nœud `binding` à son implémentation. Les ponts natifs (`pybind11`, `python_extension`, `c_cpp`, `fortran_c`) sont actifs par défaut ; ils n'agissent que sur des sites non résolus ou externes.
