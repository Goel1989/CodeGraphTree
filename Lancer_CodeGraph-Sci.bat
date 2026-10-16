@echo off
rem Lance l'application de bureau CodeGraph-Sci (environnement .venv du projet).
rem Double-cliquer sur ce fichier. Le dernier projet ouvert est rouvert automatiquement.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [CodeGraph-Sci] Environnement .venv introuvable dans %~dp0
    echo Creez-le avec :  py -3.12 -m venv .venv  puis  .venv\Scripts\python -m pip install -e .[dev]
    pause
    exit /b 1
)

rem Sans fenetre console : pythonw. Pour voir les erreurs, lancer avec l'argument "debug".
if /i "%~1"=="debug" (
    ".venv\Scripts\python.exe" -m codegraph_sci.ui.app
    pause
) else (
    start "" ".venv\Scripts\pythonw.exe" -m codegraph_sci.ui.app
)
endlocal
