@echo off
title Profity AI — Bot #4 SMC Liquidity Hunter (Port 8504)
echo ===================================================================
echo     Profity AI — Bot #4: SMC Liquidity Hunter (Port 8504)
echo ===================================================================
cd /d "%~dp0\.."

if exist .venv\Scripts\streamlit.exe (
    set STREAMLIT_CMD=.venv\Scripts\streamlit.exe
) else (
    set STREAMLIT_CMD=streamlit
)

echo Starting Bot #4 Web Dashboard on http://localhost:8504 ...
%STREAMLIT_CMD% run bot4_smc\panel.py --server.port 8504 --server.address 0.0.0.0
pause
