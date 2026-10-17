CodeGraph-Sci - portable folder
===============================

Works fully offline: no cloud service is needed and analysed source code is never sent anywhere.

Start
- Desktop application: CodeGraph-Sci (CodeGraph-Sci.exe on Windows)
- Command line       : cgs (cgs.exe on Windows)
- Installation check : cgs selftest

Data
- By default on the local disk (~/.codegraph-sci/ or %LOCALAPPDATA%\CodeGraph-Sci\),
  because an SQLite database is slow on a USB key.
- Portable mode: create the file data/portable.flag; projects and settings are
  then written to data/, next to the application.

Linux: Qt 6.5+ needs libxcb-cursor0 (sudo apt install libxcb-cursor0 on Ubuntu 22.04).

Licenses: see the licenses/ folder.
