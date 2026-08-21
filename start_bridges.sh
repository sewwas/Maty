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
WINE_PREFIX_1="${WINE_PREFIX_1:-$HOME/.wine_mt5_1}"
WINE_PREFIX_2="${WINE_PREFIX_2:-$HOME/.wine_mt5_2}"

# Wine Python path inside each prefix (Wine Python 3.x in the prefix)
WINE_PYTHON_1="${WINE_PYTHON_1:-$WINE_PREFIX_1/drive_c/Python311/python.exe}"
WINE_PYTHON_2="${WINE_PYTHON_2:-$WINE_PREFIX_2/drive_c/Python311/python.exe}"

# MT5 terminal paths inside each Wine prefix
MT5_PATH_1="${MT5_PATH_1:-C:\\\\Program Files\\\\MetaTrader 5\\\\terminal64.exe}"
MT5_PATH_2="${MT5_PATH_2:-C:\\\\Program Files\\\\MetaTrader 5\\\\terminal64.exe}"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║      Profity AI — Dual MT5 Bridge Launcher (VPS)         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Wine Prefix 1 : $WINE_PREFIX_1"
echo "  Wine Prefix 2 : $WINE_PREFIX_2"
echo ""

# ── Sanity Checks ─────────────────────────────────────────────────────────────
if ! command -v wine &>/dev/null; then
    echo "[ERROR] wine not found. Run ./vps_setup.sh first."
    exit 1
fi

if [ ! -f "$BRIDGE_SCRIPT" ]; then
    echo "[ERROR] wine_mt5_bridge.py not found at: $BRIDGE_SCRIPT"
    exit 1
fi

_check_prefix() {
    local prefix="$1" label="$2"
    if [ ! -d "$prefix" ]; then
        echo "[WARN] $label Wine prefix not found: $prefix"
        echo "       Run ./vps_setup.sh to set up Wine prefixes with MT5."
        echo ""
        return 1
    fi
    return 0
}

_check_prefix "$WINE_PREFIX_1" "Bot #1" || true
_check_prefix "$WINE_PREFIX_2" "Bot #2" || true

# Config file check
if [ ! -f "$SCRIPT_DIR/bridge_config_8001.json" ]; then
    echo "[WARN] bridge_config_8001.json missing — bridge will start without saved credentials."
fi
if [ ! -f "$SCRIPT_DIR/bridge_config_8002.json" ]; then
    echo "[WARN] bridge_config_8002.json missing — bridge will start without saved credentials."
fi

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
        "DISPLAY=${DISPLAY:-:0}"
        "PORT=$port"
        "WINE_BRIDGE_PORT=$port"
        "MT5_PATH=$mt5_path"
    )

    # Determine how to run the bridge:
    # Option A: Wine Python exists in prefix → use it (MetaTrader5 works natively)
    # Option B: Fallback to system Python3 (bridge uses REST-only mode via port)
    if [ -f "$prefix/drive_c/Python311/python.exe" ]; then
        env "${bridge_env[@]}" nohup wine "$wine_py" \
            "$(winepath -w "$BRIDGE_SCRIPT" 2>/dev/null || echo "Z:$BRIDGE_SCRIPT")" \
            "$port" > "$log_file" 2>&1 &
    elif [ -f "$prefix/drive_c/Python39/python.exe" ]; then
        local alt_py="$prefix/drive_c/Python39/python.exe"
        env "${bridge_env[@]}" nohup wine "$alt_py" \
            "$(winepath -w "$BRIDGE_SCRIPT" 2>/dev/null || echo "Z:$BRIDGE_SCRIPT")" \
            "$port" > "$log_file" 2>&1 &
    else
        # Fallback: try system python3 (works if running on same machine without Wine)
        echo "  [WARN] No Wine Python found in $prefix — using system python3 (simulation mode)"
        env "${bridge_env[@]}" nohup python3 "$BRIDGE_SCRIPT" \
            "$port" > "$log_file" 2>&1 &
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
