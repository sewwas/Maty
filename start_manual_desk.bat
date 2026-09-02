@echo off
title Profity AI — Manual Grid Desk (Port 8502)
echo.
echo  =========================================================
echo   Profity AI ^| Manual Grid Desk
echo   Symbol  : XAUUSD (Gold)
echo   Magic   : 777001 (Isolated from Auto Bot)
echo   Port    : 8502
echo  =========================================================
echo.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m streamlit run manual_grid_desk.py ^
        --server.port 8502 ^
        --server.address 0.0.0.0 ^
        --server.headless true ^
        --browser.gatherUsageStats false ^
        --theme.base dark ^
        --theme.backgroundColor "#09090b" ^
        --theme.primaryColor "#c084fc"
) else (
    python -m streamlit run manual_grid_desk.py ^
        --server.port 8502 ^
        --server.address 0.0.0.0 ^
        --server.headless true ^
        --browser.gatherUsageStats false ^
        --theme.base dark ^
        --theme.backgroundColor "#09090b" ^
        --theme.primaryColor "#c084fc"
)

pause
