#!/usr/bin/env bash
# Profity AI — Launch Bot #3 Dashboard on Port 8503 (Linux VPS)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.venv/bin/streamlit" ]; then
    STREAMLIT_CMD="$ROOT_DIR/.venv/bin/streamlit"
else
    STREAMLIT_CMD="streamlit"
fi

echo "Starting Bot #3 Web Dashboard on port 8503..."
nohup $STREAMLIT_CMD run "$SCRIPT_DIR/panel.py" --server.port 8503 --server.address 0.0.0.0 --server.headless true > "$ROOT_DIR/streamlit_8503.log" 2>&1 &
echo "Bot #3 Dashboard launched: http://$(hostname -I | awk '{print $1}'):8503"
