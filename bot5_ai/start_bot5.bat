@echo off
title Bot #5 — AI/ML Neural Trader
color 0D

echo.
echo ==================================================================
echo         Profity AI — Launching Bot #5 (AI/ML Neural Trader)
echo ==================================================================
echo.

REM Determine python and streamlit commands
set PYTHON_CMD=python
set STREAMLIT_CMD=streamlit
if exist "..\.venv\Scripts\python.exe" (
    set PYTHON_CMD=..\.venv\Scripts\python.exe
    set STREAMLIT_CMD=..\.venv\Scripts\streamlit.exe
) else if exist ".venv\Scripts\python.exe" (
    set PYTHON_CMD=.venv\Scripts\python.exe
    set STREAMLIT_CMD=.venv\Scripts\streamlit.exe
)

echo Starting Bot #5 AI Engine Daemon...
start "Bot #5 AI Engine" cmd /k "%PYTHON_CMD% ai_engine.py"

echo Starting Bot #5 Streamlit Dashboard on port 8505...
%STREAMLIT_CMD% run panel.py --server.port 8505 --server.address 0.0.0.0

pause
