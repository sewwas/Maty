#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_CMD="python3"
STREAMLIT_CMD="streamlit"

if [ -f "$SCRIPT_DIR/../.venv/bin/python3" ]; then
    PYTHON_CMD="$SCRIPT_DIR/../.venv/bin/python3"
    STREAMLIT_CMD="$SCRIPT_DIR/../.venv/bin/streamlit"
fi

echo "Starting Bot #5 AI Engine Daemon..."
nohup $PYTHON_CMD "$SCRIPT_DIR/ai_engine.py" > "$SCRIPT_DIR/bot5_engine.log" 2>&1 &

echo "Starting Bot #5 Streamlit Dashboard on port 8505..."
$STREAMLIT_CMD run "$SCRIPT_DIR/panel.py" --server.port 8505 --server.address 0.0.0.0
