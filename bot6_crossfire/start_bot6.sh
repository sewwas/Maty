#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit

echo "Starting Bot #6 Web Dashboard (Port 8506)..."
nohup streamlit run bot6_crossfire/panel.py --server.port 8506 --server.address 0.0.0.0 --server.headless true > bot6_crossfire/panel.log 2>&1 &

echo "Starting Bot #6 Engine..."
nohup python3 bot6_crossfire/main.py > bot6_crossfire/engine.log 2>&1 &

echo "Bot #6 started in background."
