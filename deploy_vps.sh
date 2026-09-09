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

pkill -f 'bot3_trend/trend_engine.py' 2>/dev/null || true
pkill -f 'bot3_trend/panel.py' 2>/dev/null || true
pkill -f 'manual_grid_desk.py' 2>/dev/null || true
sleep 2

mkdir -p $APP_DIR/logs

echo "Starting Bot #3 Trend Engine..."
nohup /root/Maty/.venv/bin/python /root/Maty/bot3_trend/trend_engine.py > /root/Maty/logs/bot3_engine.log 2>&1 &
echo "Bot #3 Engine started."

echo "Starting Bot #3 Web Dashboard (Port 8503)..."
nohup /root/Maty/.venv/bin/streamlit run /root/Maty/bot3_trend/panel.py --server.port 8503 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8503.log 2>&1 &
echo "Bot #3 Panel started."

echo "Starting Bot #2 Manual Grid Desk (Port 8502)..."
nohup /root/Maty/.venv/bin/streamlit run /root/Maty/manual_grid_desk.py --server.port 8502 --server.address 0.0.0.0 --server.headless true > /root/Maty/logs/streamlit_8502.log 2>&1 &
echo "Bot #2 Desk started."

sleep 3

echo ""
echo "=================================================================="
echo "  HEALTH & PORT VERIFICATION"
echo "=================================================================="
ss -tulnp | grep -E '8001|8002|8003|8501|8502|8503|8006'

echo ""
echo "SUCCESS: VPS Updated and all bot services are running!"
