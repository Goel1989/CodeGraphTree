# CodeGraph-Sci — Stratégie de licence et commerciale

**Version :** 1.1 (16 octobre 2026) — reprise de l'architecture v4, mise à jour pour la version portable hors ligne et la v7  
**Auteur :** Marian Bogdan Neagoe, PhD  
**Emplacement dans le dépôt :** `docs/strategie_licence.md`

> Ce document ne sert pas à l'implémentation au jour le jour. Les contraintes de licence qui touchent le code sont résumées dans `docs/architecture.md`, §7. Je ne suis pas avocat : le contrat commercial, le CLA et les conditions d'évaluation sont à faire relire par un conseil en propriété intellectuelle avant la première vente.

---

## 1. Positionnement concurrentiel

| Outil | Forces | Limites pour notre cible |
| :--- | :--- | :--- |
| Doxygen / FORD | Gratuits, graphes d'appels Fortran, documentation | Graphes statiques illisibles à grande échelle ; pas de ponts inter-langages ; aucune notion de flux de données propre à un code |
| SciTools Understand | Multi-langages dont Fortran, métriques, outil mûr | Généraliste ; ignore les conventions propres à chaque code ; pas d'IA locale orientée calcul scientifique |
| Sourcetrail (archivé) | Excellente expérience d'exploration | Plus maintenu, pas de Fortran |
| CodeScene | Hotspots, analyse de l'historique Git | Pas de graphe inter-langages ni de sémantique propre aux codes scientifiques |
| Assistants IA cloud | Explications fluides | Interdits dans de nombreux contextes R&D/défense ; hallucinations structurelles |

**Proposition de valeur :** *suivre un appel du point d'entrée utilisateur jusqu'à la boucle de calcul, à travers tous les langages, comprendre les conventions propres à chaque code grâce aux Domain Packs, et l'expliquer localement — avec une preuve pour chaque lien.*

---

## 2. Stratégie de double licence et monétisation

### 2.1. Décision : double licence PolyForm Noncommercial + licence commerciale

| Public | Licence | Droits |
| :--- | :--- | :--- |
| Étudiants, chercheurs, enseignants, usage personnel, organismes publics de recherche | **PolyForm Noncommercial 1.0.0** (fichier `LICENSE`) | Utiliser, étudier, modifier et partager gratuitement, pour un usage non commercial |
| Entreprises, bureaux d'études, consultants facturant leurs prestations | **Licence commerciale** (`COMMERCIAL_LICENSE.md` + contrat) | Usage commercial du cœur, extensions Pro/Enterprise, support |

**Ce que cette combinaison garantit :**

- **Aucune redevance** aux auteurs des modèles : uniquement des modèles Apache 2.0 / MIT, fournis avec leur licence dans l'édition IA (§2.7).
- **Personne ne peut revendre ni exploiter commercialement le code** sans licence commerciale.
- **L'auteur est le seul à pouvoir vendre des licences commerciales** — à condition de détenir les droits sur 100 % du code : chaque contribution externe doit être couverte par un CLA (§2.3), sinon elle ne peut pas entrer dans la version commerciale.
- **La licence commerciale couvre le code de CodeGraph-Sci, pas le modèle :** le contrat le précise et renvoie à la licence Apache 2.0 / MIT du modèle téléchargé.

**Points d'attention :**

- **Vocabulaire.** PolyForm NC n'est pas une licence *open source* au sens de l'OSI, dont la définition exclut toute restriction d'usage commercial. Le projet doit être présenté comme **« code source public (source-available), double licence »** et non comme « open source » : la confusion serait vite relevée par la communauté scientifique et nuirait à la crédibilité du projet.
- **Exception prévue par PolyForm NC.** Les organismes publics de recherche, établissements d'enseignement et institutions gouvernementales peuvent utiliser le cœur gratuitement, quel que soit leur financement. Les extensions Pro, propriétaires, restent payantes pour eux.
- **Évaluation par les entreprises.** PolyForm NC interdit à une entreprise d'essayer le cœur : prévoir une **licence d'évaluation gratuite de 30 jours** (clé Ed25519 standard, §3).
- **Évolution possible.** Détenant tous les droits (grâce au CLA), l'auteur pourra plus tard ajouter une licence open source (ex. AGPLv3) s'il souhaite le label OSI. Les versions déjà publiées restent, elles, utilisables sous leur licence d'origine.
- **Validation juridique.** Contrat commercial, CLA et conditions d'évaluation à faire relire par un conseil en propriété intellectuelle avant la première vente.

### 2.2. Répartition des fonctionnalités

| Fonction | Community | Pro | Enterprise |
| :--- | :---: | :---: | :---: |
| Adaptateurs Python, C, C++, Fortran ; ponts de base | ✓ | ✓ | ✓ |
| Exploration, recherche, chemins, impact | ✓ | ✓ | ✓ |
| Filtre de bruit manuel + repli automatique des hubs (`generic_noise`) | ✓ | ✓ | ✓ |
| Export HTML / SVG | ✓ | ✓ | ✓ |
| Flux de données génériques Fortran (`generic_fortran`) *(à décider)* | — | ✓ | ✓ |
| Domain Packs officiels pour des codes publics, maintenus par version | — | ✓ | ✓ |
| Cerveau IA local, fiches, RAG documentaire | — | ✓ | ✓ |
| Rapports d'architecture (Markdown / PDF) | — | ✓ | ✓ |
| Métriques avancées, hotspots Git | — | ✓ | ✓ |
| Serveur MCP local *(à décider)* | — | ✓ | ✓ |
| Packs sur mesure pour codes maison (format déclaratif) *(à décider)* | — | — | ✓ |
| Intégration CI : diff d'architecture, rapports de merge request | — | — | ✓ |
| Support | Communauté | E-mail | Contractuel, packs maintenus par version |

### 2.3. Contributions externes

Le double licenciement exige de détenir les droits sur tout le code du cœur. Il faut donc un **CLA** (accord de licence des contributions) signé par chaque contributeur — automatisable avec un bot sur GitHub — sans quoi une contribution ne pourra pas être relicenciée commercialement. À mettre en place avant la première contribution externe, y compris pour un adaptateur, un pont ou un pack proposé par la communauté.

### 2.4. Codes analysés et corpus de test

- Analyser un code ne modifie ni sa licence ni celle de CodeGraph-Sci.
- Les corpus de test ne sont **pas versionnés** dans le dépôt : seuls leurs manifestes (emplacement, révision) le sont (architecture, §5.4).
- Une démonstration publiée qui contient des extraits d'un code analysé respecte la licence de ce code (ex. code sous GPL → démonstration sous GPL, avec attribution, dans un dossier séparé). Chaque `docs/packs/<code>.md` précise ce point.
- Les noms des codes analysés appartiennent à leurs titulaires : usage nominatif (« compatible avec … »), sans suggérer de partenariat.

### 2.5. Licences tierces

- Registre `THIRD_PARTY_LICENSES.md` généré automatiquement (Python : PSF ; PySide6 / Qt : LGPL-3.0 ; tree-sitter et grammaires : MIT ; PyYAML, jsonschema : MIT ; llama.cpp / llama-cpp-python : MIT ; pypdf : BSD-3 ; cryptography : Apache-2.0 / BSD ; PyInstaller : GPL-2.0 avec exception de distribution). La liste de référence est tenue dans `docs/architecture.md`, §3.15.
- **fxtran est sous GPL-3.0** : il n'est jamais embarqué dans la distribution par défaut ; il ne peut être utilisé qu'en outil externe installé séparément, après revue de licence.
- **PySide6 / Qt (LGPL-3.0)** : bibliothèques séparées et remplaçables, texte de la licence et avis fournis, sources de Qt et PySide6 fournies ou offre écrite de les fournir (architecture, §7).
- **Contrôle automatique en CI** (ex. `pip-licenses` côté Python, `license-checker` côté npm) avec une liste blanche (MIT, BSD, Apache 2.0, ISC, EPL-2.0, LGPL après examen) : toute nouvelle dépendance sous GPL/AGPL ou sous licence non commerciale fait échouer la construction. La version portable embarque ces bibliothèques : c'est une redistribution, qui impose de joindre leurs licences (dossier `licenses/`). Un nouvel adaptateur qui apporte un parseur tiers passe par le même contrôle.
- Les licences des poids sont affichées dans l'interface et enregistrées avec la provenance du modèle (§2.7).

### 2.6. Offres et sources de revenus

- **Community :** gratuit pour tout usage non commercial (PolyForm NC).
- **Pro :** abonnement annuel par utilisateur nommé — consultants, petites équipes.
- **Enterprise :** licence de site ou d'équipe, support contractuel, packs maintenus par version, packs sur mesure, intégration CI.
- **Services** (probablement le premier revenu) : Domain Pack sur mesure pour un code maison, audit et cartographie d'un code legacy livrés avec rapport, formation.
- **Évaluation :** clé Pro de 30 jours produite par le même mécanisme (§3).
- Grille tarifaire à calibrer après les entretiens de la Phase 0.

### 2.7. Modèle IA inclus dans l'édition IA

- L'édition IA de la version portable contient le fichier du modèle : l'éditeur **redistribue** donc les poids.
- Les licences Apache 2.0 et MIT l'autorisent, à condition de joindre le texte de la licence, de conserver les mentions de l'auteur (et le fichier `NOTICE` pour Apache 2.0, s'il existe) et de ne pas utiliser ses marques. Si l'éditeur quantifie lui-même le modèle, il le signale comme une modification.
- La licence du modèle continue de s'appliquer à l'utilisateur : d'où la règle « uniquement Apache 2.0 ou MIT », appliquée par le registre `models.lock`.
- Un modèle sous licence non commerciale (ex. Qwen2.5-3B et Qwen2.5-Coder-3B, licence *Qwen Research*) n'est jamais inclus ni proposé.
- Ces licences n'imposent rien sur les textes produits par le modèle.
- Hypothèse à confirmer par l'auteur (architecture, décision D10), puis à faire valider par un conseil en propriété intellectuelle.

---

## 3. Système de clé de licence cryptographique (Ed25519)

### 3.1. Objectif réaliste

Dans une application Python, aucune protection logicielle n'est inviolable : un utilisateur déterminé peut modifier la vérification. Les clients visés (grands comptes, défense, énergie) paient pour la **conformité juridique, le support et les mises à jour**, pas à cause d'un verrou. Le système vise donc à :

- rendre l'usage conforme simple, même sur un poste isolé ;
- rendre l'usage non conforme visible ;
- **ne jamais pénaliser un client honnête.**

### 3.2. Contenu signé

```json
{
  "v": 1,
  "kid": "2026-A",
  "license_id": "L-2026-0042",
  "licensee": "ACME Aéro — BE Structures",
  "tier": "enterprise",
  "features": ["packs", "ai", "reports", "ci"],
  "seats": 10,
  "window_start": "2026-11-01",
  "window_end": "2026-11-08",
  "duration_days": 365,
  "issued_at": "2026-10-30"
}
```

- Sérialisation compacte (JSON canonique ou CBOR) + signature Ed25519 (64 octets), encodée en Base32 Crockford par groupes de 5 avec somme de contrôle : `CGWIN-XXXXX-XXXXX-…`. Également livrable sous forme de **fichier de licence**, plus pratique qu'une longue clé à saisir.
- `kid` identifie la clé de signature : le logiciel embarque plusieurs clés publiques, ce qui permet une **rotation** sans invalider les licences existantes.

### 3.3. Activation hors ligne

- Fenêtre d'activation (`window_start` → `window_end`) et durée après activation (`duration_days`).
- Pas d'identifiant matériel : le nombre de postes (`seats`) relève du contrat. En contrepartie, **le nom du titulaire est affiché** dans l'interface et en filigrane dans les rapports exportés — une dissuasion sociale efficace en entreprise.
- Pour les clients qui l'exigent : liaison à une machine par **défi-réponse hors ligne** (le logiciel affiche un code court, l'éditeur renvoie une clé liée).
- Renouvellement : simple nouvelle clé, sans connexion.

### 3.4. Recul d'horloge : détection tolérante

- *High-water mark* local (horodatage le plus récent observé) conservé, avec une **tolérance** (ex. 48 h) pour les fuseaux horaires, changements d'heure et dérives NTP.
- **Les dates de modification (`mtime`) des fichiers scannés ne servent pas de critère de verrouillage :** extraction d'archives, copies `cp -p`, montages NFS et caches CI produisent des dates « futures » parfaitement légitimes. Elles restent un simple indicateur de diagnostic.
- En cas d'incohérence : avertissement, puis période de grâce (ex. 14 jours) invitant à saisir une nouvelle clé ; **jamais** de blocage du cœur ni de perte de données.
- Le chiffrement `Fernet` de l'état local n'est qu'une obfuscation (la clé de chiffrement est sur la machine) : le conserver si souhaité, sans le présenter comme une sécurité.

### 3.5. Révocation et clé privée

- Révocation impossible hors ligne → privilégier des durées d'un an avec renouvellement.
- Clé privée Ed25519 conservée hors de toute machine de développement connectée (jeton matériel ou coffre chiffré), avec sauvegarde hors ligne.
- Le script de génération vit dans un **dépôt privé séparé**, jamais dans l'arborescence du dépôt public.

### 3.6. Distribution du code Pro

- Dépôt privé `codegraph-sci-pro`, distribué sous forme de **wheel compilée** (Cython ou Nuitka) : relève le coût de contournement et protège le savoir-faire des packs.
- Chargé par le cœur via les *entry points* Python (`codegraph_sci.plugins`) ; le cœur fonctionne sans lui.
