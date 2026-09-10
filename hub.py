#!/usr/bin/env python3
"""
Profity AI - Unified VPS Web Portal & Multi-Bot Command Center (Port 80)
Features:
- Live Portfolio Aggregate Metrics
- Multi-Bot Real-Time Profit Comparison Matrix (Today / 7D / 30D / All-Time)
- Side-by-Side Win Rate, Balance, Equity, and Floating P&L Analytics
- Direct Links & Live Status to all 3 Trading Desks (:8501, :8502, :8503)
"""

import http.server
import socket
import socketserver
import json
import urllib.parse
import urllib.request
import time
import datetime
from http import HTTPStatus
from concurrent.futures import ThreadPoolExecutor

PORT = 80

BOT_CONFIGS = [
    {
        "id": 1,
        "name": "Bot #1 — Auto Grid",
        "tag": "AUTO GRID",
        "strategy": "Breakout Grid Engine (Runner Mode)",
        "bridge_port": 8001,
        "panel_port": 8501,
        "default_acc": 160142171,
        "server": "Exness-MT5Real20",
        "color": "#38bdf8",
        "icon": "⚡"
    },
    {
        "id": 2,
        "name": "Bot #2 — Manual Grid Desk",
        "tag": "MANUAL DESK",
        "strategy": "Precision Trap Deployment & Cycle Scalping",
        "bridge_port": 8002,
        "panel_port": 8502,
        "default_acc": 257515247,
        "server": "Exness-MT5Real36",
        "color": "#f59e0b",
        "icon": "🕹️"
    },
    {
        "id": 3,
        "name": "Bot #3 — London Asian Trend",
        "tag": "TREND RUNNER",
        "strategy": "Asian Box Breakout & London Momentum",
        "bridge_port": 8003,
        "panel_port": 8503,
        "default_acc": 257499962,
        "server": "Exness-MT5Real36",
        "color": "#a855f7",
        "icon": "📈"
    },
    {
        "id": 4,
        "name": "Bot #4 — SMC Liquidity Hunter",
        "tag": "SMC REVERSAL",
        "strategy": "Liquidity Sweep & FVG Reversal (Turtle Soup)",
        "bridge_port": 8004,
        "panel_port": 8504,
        "default_acc": 257515248,
        "server": "Exness-MT5Real36",
        "color": "#10b981",
        "icon": "🎯"
    }
]

# In-memory cache for live metrics to protect MT5 bridges
_metrics_cache = {"timestamp": 0.0, "data": None}
CACHE_TTL = 2.5  # seconds

def is_port_listening(port, host="127.0.0.1", timeout=0.4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def fetch_single_bot_metrics(cfg):
    bport = cfg["bridge_port"]
    now = time.time()
    today_midnight = datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp()
    seven_days_ago = now - (7 * 86400)
    thirty_days_ago = now - (30 * 86400)

    res = {
        "id": cfg["id"],
        "name": cfg["name"],
        "tag": cfg["tag"],
        "strategy": cfg["strategy"],
        "bridge_port": bport,
        "panel_port": cfg["panel_port"],
        "color": cfg["color"],
        "icon": cfg["icon"],
        "connected": False,
        "account": cfg["default_acc"],
        "server": cfg["server"],
        "currency": "USC",
        "balance": 0.0,
        "equity": 0.0,
        "floating_pnl": 0.0,
        "active_positions": 0,
        "pnl_today": 0.0,
        "pnl_7d": 0.0,
        "pnl_30d": 0.0,
        "pnl_all": 0.0,
        "trades_today": 0,
        "trades_7d": 0,
        "trades_30d": 0,
        "trades_all": 0,
        "wins_today": 0,
        "wins_7d": 0,
        "wins_30d": 0,
        "wins_all": 0,
        "win_rate_today": 0.0,
        "win_rate_7d": 0.0,
        "win_rate_30d": 0.0,
        "win_rate_all": 0.0,
        "profit_factor_30d": 1.0,
        "best_trade_30d": 0.0,
        "worst_trade_30d": 0.0
    }

    try:
        # 1. Fetch Account Info
        req_acc = urllib.request.Request(f"http://127.0.0.1:{bport}/account", headers={"User-Agent": "HubCollector"})
        with urllib.request.urlopen(req_acc, timeout=1.8) as resp:
            acc_data = json.loads(resp.read().decode("utf-8"))
            res["connected"] = acc_data.get("connected", False)
            res["account"] = acc_data.get("login", cfg["default_acc"])
            res["server"] = acc_data.get("server", cfg["server"])
            res["currency"] = acc_data.get("currency", "USC")
            res["balance"] = round(float(acc_data.get("balance", 0.0)), 2)
            res["equity"] = round(float(acc_data.get("equity", 0.0)), 2)
    except Exception:
        pass

    try:
        # 2. Fetch Open Positions
        req_pos = urllib.request.Request(f"http://127.0.0.1:{bport}/positions", headers={"User-Agent": "HubCollector"})
        with urllib.request.urlopen(req_pos, timeout=1.8) as resp:
            pos_data = json.loads(resp.read().decode("utf-8")).get("positions", [])
            res["active_positions"] = len(pos_data)
            res["floating_pnl"] = round(sum(float(p.get("profit", 0.0)) for p in pos_data), 2)
    except Exception:
        pass

    try:
        # 3. Fetch Deal History (Last 60 Days)
        req_hist = urllib.request.Request(f"http://127.0.0.1:{bport}/history?days=60", headers={"User-Agent": "HubCollector"})
        with urllib.request.urlopen(req_hist, timeout=2.5) as resp:
            deals = json.loads(resp.read().decode("utf-8")).get("deals", [])
            trades = [d for d in deals if (d.get("entry") == 1 or d.get("profit", 0) != 0) and d.get("symbol")]

            gross_profit_30d = 0.0
            gross_loss_30d = 0.0

            for d in trades:
                t_time = float(d.get("time", 0))
                pnl = float(d.get("profit", 0.0)) + float(d.get("swap", 0.0)) + float(d.get("commission", 0.0))
                is_win = pnl > 0

                res["pnl_all"] += pnl
                res["trades_all"] += 1
                if is_win:
                    res["wins_all"] += 1

                if t_time >= thirty_days_ago:
                    res["pnl_30d"] += pnl
                    res["trades_30d"] += 1
                    if is_win:
                        res["wins_30d"] += 1
                        gross_profit_30d += pnl
                    else:
                        gross_loss_30d += abs(pnl)

                    if pnl > res["best_trade_30d"]:
                        res["best_trade_30d"] = round(pnl, 2)
                    if pnl < res["worst_trade_30d"]:
                        res["worst_trade_30d"] = round(pnl, 2)

                if t_time >= seven_days_ago:
                    res["pnl_7d"] += pnl
                    res["trades_7d"] += 1
                    if is_win:
                        res["wins_7d"] += 1

                if t_time >= today_midnight:
                    res["pnl_today"] += pnl
                    res["trades_today"] += 1
                    if is_win:
                        res["wins_today"] += 1

            res["pnl_all"] = round(res["pnl_all"], 2)
            res["pnl_30d"] = round(res["pnl_30d"], 2)
            res["pnl_7d"] = round(res["pnl_7d"], 2)
            res["pnl_today"] = round(res["pnl_today"], 2)

            if res["trades_today"] > 0:
                res["win_rate_today"] = round((res["wins_today"] / res["trades_today"]) * 100, 1)
            if res["trades_7d"] > 0:
                res["win_rate_7d"] = round((res["wins_7d"] / res["trades_7d"]) * 100, 1)
            if res["trades_30d"] > 0:
                res["win_rate_30d"] = round((res["wins_30d"] / res["trades_30d"]) * 100, 1)
            if res["trades_all"] > 0:
                res["win_rate_all"] = round((res["wins_all"] / res["trades_all"]) * 100, 1)

            if gross_loss_30d > 0:
                res["profit_factor_30d"] = round(gross_profit_30d / gross_loss_30d, 2)
            elif gross_profit_30d > 0:
                res["profit_factor_30d"] = 9.99
    except Exception:
        pass

    return res

def get_all_bot_metrics():
    global _metrics_cache
    now = time.time()
    if _metrics_cache["data"] is not None and (now - _metrics_cache["timestamp"] < CACHE_TTL):
        return _metrics_cache["data"]

    with ThreadPoolExecutor(max_workers=3) as executor:
        bots_metrics = list(executor.map(fetch_single_bot_metrics, BOT_CONFIGS))

    total_balance = sum(b["balance"] for b in bots_metrics)
    total_equity = sum(b["equity"] for b in bots_metrics)
    total_floating = sum(b["floating_pnl"] for b in bots_metrics)
    total_pnl_today = sum(b["pnl_today"] for b in bots_metrics)
    total_pnl_7d = sum(b["pnl_7d"] for b in bots_metrics)
    total_pnl_30d = sum(b["pnl_30d"] for b in bots_metrics)
    total_pnl_all = sum(b["pnl_all"] for b in bots_metrics)

    total_trades_today = sum(b["trades_today"] for b in bots_metrics)
    total_wins_today = sum(b["wins_today"] for b in bots_metrics)
    win_rate_today = round((total_wins_today / total_trades_today * 100), 1) if total_trades_today > 0 else 0.0

    total_trades_30d = sum(b["trades_30d"] for b in bots_metrics)
    total_wins_30d = sum(b["wins_30d"] for b in bots_metrics)
    win_rate_30d = round((total_wins_30d / total_trades_30d * 100), 1) if total_trades_30d > 0 else 0.0

    total_trades_all = sum(b["trades_all"] for b in bots_metrics)
    total_wins_all = sum(b["wins_all"] for b in bots_metrics)
    win_rate_all = round((total_wins_all / total_trades_all * 100), 1) if total_trades_all > 0 else 0.0

    active_positions_count = sum(b["active_positions"] for b in bots_metrics)

    portfolio = {
        "total_balance_usc": round(total_balance, 2),
        "total_equity_usc": round(total_equity, 2),
        "total_balance_usd": round(total_balance / 100.0, 2),
        "total_equity_usd": round(total_equity / 100.0, 2),
        "total_floating_usc": round(total_floating, 2),
        "total_floating_usd": round(total_floating / 100.0, 2),
        "active_positions": active_positions_count,
        "pnl_today_usc": round(total_pnl_today, 2),
        "pnl_today_usd": round(total_pnl_today / 100.0, 2),
        "pnl_7d_usc": round(total_pnl_7d, 2),
        "pnl_7d_usd": round(total_pnl_7d / 100.0, 2),
        "pnl_30d_usc": round(total_pnl_30d, 2),
        "pnl_30d_usd": round(total_pnl_30d / 100.0, 2),
        "pnl_all_usc": round(total_pnl_all, 2),
        "pnl_all_usd": round(total_pnl_all / 100.0, 2),
        "trades_today": total_trades_today,
        "trades_30d": total_trades_30d,
        "trades_all": total_trades_all,
        "win_rate_today": win_rate_today,
        "win_rate_30d": win_rate_30d,
        "win_rate_all": win_rate_all,
    }

    result = {
        "timestamp": int(now),
        "portfolio": portfolio,
        "bots": bots_metrics
    }

    _metrics_cache["timestamp"] = now
    _metrics_cache["data"] = result
    return result

PORTAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Profity AI — Trading Systems Command Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #070a12;
            --card-bg: rgba(18, 24, 38, 0.75);
            --card-border: rgba(255, 255, 255, 0.07);
            --card-hover-border: rgba(56, 189, 248, 0.35);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #10b981;
            --accent-red: #f43f5e;
            --accent-purple: #a855f7;
            --accent-gold: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(at 0% 0%, rgba(56, 189, 248, 0.12) 0px, transparent 45%),
                radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.1) 0px, transparent 45%),
                radial-gradient(at 50% 100%, rgba(16, 185, 129, 0.06) 0px, transparent 50%);
            color: var(--text-main);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            padding: 2rem 1.25rem;
        }

        .container {
            max-width: 1200px;
            width: 100%;
        }

        /* ── Header ── */
        header {
            text-align: center;
            margin-bottom: 2.25rem;
            position: relative;
        }

        .top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            margin-bottom: 1.25rem;
        }

        .badge-live {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: var(--accent-green);
            padding: 0.35rem 0.85rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }

        .dot-pulse {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            box-shadow: 0 0 10px var(--accent-green);
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.4); opacity: 0.6; }
        }

        .controls-top {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .unit-toggle {
            display: inline-flex;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 2px;
        }

        .unit-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 0.3rem 0.7rem;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .unit-btn.active {
            background: rgba(56, 189, 248, 0.2);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
        }

        .btn-refresh {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--card-border);
            color: var(--text-muted);
            padding: 0.35rem 0.75rem;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-refresh:hover {
            color: #fff;
            border-color: rgba(255, 255, 255, 0.2);
        }

        .spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }

        h1 {
            font-size: 2.5rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 50%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }

        .subtitle {
            color: var(--text-muted);
            font-size: 1.05rem;
            max-width: 680px;
            margin: 0 auto;
            line-height: 1.6;
        }

        /* ── Portfolio Overview Banner ── */
        .portfolio-overview {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .kpi-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 1.25rem 1.4rem;
            backdrop-filter: blur(12px);
            position: relative;
            overflow: hidden;
            transition: all 0.25s;
        }

        .kpi-card:hover {
            border-color: var(--card-hover-border);
            transform: translateY(-2px);
        }

        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
            background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), transparent);
        }

        .kpi-title {
            font-size: 0.78rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-muted);
            margin-bottom: 0.4rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .kpi-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.7rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 0.25rem;
        }

        .kpi-sub {
            font-size: 0.8rem;
            color: #64748b;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .val-positive { color: var(--accent-green) !important; }
        .val-negative { color: var(--accent-red) !important; }
        .val-neutral { color: var(--accent-blue) !important; }

        /* ── Comparison Section ── */
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            margin-bottom: 1rem;
        }

        .section-title {
            font-size: 1.25rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }

        .period-tabs {
            display: inline-flex;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--card-border);
            border-radius: 9px;
            padding: 3px;
            gap: 2px;
        }

        .period-tab {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 0.4rem 0.85rem;
            border-radius: 7px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .period-tab.active {
            background: rgba(56, 189, 248, 0.2);
            color: #fff;
            border: 1px solid rgba(56, 189, 248, 0.4);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        }

        /* ── Comparison Matrix Table Card ── */
        .table-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            backdrop-filter: blur(14px);
            overflow: hidden;
            margin-bottom: 2rem;
            box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
        }

        .table-responsive {
            width: 100%;
            overflow-x: auto;
        }

        table.comparison-table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.88rem;
        }

        table.comparison-table th {
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-muted);
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--card-border);
            white-space: nowrap;
        }

        table.comparison-table td {
            padding: 1.1rem 1.25rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            vertical-align: middle;
            white-space: nowrap;
        }

        table.comparison-table tr:last-child td {
            border-bottom: none;
        }

        table.comparison-table tr:hover td {
            background: rgba(255, 255, 255, 0.02);
        }

        .bot-cell {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .bot-avatar {
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.3rem;
            flex-shrink: 0;
        }

        .bot-info-title {
            font-weight: 700;
            color: #fff;
            font-size: 0.95rem;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .bot-info-sub {
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .badge-strategy {
            display: inline-block;
            font-size: 0.68rem;
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-weight: 700;
            letter-spacing: 0.04em;
        }

        .mono {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }

        .pnl-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.75rem;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.95rem;
            font-weight: 700;
        }

        .pnl-badge.pos {
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .pnl-badge.neg {
            background: rgba(244, 63, 94, 0.15);
            color: #f43f5e;
            border: 1px solid rgba(244, 63, 94, 0.3);
        }

        .pnl-badge.zero {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-muted);
            border: 1px solid var(--card-border);
        }

        .win-bar-wrap {
            width: 110px;
        }

        .win-bar-bg {
            height: 6px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 999px;
            overflow: hidden;
            margin-top: 4px;
        }

        .win-bar-fill {
            height: 100%;
            border-radius: 999px;
            transition: width 0.4s ease;
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.25rem 0.55rem;
            border-radius: 9999px;
            font-size: 0.72rem;
            font-weight: 600;
            background: rgba(16, 185, 129, 0.12);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.25);
        }

        .btn-desk-action {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.45rem 0.85rem;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s;
            cursor: pointer;
        }

        .btn-desk-action:hover {
            transform: translateY(-1px);
            filter: brightness(1.15);
        }

        /* ── Visual Comparison Contribution Bar ── */
        .comparison-bars-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.5rem;
            backdrop-filter: blur(12px);
            margin-bottom: 2.25rem;
        }

        .bar-container {
            margin-top: 1rem;
            display: flex;
            height: 24px;
            border-radius: 8px;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--card-border);
        }

        .bar-slice {
            height: 100%;
            transition: width 0.5s ease;
            position: relative;
        }

        .bar-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            margin-top: 1rem;
            font-size: 0.82rem;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--text-muted);
        }

        .legend-color {
            width: 10px;
            height: 10px;
            border-radius: 3px;
        }

        /* ── Grid Cards for Direct Launch ── */
        .grid-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2.5rem;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 1.75rem;
            backdrop-filter: blur(12px);
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        .card:hover {
            transform: translateY(-4px);
            border-color: var(--card-hover-border);
            box-shadow: 0 12px 30px -10px rgba(0, 0, 0, 0.5);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1.25rem;
        }

        .card-icon {
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
        }

        .icon-bot1 { background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.25); }
        .icon-bot2 { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.25); }
        .icon-bot3 { background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.25); }
        .icon-bot4 { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.25); }

        .port-tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.05);
            padding: 0.3rem 0.6rem;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .card-title {
            font-size: 1.35rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .card-desc {
            color: var(--text-muted);
            font-size: 0.92rem;
            line-height: 1.55;
            margin-bottom: 1.25rem;
        }

        .card-stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.75rem;
            background: rgba(0, 0, 0, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 10px;
            padding: 0.9rem;
            margin-bottom: 1.25rem;
        }

        .card-stat-label {
            font-size: 0.72rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 2px;
        }

        .card-stat-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.05rem;
            font-weight: 700;
        }

        .btn-launch {
            display: block;
            text-align: center;
            text-decoration: none;
            padding: 0.85rem 1.25rem;
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.95rem;
            transition: all 0.2s ease;
            cursor: pointer;
        }

        .btn-blue { background: #0284c7; color: #ffffff; }
        .btn-blue:hover { background: #0369a1; }
        .btn-gold { background: #d97706; color: #ffffff; }
        .btn-gold:hover { background: #b45309; }
        .btn-purple { background: #9333ea; color: #ffffff; }
        .btn-purple:hover { background: #7e22ce; }
        .btn-emerald { background: #059669; color: #ffffff; }
        .btn-emerald:hover { background: #047857; }

        .notice-box {
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 12px;
            padding: 1.25rem 1.5rem;
            font-size: 0.88rem;
            color: var(--text-muted);
            line-height: 1.6;
            margin-bottom: 2rem;
        }

        .notice-box strong { color: var(--text-main); }
        .notice-box code {
            font-family: 'JetBrains Mono', monospace;
            background: rgba(0, 0, 0, 0.3);
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            color: var(--accent-blue);
        }

        footer {
            text-align: center;
            color: #475569;
            font-size: 0.85rem;
        }

        @media (max-width: 768px) {
            h1 { font-size: 2rem; }
            .portfolio-overview { grid-template-columns: 1fr 1fr; }
            .grid-cards { grid-template-columns: 1fr; }
        }
        @media (max-width: 480px) {
            .portfolio-overview { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Top Navigation Bar -->
        <div class="top-bar">
            <div class="badge-live">
                <span class="dot-pulse"></span>
                Institutional VPS Core Active • 3 Bots Linked
            </div>
            <div class="controls-top">
                <div class="unit-toggle">
                    <button class="unit-btn active" id="btn-unit-usc" onclick="setUnit('USC')">USC (Cents)</button>
                    <button class="unit-btn" id="btn-unit-usd" onclick="setUnit('USD')">USD ($)</button>
                </div>
                <button class="btn-refresh" id="btn-manual-refresh" onclick="refreshData(true)">
                    <span id="refresh-icon">🔄</span> <span id="refresh-text">Refresh</span>
                </button>
            </div>
        </div>

        <!-- Header -->
        <header>
            <h1>Profity AI Command Center</h1>
            <p class="subtitle">Unified real-time multi-bot performance monitor, profit comparison matrix, and high-speed execution desk.</p>
        </header>

        <!-- Portfolio Overview Banner (4 KPIs) -->
        <div class="portfolio-overview">
            <div class="kpi-card">
                <div class="kpi-title">
                    <span>Combined Equity</span>
                    <span style="color: var(--accent-blue);">💎</span>
                </div>
                <div class="kpi-value" id="kpi-equity">--</div>
                <div class="kpi-sub">
                    <span>Balance: <span id="kpi-balance" class="mono">--</span></span>
                </div>
            </div>

            <div class="kpi-card">
                <div class="kpi-title">
                    <span>Floating Unrealized P&L</span>
                    <span style="color: var(--accent-green);">⚡</span>
                </div>
                <div class="kpi-value" id="kpi-floating">--</div>
                <div class="kpi-sub">
                    <span>Active Positions: <strong id="kpi-open-trades" style="color:#fff;">0</strong></span>
                </div>
            </div>

            <div class="kpi-card">
                <div class="kpi-title">
                    <span id="kpi-pnl-label">Realized Profit (30D)</span>
                    <span style="color: var(--accent-gold);">📊</span>
                </div>
                <div class="kpi-value" id="kpi-pnl">--</div>
                <div class="kpi-sub">
                    <span id="kpi-pnl-sub">All-Time: --</span>
                </div>
            </div>

            <div class="kpi-card">
                <div class="kpi-title">
                    <span>Portfolio Win Rate</span>
                    <span style="color: var(--accent-purple);">🎯</span>
                </div>
                <div class="kpi-value val-neutral" id="kpi-winrate">--</div>
                <div class="kpi-sub">
                    <span>Executed: <strong id="kpi-trades-count" style="color:#fff;">--</strong> trades</span>
                </div>
            </div>
        </div>

        <!-- Multi-Bot Profit Comparison Section -->
        <div class="section-header">
            <div class="section-title">
                <span>🏆</span> Multi-Bot Profit Comparison Matrix
            </div>
            <div class="period-tabs">
                <button class="period-tab" onclick="setPeriod('today')" id="tab-today">Today</button>
                <button class="period-tab" onclick="setPeriod('7d')" id="tab-7d">7 Days</button>
                <button class="period-tab active" onclick="setPeriod('30d')" id="tab-30d">30 Days</button>
                <button class="period-tab" onclick="setPeriod('all')" id="tab-all">All Time</button>
            </div>
        </div>

        <!-- Comparison Matrix Table -->
        <div class="table-card">
            <div class="table-responsive">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>Trading Engine / Strategy</th>
                            <th>Account / Server</th>
                            <th>Balance & Equity</th>
                            <th>Floating P&L</th>
                            <th id="th-period-pnl">Realized Profit (30D)</th>
                            <th>Win Rate & Trades</th>
                            <th>Profit Factor</th>
                            <th>Status</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="comparison-tbody">
                        <tr>
                            <td colspan="9" style="text-align: center; padding: 2.5rem; color: var(--text-muted);">
                                Loading live MT5 bridge statistics...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Visual Contribution & Distribution Bar -->
        <div class="comparison-bars-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #fff;">
                    📊 Relative Trade Volume & Equity Distribution
                </div>
                <div style="font-size: 0.8rem; color: var(--text-muted);" id="dist-period-label">
                    30-Day Contribution
                </div>
            </div>
            <div class="bar-container" id="distribution-bar">
                <div class="bar-slice" style="width: 25%; background: #38bdf8;"></div>
                <div class="bar-slice" style="width: 25%; background: #f59e0b;"></div>
                <div class="bar-slice" style="width: 25%; background: #a855f7;"></div>
                <div class="bar-slice" style="width: 25%; background: #10b981;"></div>
            </div>
            <div class="bar-legend" id="distribution-legend">
                <div class="legend-item"><div class="legend-color" style="background: #38bdf8;"></div> Bot #1 Auto Grid: --</div>
                <div class="legend-item"><div class="legend-color" style="background: #f59e0b;"></div> Bot #2 Manual Desk: --</div>
                <div class="legend-item"><div class="legend-color" style="background: #a855f7;"></div> Bot #3 Trend Runner: --</div>
                <div class="legend-item"><div class="legend-color" style="background: #10b981;"></div> Bot #4 SMC Hunter: --</div>
            </div>
        </div>

        <!-- Bot Launch Cards with Embedded Live Stats -->
        <div class="section-header">
            <div class="section-title">
                <span>🚀</span> Live Supervision Desks
            </div>
        </div>

        <div class="grid-cards">
            <!-- Bot 1: Auto Grid -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot1">⚡</div>
                        <div class="port-tag">PORT 8501</div>
                    </div>
                    <div class="card-title">Bot #1 — Auto Grid</div>
                    <div class="card-desc">Breakout Grid Engine with Smart Runner Mode, Auto-Regime Reading, and Hardened Risk Ceilings.</div>
                    
                    <div class="card-stats-grid">
                        <div>
                            <div class="card-stat-label">Live Equity</div>
                            <div class="card-stat-value" id="b1-equity">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Floating P&L</div>
                            <div class="card-stat-value" id="b1-floating">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label" id="b1-pnl-label">30D Realized</div>
                            <div class="card-stat-value" id="b1-pnl">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Win Rate</div>
                            <div class="card-stat-value val-neutral" id="b1-winrate">--</div>
                        </div>
                    </div>
                </div>
                <a id="link-bot1" href="http://" class="btn-launch btn-blue">Open Auto Grid Desk &rarr;</a>
            </div>

            <!-- Bot 2: Manual Grid Desk -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot2">🕹️</div>
                        <div class="port-tag">PORT 8502</div>
                    </div>
                    <div class="card-title">Bot #2 — Manual Grid Desk</div>
                    <div class="card-desc">Interactive manual control panel for precision trap deployment, live monitoring, and manual cycle executions.</div>
                    
                    <div class="card-stats-grid">
                        <div>
                            <div class="card-stat-label">Live Equity</div>
                            <div class="card-stat-value" id="b2-equity">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Floating P&L</div>
                            <div class="card-stat-value" id="b2-floating">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label" id="b2-pnl-label">30D Realized</div>
                            <div class="card-stat-value" id="b2-pnl">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Win Rate</div>
                            <div class="card-stat-value val-neutral" id="b2-winrate">--</div>
                        </div>
                    </div>
                </div>
                <a id="link-bot2" href="http://" class="btn-launch btn-gold">Open Manual Desk &rarr;</a>
            </div>

            <!-- Bot 3: Trend System -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot3">📈</div>
                        <div class="port-tag">PORT 8503</div>
                    </div>
                    <div class="card-title">Bot #3 — London Asian Trend</div>
                    <div class="card-desc">24/7 autonomous Asian session box breakout & London trend confirmation trading system.</div>
                    
                    <div class="card-stats-grid">
                        <div>
                            <div class="card-stat-label">Live Equity</div>
                            <div class="card-stat-value" id="b3-equity">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Floating P&L</div>
                            <div class="card-stat-value" id="b3-floating">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label" id="b3-pnl-label">30D Realized</div>
                            <div class="card-stat-value" id="b3-pnl">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Win Rate</div>
                            <div class="card-stat-value val-neutral" id="b3-winrate">--</div>
                        </div>
                    </div>
                </div>
                <a id="link-bot3" href="http://" class="btn-launch btn-purple">Open Trend Panel &rarr;</a>
            </div>

            <!-- Bot 4: SMC Liquidity Hunter -->
            <div class="card">
                <div>
                    <div class="card-header">
                        <div class="card-icon icon-bot4">🎯</div>
                        <div class="port-tag">PORT 8504</div>
                    </div>
                    <div class="card-title">Bot #4 — SMC Liquidity Hunter</div>
                    <div class="card-desc">Institutional liquidity sweep & FVG reversal engine fading fakeouts at session highs/lows.</div>
                    
                    <div class="card-stats-grid">
                        <div>
                            <div class="card-stat-label">Live Equity</div>
                            <div class="card-stat-value" id="b4-equity">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Floating P&L</div>
                            <div class="card-stat-value" id="b4-floating">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label" id="b4-pnl-label">30D Realized</div>
                            <div class="card-stat-value" id="b4-pnl">--</div>
                        </div>
                        <div>
                            <div class="card-stat-label">Win Rate</div>
                            <div class="card-stat-value val-neutral" id="b4-winrate">--</div>
                        </div>
                    </div>
                </div>
                <a id="link-bot4" href="http://" class="btn-launch btn-emerald">Open SMC Panel &rarr;</a>
            </div>
        </div>

        <div class="notice-box">
            💡 <strong>Connection & Profit Tracking:</strong> All metrics are fetched live from MetaTrader 5 terminal bridges under Wine prefixes (<code>8001</code>, <code>8002</code>, <code>8003</code>, <code>8004</code>). To access individual bot dashboards, connect via <code>http://</code> (not <code>https://</code>). Auto-refresh is synchronized every 5 seconds.
        </div>
    </div>

    <footer>
        Profity AI Systems &bull; High Frequency / Low Latency Deployment &bull; 169.58.190.245
    </footer>

    <script>
        // State
        let currentUnit = 'USC'; // 'USC' or 'USD'
        let currentPeriod = '30d'; // 'today', '7d', '30d', 'all'
        let liveData = null;

        // Dynamic target links
        const host = window.location.hostname || "169.58.190.245";
        document.getElementById("link-bot1").href = "http://" + host + ":8501";
        document.getElementById("link-bot2").href = "http://" + host + ":8502";
        document.getElementById("link-bot3").href = "http://" + host + ":8503";
        document.getElementById("link-bot4").href = "http://" + host + ":8504";

        function setUnit(unit) {
            currentUnit = unit;
            document.getElementById("btn-unit-usc").classList.toggle("active", unit === 'USC');
            document.getElementById("btn-unit-usd").classList.toggle("active", unit === 'USD');
            renderUI();
        }

        function setPeriod(period) {
            currentPeriod = period;
            document.getElementById("tab-today").classList.toggle("active", period === 'today');
            document.getElementById("tab-7d").classList.toggle("active", period === '7d');
            document.getElementById("tab-30d").classList.toggle("active", period === '30d');
            document.getElementById("tab-all").classList.toggle("active", period === 'all');
            
            const labels = {
                'today': "Realized Profit (Today)",
                '7d': "Realized Profit (7 Days)",
                '30d': "Realized Profit (30 Days)",
                'all': "Realized Profit (All Time)"
            };
            document.getElementById("kpi-pnl-label").innerText = labels[period];
            document.getElementById("th-period-pnl").innerText = labels[period];
            
            ['b1', 'b2', 'b3', 'b4'].forEach(id => {
                const el = document.getElementById(id + "-pnl-label");
                if (el) el.innerText = period.toUpperCase() + " Realized";
            });

            renderUI();
        }

        function formatMoney(amountUsc, showSign = false) {
            const val = currentUnit === 'USD' ? (amountUsc / 100.0) : amountUsc;
            const sign = (showSign && val > 0) ? "+" : "";
            const unitSuffix = currentUnit === 'USD' ? "" : " USC";
            const prefix = currentUnit === 'USD' ? "$" : "";
            return sign + prefix + val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + unitSuffix;
        }

        function getPnlColorClass(val) {
            if (val > 0.001) return "val-positive";
            if (val < -0.001) return "val-negative";
            return "";
        }

        function getPnlBadgeClass(val) {
            if (val > 0.001) return "pnl-badge pos";
            if (val < -0.001) return "pnl-badge neg";
            return "pnl-badge zero";
        }

        async function refreshData(manual = false) {
            const icon = document.getElementById("refresh-icon");
            if (icon) icon.classList.add("spin");

            try {
                const res = await fetch("/api/bot_profits");
                if (res.ok) {
                    liveData = await res.json();
                    renderUI();
                }
            } catch (err) {
                console.error("Failed to fetch profit data:", err);
            } finally {
                if (icon) icon.classList.remove("spin");
            }
        }

        function renderUI() {
            if (!liveData || !liveData.portfolio) return;
            const p = liveData.portfolio;
            const bots = liveData.bots || [];

            // 1. KPI Banner
            document.getElementById("kpi-equity").innerText = formatMoney(p.total_equity_usc);
            document.getElementById("kpi-equity").className = "kpi-value " + getPnlColorClass(p.total_equity_usc - p.total_balance_usc);
            document.getElementById("kpi-balance").innerText = formatMoney(p.total_balance_usc);

            const floatingEl = document.getElementById("kpi-floating");
            floatingEl.innerText = formatMoney(p.total_floating_usc, true);
            floatingEl.className = "kpi-value " + getPnlColorClass(p.total_floating_usc);
            document.getElementById("kpi-open-trades").innerText = p.active_positions;

            let periodPnl = p.pnl_30d_usc;
            let periodTrades = p.trades_30d;
            let periodWinRate = p.win_rate_30d;

            if (currentPeriod === 'today') {
                periodPnl = p.pnl_today_usc;
                periodTrades = p.trades_today;
                periodWinRate = p.win_rate_today;
            } else if (currentPeriod === '7d') {
                periodPnl = p.pnl_7d_usc;
            } else if (currentPeriod === 'all') {
                periodPnl = p.pnl_all_usc;
                periodTrades = p.trades_all;
                periodWinRate = p.win_rate_all;
            }

            const pnlEl = document.getElementById("kpi-pnl");
            pnlEl.innerText = formatMoney(periodPnl, true);
            pnlEl.className = "kpi-value " + getPnlColorClass(periodPnl);
            document.getElementById("kpi-pnl-sub").innerText = "All-Time: " + formatMoney(p.pnl_all_usc, true);

            document.getElementById("kpi-winrate").innerText = periodWinRate.toFixed(1) + "%";
            document.getElementById("kpi-trades-count").innerText = periodTrades.toLocaleString();

            // 2. Comparison Table
            const tbody = document.getElementById("comparison-tbody");
            tbody.innerHTML = "";

            bots.forEach(b => {
                let botPeriodPnl = b.pnl_30d;
                let botPeriodTrades = b.trades_30d;
                let botPeriodWins = b.wins_30d;
                let botPeriodWinRate = b.win_rate_30d;

                if (currentPeriod === 'today') {
                    botPeriodPnl = b.pnl_today;
                    botPeriodTrades = b.trades_today;
                    botPeriodWins = b.wins_today;
                    botPeriodWinRate = b.win_rate_today;
                } else if (currentPeriod === '7d') {
                    botPeriodPnl = b.pnl_7d;
                    botPeriodTrades = b.trades_7d;
                    botPeriodWins = b.wins_7d;
                    botPeriodWinRate = b.win_rate_7d;
                } else if (currentPeriod === 'all') {
                    botPeriodPnl = b.pnl_all;
                    botPeriodTrades = b.trades_all;
                    botPeriodWins = b.wins_all;
                    botPeriodWinRate = b.win_rate_all;
                }

                const tr = document.createElement("tr");

                const btnColors = {
                    1: "btn-blue",
                    2: "btn-gold",
                    3: "btn-purple",
                    4: "btn-emerald"
                };

                tr.innerHTML = `
                    <td>
                        <div class="bot-cell">
                            <div class="bot-avatar icon-bot${b.id}">${b.icon}</div>
                            <div>
                                <div class="bot-info-title">
                                    ${b.name}
                                    <span class="badge-strategy" style="background: ${b.color}22; color: ${b.color}; border: 1px solid ${b.color}44;">${b.tag}</span>
                                </div>
                                <div class="bot-info-sub">${b.strategy}</div>
                            </div>
                        </div>
                    </td>
                    <td>
                        <div class="mono" style="color: #fff; font-size: 0.9rem;">#${b.account}</div>
                        <div style="font-size: 0.75rem; color: var(--text-muted);">${b.server}</div>
                    </td>
                    <td>
                        <div class="mono" style="color: #fff; font-size: 0.95rem;">${formatMoney(b.equity)}</div>
                        <div style="font-size: 0.75rem; color: var(--text-muted);">Bal: ${formatMoney(b.balance)}</div>
                    </td>
                    <td>
                        <span class="mono ${getPnlColorClass(b.floating_pnl)}" style="font-size: 0.95rem;">
                            ${formatMoney(b.floating_pnl, true)}
                        </span>
                        <div style="font-size: 0.75rem; color: var(--text-muted);">${b.active_positions} Open</div>
                    </td>
                    <td>
                        <div class="${getPnlBadgeClass(botPeriodPnl)}">
                            ${formatMoney(botPeriodPnl, true)}
                        </div>
                    </td>
                    <td>
                        <div class="win-bar-wrap">
                            <div style="display: flex; justify-content: space-between; font-size: 0.8rem;">
                                <span class="mono" style="color: #fff; font-weight: 700;">${botPeriodWinRate.toFixed(1)}%</span>
                                <span style="color: var(--text-muted); font-size: 0.75rem;">${botPeriodWins}/${botPeriodTrades}</span>
                            </div>
                            <div class="win-bar-bg">
                                <div class="win-bar-fill" style="width: ${Math.min(100, Math.max(0, botPeriodWinRate))}%; background: ${b.color};"></div>
                            </div>
                        </div>
                    </td>
                    <td>
                        <span class="mono" style="color: #cbd5e1;">${b.profit_factor_30d || '1.0'}</span>
                    </td>
                    <td>
                        <span class="status-pill">
                            <span class="dot-pulse" style="width: 6px; height: 6px;"></span>
                            Online
                        </span>
                    </td>
                    <td>
                        <a href="http://${host}:${b.panel_port}" class="btn-desk-action ${btnColors[b.id] || 'btn-blue'}">
                            Open &rarr;
                        </a>
                    </td>
                `;
                tbody.appendChild(tr);

                // 3. Update Individual Bot Cards
                const bId = "b" + b.id;
                const eqEl = document.getElementById(bId + "-equity");
                if (eqEl) eqEl.innerText = formatMoney(b.equity);

                const flEl = document.getElementById(bId + "-floating");
                if (flEl) {
                    flEl.innerText = formatMoney(b.floating_pnl, true);
                    flEl.className = "card-stat-value " + getPnlColorClass(b.floating_pnl);
                }

                const pnlCardEl = document.getElementById(bId + "-pnl");
                if (pnlCardEl) {
                    pnlCardEl.innerText = formatMoney(botPeriodPnl, true);
                    pnlCardEl.className = "card-stat-value " + getPnlColorClass(botPeriodPnl);
                }

                const wrCardEl = document.getElementById(bId + "-winrate");
                if (wrCardEl) wrCardEl.innerText = botPeriodWinRate.toFixed(1) + "%";
            });

            // 4. Update Distribution Bar
            const distContainer = document.getElementById("distribution-bar");
            const legendContainer = document.getElementById("distribution-legend");
            
            const totalTradesCount = bots.reduce((sum, b) => {
                if (currentPeriod === 'today') return sum + b.trades_today;
                if (currentPeriod === '7d') return sum + b.trades_7d;
                if (currentPeriod === 'all') return sum + b.trades_all;
                return sum + b.trades_30d;
            }, 0);

            if (totalTradesCount > 0) {
                distContainer.innerHTML = "";
                legendContainer.innerHTML = "";

                bots.forEach(b => {
                    let bTrades = (currentPeriod === 'today') ? b.trades_today :
                                  (currentPeriod === '7d') ? b.trades_7d :
                                  (currentPeriod === 'all') ? b.trades_all : b.trades_30d;
                    let pct = ((bTrades / totalTradesCount) * 100).toFixed(1);

                    const slice = document.createElement("div");
                    slice.className = "bar-slice";
                    slice.style.width = pct + "%";
                    slice.style.background = b.color;
                    slice.title = `${b.name}: ${pct}% (${bTrades} trades)`;
                    distContainer.appendChild(slice);

                    const leg = document.createElement("div");
                    leg.className = "legend-item";
                    leg.innerHTML = `<div class="legend-color" style="background: ${b.color};"></div> ${b.name}: <strong>${pct}%</strong> (${bTrades} trades)`;
                    legendContainer.appendChild(leg);
                });
            }
        }

        // Initial fetch & set 5-second polling
        refreshData();
        setInterval(refreshData, 5000);
    </script>
</body>
</html>
"""

class PortalHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/bot_profits":
            data = get_all_bot_metrics()
            body = json.dumps(data).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/status":
            status = {
                "bot1": is_port_listening(8501),
                "bot2": is_port_listening(8502),
                "bot3": is_port_listening(8503),
            }
            body = json.dumps(status).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = PORTAL_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress verbose terminal access logs
        pass

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), PortalHandler) as httpd:
        print(f"Profity AI Portal & Command Center running on http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run()
