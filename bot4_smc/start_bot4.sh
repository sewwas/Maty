#!/usr/bin/env bash
# Start Bot #4 Web Dashboard on Linux/VPS
cd "$(dirname "$0")/.."

if [ -f ".venv/bin/streamlit" ]; then
    STREAMLIT_CMD=".venv/bin/streamlit"
else
    STREAMLIT_CMD="streamlit"
fi

echo "Starting Bot #4 Web Dashboard on port 8504..."
$STREAMLIT_CMD run bot4_smc/panel.py --server.port 8504 --server.address 0.0.0.0
