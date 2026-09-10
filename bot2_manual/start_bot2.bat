@echo off
title Profity AI — Bot #2 Manual Grid Desk (Port 8502)
echo ===================================================================
echo     Profity AI — Bot #2: Manual Grid Desk (Port 8502)
echo ===================================================================
cd /d "%~dp0\.."

if exist .venv\Scripts\python.exe (
    set PY_CMD=.venv\Scripts\python.exe
    set STREAMLIT_CMD=.venv\Scripts\streamlit.exe
) else (
    set PY_CMD=python
    set STREAMLIT_CMD=streamlit
)

echo Starting Bot #2 Autonomous Engine...
start "Bot #2 Engine" %PY_CMD% bot2_manual\grid_engine.py

echo Starting Bot #2 Web Dashboard on http://localhost:8502 ...
%STREAMLIT_CMD% run bot2_manual\panel.py --server.port 8502 --server.address 0.0.0.0
pause
