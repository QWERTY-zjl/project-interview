@echo off
REM Launch the interview simulator server (FastAPI).
cd /d "%~dp0"

REM Interpreter priority: bundled portable Python - project venv - system python.
if exist runtime\python\python.exe (
    set "PY=runtime\python\python.exe"
    echo Bundled Python runtime detected. Starting ...
) else if exist app\venv\Scripts\python.exe (
    set "PY=app\venv\Scripts\python.exe"
    echo Using project virtualenv app\venv ...
) else (
    echo Python not found. Please run setup.bat first.
    pause
    exit /b 1
)

REM Isolate from user-level site-packages so the bundled deps stay untouched.
set "PYTHONNOUSERSITE=1"

REM API key is read from .env in the project root (bundled with the package).
echo Starting server ... open http://127.0.0.1:10009 in your browser.
%PY% -m app.main

pause
