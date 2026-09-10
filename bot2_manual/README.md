# 🕹️ Bot #2 — Manual Grid Desk & Autonomous 24/7 Engine

## Overview
Bot #2 is a dedicated precision trap and breakout grid system for **XAUUSD** (Exness Account `#257515247` on MT5 Bridge port `8002`).

## Architecture & Components
All necessary and needful components for Bot #2 are fully isolated within this directory:

- **`grid_engine.py`**: Standalone 24/7 background engine daemon. Runs as `bot2-engine.service` via systemd.
  - Monitors floating P&L every **50ms**.
  - Triggers **instant zero-latency auto-close** the exact millisecond Target Profit or Stop Loss is reached.
  - Executes regardless of whether a web browser is open.
- **`panel.py`**: Streamlit interactive control desk. Runs on port `8502` (`bot2-manual.service`).
  - Real-time chart, levels visualization, telemetry badge (`🟢 24/7 ENGINE ACTIVE`).
  - Action buttons: Instant Flatten All, Cancel Pending, Lock Center, Adjust Parameters.
- **`manual_state.json`**: Real-time state persistence (grid levels, risk bounds, telemetry, audit logs).
- **`start_bot2.sh`**: Linux VPS startup script.
- **`start_bot2.bat`**: Windows local development launcher.

## Systemd Services (VPS)
- **Engine Daemon**: `systemctl status bot2-engine.service`
- **Web Dashboard**: `systemctl status bot2-manual.service`
- **Live Logs**: `tail -f /root/bot2_engine.log`
