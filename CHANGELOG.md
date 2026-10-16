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
