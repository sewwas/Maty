@echo off
title Profity AI — Bridge Launcher
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║         Profity AI — Starting MT5 Bridges                ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM ── Check Python is available ────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Please install Python 3.9+
    pause
    exit /b 1
)

REM ── Check bridge config files exist ──────────────────────────────────────
if not exist bridge_config_8001.json (
    echo [WARN] bridge_config_8001.json not found.
    echo        Run: python setup_accounts.py to set credentials first.
    echo.
)
if not exist bridge_config_8002.json (
    echo [WARN] bridge_config_8002.json not found.
    echo        Run: python setup_accounts.py to set credentials first.
    echo.
)

REM ── Kill any existing bridge processes ───────────────────────────────────
echo Stopping any existing bridge processes...
taskkill /FI "WINDOWTITLE eq Bridge 8001*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Bridge 8002*" /F >nul 2>&1
timeout /t 1 /nobreak >nul

REM ── Start Bot #1 Bridge (Port 8001) ──────────────────────────────────────
echo Starting Bridge #1 on port 8001...
start "Bridge 8001 — Bot #1 (MT5 Account #1)" cmd /k "python wine_mt5_bridge.py 8001"

REM ── Start Bot #2 Bridge (Port 8002) ──────────────────────────────────────
echo Starting Bridge #2 on port 8002...
start "Bridge 8002 — Bot #2 (MT5 Account #2)" cmd /k "python wine_mt5_bridge.py 8002"

echo.
echo Both bridges launched! Waiting 3s for them to initialize...
timeout /t 3 /nobreak >nul

echo.
echo ✅  Bridges running:
echo     Bot #1 Bridge → http://127.0.0.1:8001/account
echo     Bot #2 Bridge → http://127.0.0.1:8002/account
echo.
echo Now start the Streamlit app:
echo     streamlit run app.py --server.port 8501
echo.
pause
