@echo off
rem Starts the CodeGraph-Sci desktop application (the project's .venv environment).
rem Double-click this file. The last opened project is reopened automatically.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [CodeGraph-Sci] No .venv environment found in %~dp0
    echo Create it with:  py -3.12 -m venv .venv  then  .venv\Scripts\python -m pip install -e .[dev]
    pause
    exit /b 1
)

rem No console window: pythonw. To see errors, start with the "debug" argument.
if /i "%~1"=="debug" (
    ".venv\Scripts\python.exe" -m codegraph_sci.ui.app
    pause
) else (
    start "" ".venv\Scripts\pythonw.exe" -m codegraph_sci.ui.app
)
endlocal
