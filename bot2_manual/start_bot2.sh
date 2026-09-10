#!/usr/bin/env bash
# ==============================================================================
# Profity AI — Launch Bot #2 (Manual Grid Desk + 24/7 Engine) on Linux VPS
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p "$ROOT_DIR/logs"

# Detect python
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$ROOT_DIR/.venv/bin/python"
    STREAMLIT_CMD="$ROOT_DIR/.venv/bin/streamlit"
else
    PYTHON_CMD="python3"
    STREAMLIT_CMD="streamlit"
fi

echo "=================================================================="
echo " Starting Bot #2: Manual Grid Desk (Port 8502 & Engine)"
echo "=================================================================="

# 1. Start 24/7 Autonomous Grid Engine Daemon (if not already running via systemd)
if ! pgrep -f "bot2_manual/grid_engine.py" > /dev/null; then
    echo "Starting 24/7 Grid Engine Daemon..."
    nohup $PYTHON_CMD "$SCRIPT_DIR/grid_engine.py" > "$ROOT_DIR/bot2_engine.log" 2>&1 &
    echo "  ✅ 24/7 Grid Engine running (PID: $!)"
else
    echo "  ℹ️  24/7 Grid Engine is already running."
fi

# 2. Start Streamlit Web Dashboard on port 8502
if ! pgrep -f "bot2_manual/panel.py" > /dev/null; then
    echo "Starting Streamlit Web Dashboard on port 8502..."
    nohup $STREAMLIT_CMD run "$SCRIPT_DIR/panel.py" --server.port 8502 --server.address 0.0.0.0 --server.headless true > "$ROOT_DIR/logs/streamlit_8502.log" 2>&1 &
    echo "  ✅ Web Dashboard running on http://$(hostname -I | awk '{print $1}'):8502"
else
    echo "  ℹ️  Web Dashboard already running on port 8502."
fi

echo "=================================================================="
