@echo off
title Profity AI — Bot #6 FVG Crossfire (Port 8506)
echo ===================================================================
echo     Profity AI — Bot #6: FVG Crossfire
echo ===================================================================
cd /d "%~dp0\.."

if exist .venv\Scripts\streamlit.exe (
    set STREAMLIT_CMD=.venv\Scripts\streamlit.exe
    set PYTHON_CMD=.venv\Scripts\python.exe
) else (
    set STREAMLIT_CMD=streamlit
    set PYTHON_CMD=python
)

echo Starting Bot #6 Engine (main.py)...
start "Bot #6 Engine" cmd /k "%PYTHON_CMD% bot6_crossfire\main.py"

echo Starting Bot #6 Web Dashboard on http://localhost:8506 ...
%STREAMLIT_CMD% run bot6_crossfire\panel.py --server.port 8506 --server.address 0.0.0.0
pause
