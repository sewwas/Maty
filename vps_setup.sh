#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# Profity AI — VPS Setup Script (Linux + Wine + Dual MT5)
#
# Run this ONCE on your VPS to:
#   1. Install Wine + dependencies
#   2. Create two isolated Wine prefixes
#   3. Install Python 3.11 + MetaTrader5 in each prefix
#   4. Download and install MT5 terminal in each prefix
#   5. Auto-login each MT5 with saved credentials
#
# Accounts:
#   Bot #1 → Wine Prefix ~/.wine_mt5_1 → Account #160142171 (Exness-MT5Real20)
#   Bot #2 → Wine Prefix ~/.wine_mt5_2 → Account #257515247 (Exness-MT5Real36)
#
# Usage:
#   chmod +x vps_setup.sh && ./vps_setup.sh
# ══════════════════════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Account credentials (hardcoded from your setup)
ACCOUNT_1_LOGIN="160142171"
ACCOUNT_1_PASSWORD="Asel@12345"
ACCOUNT_1_SERVER="Exness-MT5Real20"

ACCOUNT_2_LOGIN="257515247"
ACCOUNT_2_PASSWORD="Asel@12345"
ACCOUNT_2_SERVER="Exness-MT5Real36"

PREFIX_1="$HOME/.wine_mt5_1"
PREFIX_2="$HOME/.wine_mt5_2"

# Python installer URL (Windows x64)
PY_URL="https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PY_INSTALLER="/tmp/python-3.11.9-amd64.exe"

# MT5 installer URL (Exness)
MT5_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
MT5_INSTALLER="/tmp/mt5setup.exe"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✅ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️  $*${NC}"; }
err()  { echo -e "${RED}  ❌ $*${NC}"; }
step() { echo -e "\n${BLUE}── $* ──────────────────────────────────────────────────${NC}"; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Profity AI — VPS One-Time Setup (Wine + Dual MT5)      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Bot #1: Account #$ACCOUNT_1_LOGIN @ $ACCOUNT_1_SERVER"
echo "  Bot #2: Account #$ACCOUNT_2_LOGIN @ $ACCOUNT_2_SERVER"
echo ""

# ── Step 1: Install system dependencies ──────────────────────────────────────
step "Step 1: System Dependencies"

if command -v apt-get &>/dev/null; then
    sudo dpkg --add-architecture i386 2>/dev/null || true
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        wine wine64 wine32 winetricks \
        xvfb x11-utils \
        curl wget python3 python3-pip \
        cabextract p7zip-full \
        2>/dev/null && ok "APT packages installed" || warn "Some APT packages failed (may already be installed)"
elif command -v yum &>/dev/null; then
    sudo yum install -y wine xorg-x11-server-Xvfb curl wget python3 python3-pip \
        2>/dev/null && ok "YUM packages installed" || warn "Some YUM packages failed"
else
    warn "Unknown package manager — install wine, xvfb, python3 manually"
fi

# Start virtual display if not running
if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :0 -screen 0 1024x768x24 &
    export DISPLAY=:0
    sleep 2
    ok "Virtual display started (Xvfb :0)"
else
    export DISPLAY="${DISPLAY:-:0}"
    ok "Display already running: $DISPLAY"
fi

# Install streamlit on system python
pip3 install streamlit requests 2>/dev/null | tail -1 || true

# ── Step 2: Download installers ───────────────────────────────────────────────
step "Step 2: Download Installers"

if [ ! -f "$PY_INSTALLER" ]; then
    echo "  Downloading Python 3.11 (Windows x64)..."
    wget -q --show-progress -O "$PY_INSTALLER" "$PY_URL" && ok "Python 3.11 downloaded"
else
    ok "Python installer already exists: $PY_INSTALLER"
fi

if [ ! -f "$MT5_INSTALLER" ]; then
    echo "  Downloading MT5 installer..."
    wget -q --show-progress -O "$MT5_INSTALLER" "$MT5_URL" && ok "MT5 installer downloaded"
else
    ok "MT5 installer already exists: $MT5_INSTALLER"
fi

# ── Step 3: Setup Wine Prefix 1 ───────────────────────────────────────────────
step "Step 3: Wine Prefix 1 — Bot #1 (Account #$ACCOUNT_1_LOGIN)"

setup_prefix() {
    local prefix="$1"
    local login="$2"
    local password="$3"
    local server="$4"
    local port="$5"
    local label="Bot #$( [ "$port" = "8001" ] && echo 1 || echo 2 )"

    export WINEPREFIX="$prefix"
    export WINEARCH="win64"
    export WINEDEBUG="-all"

    if [ -f "$prefix/drive_c/Python311/python.exe" ] && \
       [ -f "$prefix/drive_c/Program Files/MetaTrader 5/terminal64.exe" ]; then
        ok "$label prefix already fully set up at $prefix — skipping"
        return 0
    fi

    echo "  Creating Wine prefix at $prefix..."
    mkdir -p "$prefix"
    WINEPREFIX="$prefix" WINEARCH="win64" WINEDEBUG="-all" \
        wine wineboot --init 2>/dev/null || true
    sleep 2

    # Install Visual C++ Runtime (required by MT5)
    echo "  Installing Visual C++ Runtime..."
    WINEPREFIX="$prefix" WINEDEBUG="-all" \
        winetricks -q vcrun2019 2>/dev/null | tail -1 || \
        warn "vcrun2019 install failed — MT5 might still work"

    # Install Python 3.11 for Windows in this prefix
    if [ ! -f "$prefix/drive_c/Python311/python.exe" ]; then
        echo "  Installing Python 3.11 in $label prefix..."
        WINEPREFIX="$prefix" WINEDEBUG="-all" \
            wine "$PY_INSTALLER" \
            /quiet InstallAllUsers=0 \
            TargetDir='C:\Python311' \
            PrependPath=1 2>/dev/null
        sleep 3
        if [ -f "$prefix/drive_c/Python311/python.exe" ]; then
            ok "Python 3.11 installed in $label"
        else
            warn "Python install may have failed — check manually"
        fi
    fi

    # Install MetaTrader5 Python package inside this prefix
    if [ -f "$prefix/drive_c/Python311/python.exe" ]; then
        echo "  Installing MetaTrader5 Python package..."
        WINEPREFIX="$prefix" WINEDEBUG="-all" \
            wine "$prefix/drive_c/Python311/python.exe" \
            -m pip install MetaTrader5 requests 2>/dev/null | tail -3 || true
        ok "MetaTrader5 pip package installed"
    fi

    # Install MT5 terminal
    if [ ! -f "$prefix/drive_c/Program Files/MetaTrader 5/terminal64.exe" ]; then
        echo "  Installing MT5 terminal in $label prefix..."
        WINEPREFIX="$prefix" WINEDEBUG="-all" \
            wine "$MT5_INSTALLER" /auto 2>/dev/null
        sleep 10
        if [ -f "$prefix/drive_c/Program Files/MetaTrader 5/terminal64.exe" ]; then
            ok "MT5 terminal installed in $label"
        else
            warn "MT5 install may need more time — check $prefix/drive_c/Program\ Files/"
        fi
    fi

    # Copy bridge config into the prefix's Z: drive (which maps to /)
    cp "$SCRIPT_DIR/bridge_config_${port}.json" "$prefix/drive_c/bridge_config_${port}.json" 2>/dev/null || true
    ok "$label prefix configured"
}

setup_prefix "$PREFIX_1" "$ACCOUNT_1_LOGIN" "$ACCOUNT_1_PASSWORD" "$ACCOUNT_1_SERVER" "8001"

# ── Step 4: Setup Wine Prefix 2 ───────────────────────────────────────────────
step "Step 4: Wine Prefix 2 — Bot #2 (Account #$ACCOUNT_2_LOGIN)"
setup_prefix "$PREFIX_2" "$ACCOUNT_2_LOGIN" "$ACCOUNT_2_PASSWORD" "$ACCOUNT_2_SERVER" "8002"

# ── Step 5: Create systemd service (optional) ─────────────────────────────────
step "Step 5: Create Systemd Auto-Start Service"

SERVICE_FILE="/etc/systemd/system/profity-bridges.service"
CURRENT_USER="$(whoami)"

if command -v systemctl &>/dev/null && [ "$CURRENT_USER" != "root" ] || [ -w /etc/systemd/system ]; then
    cat > /tmp/profity-bridges.service << EOF
[Unit]
Description=Profity AI — MT5 Bridge Services
After=network.target

[Service]
Type=forking
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
Environment=DISPLAY=:0
Environment=WINE_PREFIX_1=$PREFIX_1
Environment=WINE_PREFIX_2=$PREFIX_2
ExecStartPre=/usr/bin/Xvfb :0 -screen 0 1024x768x24 &
ExecStart=/bin/bash $SCRIPT_DIR/start_bridges.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    if [ -w /etc/systemd/system ]; then
        sudo cp /tmp/profity-bridges.service "$SERVICE_FILE"
        sudo systemctl daemon-reload
        sudo systemctl enable profity-bridges
        ok "Systemd service installed (profity-bridges)"
        echo "    Enable:  sudo systemctl enable profity-bridges"
        echo "    Start:   sudo systemctl start profity-bridges"
        echo "    Status:  sudo systemctl status profity-bridges"
    else
        warn "Cannot write to /etc/systemd/system — run as root to install service"
        echo "    Service file saved to: /tmp/profity-bridges.service"
    fi
fi

# ── Step 6: Final Summary ─────────────────────────────────────────────────────
step "Setup Complete!"
echo ""
echo "  Wine Prefix 1: $PREFIX_1"
echo "  Wine Prefix 2: $PREFIX_2"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Start the bridges:"
echo "     bash $SCRIPT_DIR/start_bridges.sh"
echo ""
echo "  2. Start the Streamlit app:"
echo "     streamlit run $SCRIPT_DIR/app.py \\"
echo "       --server.port 8501 \\"
echo "       --server.address 0.0.0.0 &"
echo ""
echo "  3. Open in browser:"
echo "     http://$(hostname -I | awk '{print $1}'):8501"
echo ""
echo "══════════════════════════════════════════════════════════"
