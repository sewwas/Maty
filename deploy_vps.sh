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
pkill -f 'hub.py' 2>/dev/null || true
pkill -f 'bot3_trend/trend_engine.py' 2>/dev/null || true
pkill -f 'bot3_trend/panel.py' 2>/dev/null || true
pkill -f 'manual_grid_desk.py' 2>/dev/null || true
pkill -f 'streamlit run /root/Maty/app.py' 2>/dev/null || true

# Force release any locked dashboard ports
fuser -k 80/tcp 8501/tcp 8502/tcp 8503/tcp 2>/dev/null || true
sleep 2

mkdir -p $APP_DIR/logs

echo "Starting Port 80 Command Center Portal (hub.py)..."
nohup $PYTHON_BIN /root/Maty/hub.py > /root/Maty/logs/hub.log 2>&1 &
echo "Command Center Portal started."

echo "Starting Bot #1 Auto Grid Dashboard (Port 8501)..."
nohup $STREAMLIT_BIN run /root/Maty/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8501.log 2>&1 &
echo "Bot #1 Dashboard started."

echo "Starting Bot #2 Manual Grid Desk (Port 8502)..."
nohup $STREAMLIT_BIN run /root/Maty/manual_grid_desk.py --server.port 8502 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8502.log 2>&1 &
echo "Bot #2 Desk started."

echo "Starting Bot #3 Trend Engine..."
nohup $PYTHON_BIN /root/Maty/bot3_trend/trend_engine.py > /root/Maty/logs/bot3_engine.log 2>&1 &
echo "Bot #3 Engine started."

echo "Starting Bot #3 Web Dashboard (Port 8503)..."
nohup $STREAMLIT_BIN run /root/Maty/bot3_trend/panel.py --server.port 8503 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8503.log 2>&1 &
echo "Bot #3 Panel started."

sleep 3

echo ""
echo "=================================================================="
echo "  HEALTH & PORT VERIFICATION"
echo "=================================================================="
ss -tulnp | grep -E '80 |8001|8002|8003|8501|8502|8503'

echo ""
echo "SUCCESS: VPS Updated and all bot services are running!"
