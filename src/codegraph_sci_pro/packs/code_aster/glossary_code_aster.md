# Glossaire Code_Aster (pack `code_aster`)

Vocabulaire métier fourni à l'IA locale (explications, lot 15). Termes génériques, sans extrait de code.

- **JEVEUX** : gestionnaire mémoire de Code_Aster ; les objets sont nommés par des chaînes (ex. `<sd>.VALE`) et accédés par `jeveuo` (`'L'` lecture, `'E'` écriture), créés par `wkvect`/`jecreo`/`jecrec`, détruits par `jedetr`.
- **`zi`, `zr`, `zc`, `zl`, `zk8`… `zk80`** : tableaux globaux (blocs `COMMON` de `jeveux.h`) donnant accès au contenu des objets JEVEUX par adresse.
- **Objet de travail `&&…`** : objet JEVEUX temporaire propre à une routine.
- **Structure de données (SD)** : ensemble d'objets JEVEUX de même préfixe (champ, matrice, résultat…) ; les suffixes `.VALE`, `.DESC`, `.REFE`… désignent ses composantes.
- **`opXXXX`** : routine Fortran d'un opérateur (commande utilisateur), ex. `op0070` pour `STAT_NON_LINE`.
- **`te0000` / `teXXXX`** : aiguillage vers les routines élémentaires (calcul d'une option sur un type d'élément fini).
- **`lc0000` / `lcXXXX`** : aiguillage vers les lois de comportement.
- **Option de calcul** : nom d'un calcul élémentaire (ex. `RIGI_MECA` pour la rigidité mécanique).
- **Cas-test** : fichier de commandes (`.comm`) de la base de validation `astest/`.
- **`CALL_X` / `CALLO_X`** : macros C/C++ qui appellent la routine Fortran `x` ; **`DEFS…`** : macros qui définissent une fonction C appelable depuis le Fortran.
- **`libaster`** : module Python compilé (pybind11) qui expose le noyau C++ à la couche Python `code_aster/`.
- **`UTMESS`** : émission d'un message utilisateur (information, alarme, erreur) ; **`ASSERT`** : vérification interne.
