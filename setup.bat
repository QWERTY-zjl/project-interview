@echo off
REM One-click setup: prefer the bundled portable Python; fall back to local Python.
cd /d "%~dp0"

REM Case 1: bundled runtime present - nothing to install, ready to launch.
if exist runtime\python\python.exe (
    echo [OK] Bundled Python runtime detected. No installation needed.
    echo.
    echo ==============================================
    echo   Just double-click start_personal_server.bat
    echo   then open http://127.0.0.1:10009 in browser.
    echo   See the .txt guide in this folder for details.
    echo ==============================================
    pause
    exit /b 0
)

REM Case 2: no bundled runtime (source mode) - build env with local Python.
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found and no bundled runtime in this package.
    echo        Please install Python 3.10+ from python.org first.
    echo        IMPORTANT: check "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo [1/3] Python detected:
python --version

REM Create virtualenv (skip if already exists).
if exist app\venv\Scripts\python.exe (
    echo [2/3] Virtualenv already exists, skipped.
) else (
    echo [2/3] Creating virtualenv app\venv ...
    python -m venv app\venv
    if errorlevel 1 (
        echo [FAIL] Failed to create virtualenv. Check disk space.
        pause
        exit /b 1
    )
)

REM Install dependencies from Aliyun mirror (~3-5 min on first run).
echo [3/3] Installing dependencies, please wait ...
app\venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
if errorlevel 1 (
    echo [FAIL] Install failed. Check your network and run again.
    pause
    exit /b 1
)

echo.
echo ==============================================
echo   Setup done! Two steps left:
echo   1. Copy .env.example to .env and fill in
echo      DASHSCOPE_API_KEY (from Aliyun Bailian).
echo   2. Double-click start_personal_server.bat
echo      then open http://127.0.0.1:10009
echo ==============================================
pause
