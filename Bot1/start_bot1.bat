@echo off
cd /d "%~dp0\.."
streamlit run Bot1\panel.py --server.port 8501
pause
