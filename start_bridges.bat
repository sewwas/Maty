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
if not exist bridge_config_8003.json (
    echo [WARN] bridge_config_8003.json not found.
    echo        Run: python setup_accounts.py to set credentials first.
    echo.
)

REM ── Kill any existing bridge processes ───────────────────────────────────
echo Stopping any existing bridge processes...
taskkill /FI "WINDOWTITLE eq Bridge 8001*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Bridge 8002*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Bridge 8003*" /F >nul 2>&1
timeout /t 1 /nobreak >nul

REM ── Start Bot #1 Bridge (Port 8001) ──────────────────────────────────────
echo Starting Bridge #1 on port 8001...
start "Bridge 8001 — Bot #1 (Auto Grid MT5)" cmd /k "python wine_mt5_bridge.py 8001"

REM ── Start Bot #2 Bridge (Port 8002) ──────────────────────────────────────
echo Starting Bridge #2 on port 8002...
start "Bridge 8002 — Bot #2 (Manual Desk MT5)" cmd /k "python wine_mt5_bridge.py 8002"

REM ── Start Bot #3 Bridge (Port 8003) ──────────────────────────────────────
echo Starting Bridge #3 on port 8003...
start "Bridge 8003 — Bot #3 (Trend Runner MT5)" cmd /k "python wine_mt5_bridge.py 8003"

echo.
echo All 3 bridges launched! Waiting 3s for them to initialize...
timeout /t 3 /nobreak >nul

echo.
echo ✅  Bridges running:
echo     Bot #1 Bridge → http://127.0.0.1:8001/account
echo     Bot #2 Bridge → http://127.0.0.1:8002/account
echo     Bot #3 Bridge → http://127.0.0.1:8003/account
echo.
echo Start the Streamlit Dashboards:
echo     Bot #1 (Auto Grid):    streamlit run app.py --server.port 8501
echo     Bot #2 (Manual Desk):  streamlit run manual_grid_desk.py --server.port 8502
echo     Bot #3 (Trend Runner): streamlit run bot3_trend\panel.py --server.port 8503
echo.
pause
