#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Profity AI — Start Both MT5 Bridges (Linux VPS + Wine)
#
# Architecture:
#   Wine Prefix 1 (~/.wine_mt5_1)  →  MT5 Account #160142171  →  Bridge :8001
#   Wine Prefix 2 (~/.wine_mt5_2)  →  MT5 Account #257515247  →  Bridge :8002
#
# Usage:
#   chmod +x start_bridges.sh
#   ./start_bridges.sh
#
# Prerequisites: Run vps_setup.sh ONCE first to install Wine + MT5 in each prefix.
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_SCRIPT="$SCRIPT_DIR/wine_mt5_bridge.py"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── Wine Prefix Configuration ─────────────────────────────────────────────────
# Auto-detect existing Wine prefix and Python
_DEFAULT_PREFIX="$HOME/.wine"
if [ -d "$HOME/.wine_mt5_1" ]; then
    WINE_PREFIX_1="$HOME/.wine_mt5_1"
else
    WINE_PREFIX_1="$_DEFAULT_PREFIX"
fi

if [ -d "$HOME/.wine_mt5_2" ]; then
    WINE_PREFIX_2="$HOME/.wine_mt5_2"
else
    WINE_PREFIX_2="$_DEFAULT_PREFIX"
fi

# Find Wine Python (checks Program Files/Python311 and Python311 in prefix)
_find_wine_py() {
    local p="$1"
    for py in \
        "$p/drive_c/Program Files/Python311/python.exe" \
        "$p/drive_c/Python311/python.exe" \
        "$p/drive_c/Program Files/Python39/python.exe" \
        "$p/drive_c/Python39/python.exe" \
        "$p/drive_c/Python310/python.exe"; do
        if [ -f "$py" ]; then
            echo "$py"
            return 0
        fi
    done
    return 1
}

WINE_PYTHON_1=$(_find_wine_py "$WINE_PREFIX_1" || echo "$WINE_PREFIX_1/drive_c/Program Files/Python311/python.exe")
WINE_PYTHON_2=$(_find_wine_py "$WINE_PREFIX_2" || echo "$WINE_PREFIX_2/drive_c/Program Files/Python311/python.exe")

# MT5 terminal paths
MT5_PATH_1="C:\\Program Files\\MetaTrader 5\\terminal64.exe"
MT5_PATH_2="C:\\Program Files\\MetaTrader 5_2\\terminal64.exe"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║      Profity AI — Dual MT5 Bridge Launcher (VPS)         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Wine Prefix 1 : $WINE_PREFIX_1"
echo "  Wine Prefix 2 : $WINE_PREFIX_2"
echo "  Wine Python 1 : $WINE_PYTHON_1"
echo "  Wine Python 2 : $WINE_PYTHON_2"
echo "  Terminal 1    : $MT5_PATH_1"
echo "  Terminal 2    : $MT5_PATH_2"
echo ""

# ── Kill existing bridge processes ────────────────────────────────────────────
echo "Stopping any existing bridge processes..."
pkill -f "wine_mt5_bridge.py 8001" 2>/dev/null || true
pkill -f "wine_mt5_bridge.py 8002" 2>/dev/null || true
sleep 1

# ── Helper: start a bridge inside its Wine prefix ────────────────────────────
_start_bridge() {
    local port="$1"
    local prefix="$2"
    local wine_py="$3"
    local mt5_path="$4"
    local log_file="$LOG_DIR/bridge_${port}.log"

    echo "Starting Bridge #$([ "$port" = "8001" ] && echo 1 || echo 2) on port $port..."

    # Build env vars for the bridge process
    local bridge_env=(
        "WINEPREFIX=$prefix"
        "WINEDEBUG=-all"
        "DISPLAY=${DISPLAY:-:1}"
        "PORT=$port"
        "WINE_BRIDGE_PORT=$port"
        "MT5_PATH=$mt5_path"
    )

    if [ -f "$wine_py" ]; then
        env "${bridge_env[@]}" nohup wine "$wine_py" \
            "$(winepath -w "$BRIDGE_SCRIPT" 2>/dev/null || echo "Z:$BRIDGE_SCRIPT")" \
            "$port" > "$log_file" 2>&1 &
    else
        # Fallback: try direct wine python command
        echo "  [WARN] Wine Python not at $wine_py — attempting wine python execution"
        env "${bridge_env[@]}" nohup wine python "$BRIDGE_SCRIPT" "$port" > "$log_file" 2>&1 &
    fi

    local pid=$!
    echo "$pid" > "$LOG_DIR/bridge_${port}.pid"
    echo "  PID: $pid  |  Log: $log_file"
}

# ── Start both bridges ────────────────────────────────────────────────────────
_start_bridge "8001" "$WINE_PREFIX_1" "$WINE_PYTHON_1" "$MT5_PATH_1"
sleep 2
_start_bridge "8002" "$WINE_PREFIX_2" "$WINE_PYTHON_2" "$MT5_PATH_2"

echo ""
echo "Waiting 8s for MT5 to initialize..."
sleep 8

# ── Health Check ──────────────────────────────────────────────────────────────
echo ""
echo "── Health Check ──────────────────────────────────────────"

_check_bridge() {
    local port="$1" label="$2"
    if curl -sf "http://127.0.0.1:${port}/health" > /dev/null 2>&1; then
        local info
        info=$(curl -s "http://127.0.0.1:${port}/account" 2>/dev/null)
        local login server balance
        login=$(echo "$info" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('login','?'))" 2>/dev/null || echo "?")
        server=$(echo "$info" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('server','?'))" 2>/dev/null || echo "?")
        balance=$(echo "$info" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('balance','?'))" 2>/dev/null || echo "?")
        echo "  ✅ $label (port $port) → Account #$login | $server | Balance: \$$balance"
    else
        echo "  ❌ $label (port $port) → NOT RESPONDING"
        echo "     Check log: $LOG_DIR/bridge_${port}.log"
        echo "     Last 5 lines:"
        tail -5 "$LOG_DIR/bridge_${port}.log" 2>/dev/null | sed 's/^/       /'
    fi
}

_check_bridge "8001" "Bot #1 (Fx03 #160142171)"
_check_bridge "8002" "Bot #2 (Fx02 #257515247)"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "Logs:  tail -f $LOG_DIR/bridge_8001.log"
echo "       tail -f $LOG_DIR/bridge_8002.log"
echo ""
echo "Start the app:"
echo "  streamlit run $SCRIPT_DIR/app.py --server.port 8501 --server.address 0.0.0.0 &"
echo "══════════════════════════════════════════════════════════"
echo ""
