# Changelog

## Lot 0 — Squelette portable
- Structure du dépôt (§3.16), `pyproject.toml`, contrats import-linter (§3.4), `tools/check.py`.
- `cgs --version`, `cgs selftest` (Qt, grammaires tree-sitter, SQLite FTS5, dossier de données, jeux d'instructions CPU, garde réseau).
- Garde réseau (`core/netguard.py`) installée au démarrage de `cgs` et de l'application.
- Fenêtre PySide6 vide avec « À propos ».
- `tools/build_portable.py` + spécification PyInstaller à deux exécutables (mode dossier), conteneur Linux glibc 2.28, intégration continue Linux + Windows.
- Mesure : dossier portable Windows sans IA = 129 Mo.
