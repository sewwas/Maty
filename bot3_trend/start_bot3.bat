@echo off
title Profity AI — Bot #3 Trend Runner (Port 8503)
echo ===================================================================
echo     Profity AI — Bot #3: Trend Breakout Dashboard (Port 8503)
echo ===================================================================
cd /d "%~dp0\.."

if exist .venv\Scripts\streamlit.exe (
    set STREAMLIT_CMD=.venv\Scripts\streamlit.exe
) else (
    set STREAMLIT_CMD=streamlit
)

echo Starting Bot #3 Web Dashboard on http://localhost:8503 ...
%STREAMLIT_CMD% run bot3_trend\panel.py --server.port 8503 --server.address 0.0.0.0
pause
