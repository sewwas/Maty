#!/usr/bin/env bash
set -e
APP_DIR=/root/Maty
cd $APP_DIR

echo ==================================================================
echo  PULLING LATEST CODE FROM GITHUB
echo ==================================================================
git fetch origin main
git reset --hard origin/main
git log -n 1 --oneline

echo ""
echo "=================================================================="
echo "  RESTARTING BOT & DASHBOARD SERVICES"
echo "=================================================================="

PYTHON_BIN=$(command -v python3 || echo "/usr/bin/python3")
STREAMLIT_BIN=$(command -v streamlit || echo "/usr/local/bin/streamlit")

echo "Stopping previous services..."
pkill -9 -f 'app.py' 2>/dev/null || true
pkill -9 -f 'sunrise_engine.py' 2>/dev/null || true
pkill -9 -f 'Bot1' 2>/dev/null || true
pkill -9 -f 'hub.py' 2>/dev/null || true
pkill -9 -f 'bot3_trend' 2>/dev/null || true
pkill -9 -f 'bot4_smc' 2>/dev/null || true
pkill -9 -f 'smc_engine.py' 2>/dev/null || true
pkill -9 -f 'bot5_ai' 2>/dev/null || true
pkill -9 -f 'ai_engine.py' 2>/dev/null || true
pkill -9 -f 'mt5-ai-xauusd-trader' 2>/dev/null || true
pkill -9 -f 'bot2_manual' 2>/dev/null || true
pkill -9 -f 'grid_engine.py' 2>/dev/null || true
pkill -9 -f 'manual_grid_desk.py' 2>/dev/null || true
pkill -9 -f 'bot6_crossfire' 2>/dev/null || true
pkill -9 -f 'crossfire_engine.py' 2>/dev/null || true
pkill -9 -f 'streamlit' 2>/dev/null || true

# Force release any locked dashboard ports
fuser -k -9 80/tcp 8501/tcp 8502/tcp 8503/tcp 8504/tcp 8505/tcp 8506/tcp 2>/dev/null || true
sleep 2

# Wait until ports are actually free
for port in 80 8501 8502 8503 8504 8505 8506; do
    while fuser $port/tcp 2>/dev/null; do
        echo "Waiting for port $port to clear..."
        fuser -k -9 $port/tcp 2>/dev/null || true
        sleep 1
    done
done

mkdir -p $APP_DIR/logs

echo "Starting Port 80 Command Center Portal (hub.py)..."
nohup $PYTHON_BIN /root/Maty/hub.py > /root/Maty/logs/hub.log 2>&1 &
echo "Command Center Portal started."

if systemctl is-active bot1.service >/dev/null 2>&1 || systemctl is-enabled bot1.service >/dev/null 2>&1; then
    echo "Restarting Bot #1 via systemd..."
    systemctl restart bot1.service
else
    echo "Starting Bot #1 Sunrise Engine Daemon..."
    nohup $PYTHON_BIN /root/Maty/Bot1/sunrise_engine.py > /root/Maty/logs/bot1_engine.log 2>&1 &
    echo "Bot #1 Engine started."

    echo "Starting Bot #1 Sunrise Dashboard (Port 8501)..."
    nohup $STREAMLIT_BIN run /root/Maty/Bot1/panel.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8501.log 2>&1 &
    echo "Bot #1 Dashboard started."
fi

if systemctl is-active bot2-engine.service >/dev/null 2>&1 || systemctl is-enabled bot2-engine.service >/dev/null 2>&1; then
    echo "Restarting Bot #2 24/7 Grid Engine via systemd..."
    systemctl restart bot2-engine.service
else
    echo "Starting Bot #2 24/7 Grid Engine..."
    nohup $PYTHON_BIN /root/Maty/bot2_manual/grid_engine.py > /root/Maty/logs/bot2_engine.log 2>&1 &
    echo "Bot #2 Engine started."
fi

if systemctl is-active bot2-manual.service >/dev/null 2>&1 || systemctl is-enabled bot2-manual.service >/dev/null 2>&1; then
    echo "Restarting Bot #2 Manual Grid Desk (Port 8502) via systemd..."
    systemctl restart bot2-manual.service
else
    echo "Starting Bot #2 Manual Grid Desk (Port 8502)..."
    nohup $STREAMLIT_BIN run /root/Maty/bot2_manual/panel.py --server.port 8502 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8502.log 2>&1 &
    echo "Bot #2 Desk started."
fi

echo "Starting Bot #3 Trend Engine..."
nohup $PYTHON_BIN /root/Maty/bot3_trend/trend_engine.py > /root/Maty/logs/bot3_engine.log 2>&1 &
echo "Bot #3 Engine started."

echo "Starting Bot #3 Web Dashboard (Port 8503)..."
nohup $STREAMLIT_BIN run /root/Maty/bot3_trend/panel.py --server.port 8503 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8503.log 2>&1 &
echo "Bot #3 Panel started."

echo "Starting Bot #4 SMC Engine..."
nohup $PYTHON_BIN /root/Maty/bot4_smc/smc_engine.py > /root/Maty/logs/bot4_engine.log 2>&1 &
echo "Bot #4 Engine started."

echo "Starting Bot #4 Web Dashboard (Port 8504)..."
nohup $STREAMLIT_BIN run /root/Maty/bot4_smc/panel.py --server.port 8504 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8504.log 2>&1 &
echo "Bot #4 Panel started."

echo "Starting Bot #5 AI Engine..."
nohup $PYTHON_BIN /root/Maty/bot5_ai/ai_engine.py > /root/Maty/logs/bot5_engine.log 2>&1 &
echo "Bot #5 Engine started."

echo "Starting Bot #5 Web Dashboard (Port 8505)..."
nohup $STREAMLIT_BIN run /root/Maty/bot5_ai/panel.py --server.port 8505 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8505.log 2>&1 &
echo "Bot #5 Panel started."

sleep 3

echo ""
echo "=================================================================="
echo "  HEALTH & PORT VERIFICATION"
echo "=================================================================="
ss -tulnp | grep -E '80 |8001|8002|8003|8004|8005|8501|8502|8503|8504|8505'

echo ""
echo "SUCCESS: VPS Updated and all bot services are running!"
