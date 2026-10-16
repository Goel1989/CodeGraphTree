# AGENTS.md — Consignes pour l'agent de développement

(Copie de l'Annexe C de docs/architecture.md.)

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

## Environnement

- Python 3.12 dans `.venv` : `.venv/Scripts/python tools/check.py` (Windows) ou `.venv/bin/python tools/check.py`.
- Grammaires tree-sitter : roues individuelles (`tree-sitter-fortran`, `-python`, `-c`, `-cpp`). Ne pas utiliser `tree-sitter-language-pack` ≥ 1.0 : il télécharge les grammaires à l'exécution.
