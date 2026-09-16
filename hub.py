#!/usr/bin/env python3
"""
Profity AI - Unified VPS Web Portal & Multi-Bot Command Center (Port 80)
Features:
- Fullscreen Institutional High-Frequency Trading Desk Layout (No Boxed Constraints)
- Real-Time Global Market Session Ticker (London, NY, Tokyo, Sydney) & Live UTC Clock
- Live Portfolio Aggregate Metrics (Equity, Balance, Free Margin, Margin Level %, Floating PnL)
- Multi-Bot Real-Time Profit Comparison Matrix (Today / 7D / 30D / All-Time) across all 5 bots
- Deep Financial & Risk Metrics (Win/Loss counts, Profit Factor, Payoff Ratio, Avg Win/Loss, ROI %)
- Net Open Lot Exposure (Long Lots vs Short Lots) per bot and portfolio-wide
- Live Active Positions & Ticket Inspector with real-time Floating P&L
- One-Click HTML5 Fullscreen Mode for Wall Displays & Kiosks
- Direct Launch to all 5 Trading Desks (:8501-:8505) and Wine MT5 Screen (:8006)
"""

import http.server
import threading
import time
import json
import logging
import uuid
import sys
import sys

# --- FIX WINDOWS EMOJI PRINT CRASHES ---
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
# ---------------------------------------
import socket
import socketserver
import urllib.parse
import urllib.request
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
    },
    {
        "id": 5,
        "name": "Bot #5 — AI/ML Neural Trader",
        "tag": "AI ENSEMBLE",
        "strategy": "Deep RL (PPO/Dreamer) + Regime Detection & DSS Risk Guard",
        "bridge_port": 8005,
        "panel_port": 8505,
        "default_acc": 257515249,
        "server": "Exness-MT5Real36",
        "color": "#ec4899",
        "icon": "🤖"
    }
]

# In-memory cache for live metrics to protect MT5 bridges
_metrics_cache = {"timestamp": 0.0, "data": None}
CACHE_TTL = 2.0  # seconds

def is_port_listening(port, host="127.0.0.1", timeout=0.3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

def fetch_single_bot_metrics(cfg):
    bport = cfg["bridge_port"]
    start_t = time.time()
    now = start_t
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
        "leverage": 2000,
        "balance": 0.0,
        "equity": 0.0,
        "margin": 0.0,
        "margin_free": 0.0,
        "margin_level": 0.0,
        "floating_pnl": 0.0,
        "active_positions": 0,
        "open_lots": 0.0,
        "buy_positions": 0,
        "sell_positions": 0,
        "buy_lots": 0.0,
        "sell_lots": 0.0,
        "positions_list": [],
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
        "losses_today": 0,
        "losses_7d": 0,
        "losses_30d": 0,
        "losses_all": 0,
        "win_rate_today": 0.0,
        "win_rate_7d": 0.0,
        "win_rate_30d": 0.0,
        "win_rate_all": 0.0,
        "gross_profit_30d": 0.0,
        "gross_loss_30d": 0.0,
        "profit_factor_30d": 1.0,
        "avg_win_30d": 0.0,
        "avg_loss_30d": 0.0,
        "payoff_ratio_30d": 1.0,
        "best_trade_30d": 0.0,
        "worst_trade_30d": 0.0,
        "roi_30d_pct": 0.0,
        "latency_ms": 0.0,
        "last_trade_time": 0
    }

    try:
        # 1. Fetch Account Info
        req_acc = urllib.request.Request(f"http://127.0.0.1:{bport}/account", headers={"User-Agent": "HubCollector"})
        with urllib.request.urlopen(req_acc, timeout=4.5) as resp:
            acc_data = json.loads(resp.read().decode("utf-8"))
            res["connected"] = acc_data.get("connected", False)
            res["account"] = acc_data.get("login", cfg["default_acc"])
            res["server"] = acc_data.get("server", cfg["server"])
            res["currency"] = acc_data.get("currency", "USC")
            res["leverage"] = acc_data.get("leverage", 2000)
            res["balance"] = round(float(acc_data.get("balance", 0.0)), 2)
            res["equity"] = round(float(acc_data.get("equity", 0.0)), 2)
            res["margin"] = round(float(acc_data.get("margin", 0.0)), 2)
            res["margin_free"] = round(float(acc_data.get("margin_free", res["balance"])), 2)
            res["margin_level"] = round(float(acc_data.get("margin_level", 0.0)), 1)
    except Exception:
        pass

    try:
        # 2. Fetch Open Positions
        req_pos = urllib.request.Request(f"http://127.0.0.1:{bport}/positions", headers={"User-Agent": "HubCollector"})
        with urllib.request.urlopen(req_pos, timeout=4.5) as resp:
            pos_data = json.loads(resp.read().decode("utf-8")).get("positions", [])
            res["active_positions"] = len(pos_data)
            res["floating_pnl"] = round(sum(float(p.get("profit", 0.0)) for p in pos_data), 2)

            for p in pos_data:
                vol = round(float(p.get("volume", 0.0)), 2)
                res["open_lots"] += vol
                is_buy = p.get("type") in (0, "BUY", "buy")
                if is_buy:
                    res["buy_positions"] += 1
                    res["buy_lots"] += vol
                else:
                    res["sell_positions"] += 1
                    res["sell_lots"] += vol

                res["positions_list"].append({
                    "ticket": p.get("ticket"),
                    "bot_id": cfg["id"],
                    "bot_name": cfg["name"],
                    "bot_tag": cfg["tag"],
                    "bot_color": cfg["color"],
                    "symbol": p.get("symbol", "XAUUSDm"),
                    "type": "BUY" if is_buy else "SELL",
                    "volume": vol,
                    "price_open": round(float(p.get("price_open", 0.0)), 3),
                    "price_current": round(float(p.get("price_current", 0.0)), 3),
                    "sl": round(float(p.get("sl", 0.0)), 3),
                    "tp": round(float(p.get("tp", 0.0)), 3),
                    "profit": round(float(p.get("profit", 0.0)), 2),
                    "time": p.get("time", 0)
                })

            res["open_lots"] = round(res["open_lots"], 2)
            res["buy_lots"] = round(res["buy_lots"], 2)
            res["sell_lots"] = round(res["sell_lots"], 2)
    except Exception:
        pass

    try:
        # 3. Fetch Deal History (Last 60 Days)
        req_hist = urllib.request.Request(f"http://127.0.0.1:{bport}/history?days=60", headers={"User-Agent": "HubCollector"})
        with urllib.request.urlopen(req_hist, timeout=6.0) as resp:
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
                if t_time > res["last_trade_time"]:
                    res["last_trade_time"] = int(t_time)

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

            res["losses_today"] = res["trades_today"] - res["wins_today"]
            res["losses_7d"] = res["trades_7d"] - res["wins_7d"]
            res["losses_30d"] = res["trades_30d"] - res["wins_30d"]
            res["losses_all"] = res["trades_all"] - res["wins_all"]

            res["gross_profit_30d"] = round(gross_profit_30d, 2)
            res["gross_loss_30d"] = round(gross_loss_30d, 2)

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

            if res["wins_30d"] > 0:
                res["avg_win_30d"] = round(gross_profit_30d / res["wins_30d"], 2)
            if res["losses_30d"] > 0:
                res["avg_loss_30d"] = round(gross_loss_30d / res["losses_30d"], 2)

            if res["avg_loss_30d"] > 0:
                res["payoff_ratio_30d"] = round(res["avg_win_30d"] / res["avg_loss_30d"], 2)

            init_cap = max(100.0, res["balance"] - res["pnl_30d"])
            res["roi_30d_pct"] = round((res["pnl_30d"] / init_cap) * 100, 1)

    except Exception:
        pass

    res["latency_ms"] = round((time.time() - start_t) * 1000, 1)
    return res

def get_all_bot_metrics():
    global _metrics_cache
    now = time.time()
    if _metrics_cache["data"] is not None and (now - _metrics_cache["timestamp"] < CACHE_TTL):
        return _metrics_cache["data"]

    with ThreadPoolExecutor(max_workers=5) as executor:
        bots_metrics = list(executor.map(fetch_single_bot_metrics, BOT_CONFIGS))

    total_balance = sum(b["balance"] for b in bots_metrics)
    total_equity = sum(b["equity"] for b in bots_metrics)
    total_margin = sum(b["margin"] for b in bots_metrics)
    total_margin_free = sum(b["margin_free"] for b in bots_metrics)
    total_floating = sum(b["floating_pnl"] for b in bots_metrics)
    total_pnl_today = sum(b["pnl_today"] for b in bots_metrics)
    total_pnl_7d = sum(b["pnl_7d"] for b in bots_metrics)
    total_pnl_30d = sum(b["pnl_30d"] for b in bots_metrics)
    total_pnl_all = sum(b["pnl_all"] for b in bots_metrics)

    total_trades_today = sum(b["trades_today"] for b in bots_metrics)
    total_wins_today = sum(b["wins_today"] for b in bots_metrics)
    win_rate_today = round((total_wins_today / total_trades_today * 100), 1) if total_trades_today > 0 else 0.0

    total_trades_7d = sum(b["trades_7d"] for b in bots_metrics)
    total_wins_7d = sum(b["wins_7d"] for b in bots_metrics)
    win_rate_7d = round((total_wins_7d / total_trades_7d * 100), 1) if total_trades_7d > 0 else 0.0

    total_trades_30d = sum(b["trades_30d"] for b in bots_metrics)
    total_wins_30d = sum(b["wins_30d"] for b in bots_metrics)
    win_rate_30d = round((total_wins_30d / total_trades_30d * 100), 1) if total_trades_30d > 0 else 0.0

    total_trades_all = sum(b["trades_all"] for b in bots_metrics)
    total_wins_all = sum(b["wins_all"] for b in bots_metrics)
    win_rate_all = round((total_wins_all / total_trades_all * 100), 1) if total_trades_all > 0 else 0.0

    active_positions_count = sum(b["active_positions"] for b in bots_metrics)
    total_open_lots = round(sum(b["open_lots"] for b in bots_metrics), 2)
    total_buy_lots = round(sum(b["buy_lots"] for b in bots_metrics), 2)
    total_sell_lots = round(sum(b["sell_lots"] for b in bots_metrics), 2)

    total_margin_level = round((total_equity / total_margin * 100), 1) if total_margin > 0 else 0.0

    all_positions = []
    for b in bots_metrics:
        all_positions.extend(b.get("positions_list", []))
    all_positions.sort(key=lambda x: x["profit"])

    gross_profit_30d = sum(b.get("gross_profit_30d", 0.0) for b in bots_metrics)
    gross_loss_30d = sum(b.get("gross_loss_30d", 0.0) for b in bots_metrics)
    profit_factor_30d = round(gross_profit_30d / gross_loss_30d, 2) if gross_loss_30d > 0 else (9.99 if gross_profit_30d > 0 else 1.0)

    portfolio = {
        "total_balance_usc": round(total_balance, 2),
        "total_equity_usc": round(total_equity, 2),
        "total_balance_usd": round(total_balance / 100.0, 2),
        "total_equity_usd": round(total_equity / 100.0, 2),
        "total_margin_usc": round(total_margin, 2),
        "total_margin_usd": round(total_margin / 100.0, 2),
        "total_margin_free_usc": round(total_margin_free, 2),
        "total_margin_free_usd": round(total_margin_free / 100.0, 2),
        "total_margin_level": total_margin_level,
        "total_floating_usc": round(total_floating, 2),
        "total_floating_usd": round(total_floating / 100.0, 2),
        "active_positions": active_positions_count,
        "total_open_lots": total_open_lots,
        "total_buy_lots": total_buy_lots,
        "total_sell_lots": total_sell_lots,
        "pnl_today_usc": round(total_pnl_today, 2),
        "pnl_today_usd": round(total_pnl_today / 100.0, 2),
        "pnl_7d_usc": round(total_pnl_7d, 2),
        "pnl_7d_usd": round(total_pnl_7d / 100.0, 2),
        "pnl_30d_usc": round(total_pnl_30d, 2),
        "pnl_30d_usd": round(total_pnl_30d / 100.0, 2),
        "pnl_all_usc": round(total_pnl_all, 2),
        "pnl_all_usd": round(total_pnl_all / 100.0, 2),
        "trades_today": total_trades_today,
        "trades_7d": total_trades_7d,
        "trades_30d": total_trades_30d,
        "trades_all": total_trades_all,
        "wins_today": total_wins_today,
        "wins_7d": total_wins_7d,
        "wins_30d": total_wins_30d,
        "wins_all": total_wins_all,
        "losses_today": total_trades_today - total_wins_today,
        "losses_7d": total_trades_7d - total_wins_7d,
        "losses_30d": total_trades_30d - total_wins_30d,
        "losses_all": total_trades_all - total_wins_all,
        "win_rate_today": win_rate_today,
        "win_rate_7d": win_rate_7d,
        "win_rate_30d": win_rate_30d,
        "win_rate_all": win_rate_all,
        "profit_factor_30d": profit_factor_30d,
        "gross_profit_30d_usc": round(gross_profit_30d, 2),
        "gross_loss_30d_usc": round(gross_loss_30d, 2),
        "all_positions": all_positions
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
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #07090e;
            --bg-card: rgba(15, 21, 37, 0.72);
            --bg-card-hover: rgba(22, 31, 54, 0.85);
            --border-card: rgba(255, 255, 255, 0.07);
            --border-card-hover: rgba(56, 189, 248, 0.4);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-cyan: #38bdf8;
            --accent-green: #10b981;
            --accent-rose: #f43f5e;
            --accent-purple: #a855f7;
            --accent-amber: #f59e0b;
            --accent-pink: #ec4899;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-dark);
            background-image: 
                radial-gradient(at 0% 0%, rgba(56, 189, 248, 0.12) 0px, transparent 40%),
                radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.1) 0px, transparent 40%),
                radial-gradient(at 50% 100%, rgba(16, 185, 129, 0.07) 0px, transparent 50%),
                linear-gradient(rgba(255, 255, 255, 0.015) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255, 255, 255, 0.015) 1px, transparent 1px);
            background-size: 100% 100%, 100% 100%, 100% 100%, 32px 32px, 32px 32px;
            color: var(--text-primary);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            width: 100%;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
        }

        /* ── Fullscreen Main Shell ── */
        .fullscreen-shell {
            width: 100%;
            padding: 1rem 1.5rem;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }

        /* ── Header Navigation Ribbon ── */
        .nav-ribbon {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            background: rgba(13, 18, 30, 0.85);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 0.75rem 1.25rem;
            backdrop-filter: blur(16px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }

        .brand-group {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .brand-icon {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.25), rgba(168, 85, 247, 0.25));
            border: 1px solid rgba(56, 189, 248, 0.4);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            box-shadow: 0 0 16px rgba(56, 189, 248, 0.2);
        }

        .brand-title {
            font-size: 1.25rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 60%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .vps-status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            background: rgba(16, 185, 129, 0.12);
            color: var(--accent-green);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 999px;
            padding: 0.25rem 0.65rem;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.03em;
        }

        .dot-live {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--accent-green);
            box-shadow: 0 0 8px var(--accent-green);
            animation: pulse-live 1.8s infinite;
        }
        @keyframes pulse-live {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.35); opacity: 0.6; }
        }

        /* ── Market Session Clocks ── */
        .market-sessions {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }

        .session-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.25rem 0.55rem;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.07);
            font-size: 0.73rem;
            color: var(--text-secondary);
        }

        .session-open {
            background: rgba(16, 185, 129, 0.15);
            border-color: rgba(16, 185, 129, 0.35);
            color: #34d399;
            font-weight: 600;
        }

        .clock-utc {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--accent-cyan);
            background: rgba(56, 189, 248, 0.1);
            border: 1px solid rgba(56, 189, 248, 0.25);
            padding: 0.25rem 0.6rem;
            border-radius: 6px;
        }

        /* ── Action Controls (Unit, Period, Refresh, Fullscreen) ── */
        .controls-ribbon {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            flex-wrap: wrap;
        }

        .toggle-group {
            display: inline-flex;
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid var(--border-card);
            border-radius: 8px;
            padding: 2px;
            gap: 2px;
        }

        .toggle-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 0.35rem 0.75rem;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }

        .toggle-btn:hover {
            color: #fff;
        }

        .toggle-btn.active {
            background: rgba(56, 189, 248, 0.22);
            color: var(--accent-cyan);
            border: 1px solid rgba(56, 189, 248, 0.4);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);
        }

        .btn-action {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-card);
            color: var(--text-secondary);
            padding: 0.4rem 0.8rem;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-action:hover {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
            border-color: rgba(255, 255, 255, 0.2);
        }

        .btn-fullscreen {
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.2), rgba(168, 85, 247, 0.2));
            color: #fff;
            border: 1px solid rgba(56, 189, 248, 0.4);
        }

        .btn-fullscreen:hover {
            border-color: var(--accent-cyan);
            box-shadow: 0 0 14px rgba(56, 189, 248, 0.3);
        }

        .spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }

        /* ── Institutional KPI Strip (6 Cards) ── */
        .kpi-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.9rem;
        }

        .kpi-tile {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 1.1rem 1.25rem;
            backdrop-filter: blur(14px);
            position: relative;
            overflow: hidden;
            transition: all 0.25s;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }

        .kpi-tile:hover {
            border-color: var(--border-card-hover);
            transform: translateY(-2px);
            background: var(--bg-card-hover);
        }

        .kpi-tile::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 2.5px;
            background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.5), transparent);
        }

        .kpi-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.45rem;
        }

        .kpi-label {
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-secondary);
        }

        .kpi-icon {
            font-size: 1.1rem;
            opacity: 0.85;
        }

        .kpi-val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.65rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin-bottom: 0.35rem;
            color: #fff;
        }

        .kpi-footer {
            font-size: 0.78rem;
            color: var(--text-muted);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: 'Inter', sans-serif;
        }

        .mono {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }

        .val-positive { color: var(--accent-green) !important; }
        .val-negative { color: var(--accent-rose) !important; }
        .val-neutral { color: var(--accent-cyan) !important; }
        .val-warning { color: var(--accent-amber) !important; }

        /* ── Multi-Bot Comparison Section ── */
        .section-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin-top: 0.5rem;
        }

        .section-heading {
            font-size: 1.25rem;
            font-weight: 800;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            letter-spacing: -0.01em;
        }

        .table-card {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            backdrop-filter: blur(16px);
            overflow: hidden;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
        }

        .table-responsive {
            width: 100%;
            overflow-x: auto;
        }

        table.comparison-table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.86rem;
        }

        table.comparison-table th {
            background: rgba(255, 255, 255, 0.025);
            color: var(--text-secondary);
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            padding: 1rem 1.15rem;
            border-bottom: 1px solid var(--border-card);
            white-space: nowrap;
        }

        table.comparison-table td {
            padding: 1rem 1.15rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            vertical-align: middle;
            white-space: nowrap;
        }

        table.comparison-table tr:hover td {
            background: rgba(255, 255, 255, 0.02);
        }

        table.comparison-table tr:last-child td {
            border-bottom: none;
        }

        .bot-cell {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .bot-avatar {
            width: 42px;
            height: 42px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.35rem;
            flex-shrink: 0;
        }

        .icon-bot1 { background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.35); }
        .icon-bot2 { background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.35); }
        .icon-bot3 { background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.35); }
        .icon-bot4 { background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); }
        .icon-bot5 { background: rgba(236, 72, 153, 0.15); border: 1px solid rgba(236, 72, 153, 0.35); }

        .bot-name {
            font-weight: 700;
            color: #fff;
            font-size: 0.96rem;
            display: flex;
            align-items: center;
            gap: 0.45rem;
        }

        .badge-strategy {
            display: inline-block;
            font-size: 0.65rem;
            padding: 0.12rem 0.45rem;
            border-radius: 4px;
            font-weight: 700;
            letter-spacing: 0.04em;
        }

        .bot-strategy-desc {
            font-size: 0.77rem;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .pnl-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.35rem 0.75rem;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.92rem;
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
            border: 1px solid var(--border-card);
        }

        .win-bar-wrap {
            width: 120px;
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
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 600;
            background: rgba(16, 185, 129, 0.12);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.25);
        }

        .btn-desk {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.45rem 0.9rem;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 700;
            text-decoration: none;
            transition: all 0.2s;
            cursor: pointer;
        }

        .btn-blue { background: #0284c7; color: #fff; }
        .btn-blue:hover { background: #0369a1; box-shadow: 0 0 12px rgba(2, 132, 199, 0.4); }
        .btn-gold { background: #d97706; color: #fff; }
        .btn-gold:hover { background: #b45309; box-shadow: 0 0 12px rgba(217, 119, 6, 0.4); }
        .btn-purple { background: #9333ea; color: #fff; }
        .btn-purple:hover { background: #7e22ce; box-shadow: 0 0 12px rgba(147, 51, 234, 0.4); }
        .btn-emerald { background: #059669; color: #fff; }
        .btn-emerald:hover { background: #047857; box-shadow: 0 0 12px rgba(5, 150, 105, 0.4); }
        .btn-pink { background: #db2777; color: #fff; }
        .btn-pink:hover { background: #be185d; box-shadow: 0 0 12px rgba(219, 39, 119, 0.4); }

        /* ── Volume & Distribution Card ── */
        .dist-card {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 1rem 1.25rem;
            backdrop-filter: blur(14px);
        }

        .dist-bar {
            height: 10px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 999px;
            overflow: hidden;
            display: flex;
            margin: 0.75rem 0;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .dist-slice {
            height: 100%;
            transition: width 0.5s ease;
        }

        .dist-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            font-size: 0.78rem;
            color: var(--text-secondary);
        }

        .legend-tag {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
        }

        .legend-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }

        /* ── 5 Bot Command Cards (Responsive Full Grid) ── */
        .bots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem;
        }

        .bot-card {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: all 0.25s;
            position: relative;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }

        .bot-card:hover {
            border-color: var(--border-card-hover);
            transform: translateY(-2px);
            background: var(--bg-card-hover);
        }

        .bot-card-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 0.85rem;
        }

        .port-badge {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.05);
            padding: 0.25rem 0.55rem;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .bot-card-title {
            font-size: 1.15rem;
            font-weight: 800;
            margin-bottom: 0.35rem;
            color: #fff;
        }

        .bot-card-desc {
            color: var(--text-muted);
            font-size: 0.82rem;
            line-height: 1.45;
            margin-bottom: 1rem;
            min-height: 2.4rem;
        }

        .bot-stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 0.65rem;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 10px;
            padding: 0.85rem;
            margin-bottom: 1.15rem;
        }

        .stat-item-label {
            font-size: 0.68rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 2px;
        }

        .stat-item-val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.98rem;
            font-weight: 700;
        }

        /* ── Live Positions Inspector ── */
        .positions-card {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            padding: 1.25rem;
            backdrop-filter: blur(16px);
        }

        .badge-buy {
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-weight: 700;
            font-size: 0.72rem;
        }

        .badge-sell {
            background: rgba(244, 63, 94, 0.15);
            color: #f43f5e;
            border: 1px solid rgba(244, 63, 94, 0.3);
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-weight: 700;
            font-size: 0.72rem;
        }

        /* ── Footer ── */
        footer {
            margin-top: 1rem;
            padding: 1rem 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.75rem;
            color: var(--text-muted);
            font-size: 0.8rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        .footer-links {
            display: flex;
            gap: 1rem;
        }

        .footer-link {
            color: var(--text-secondary);
            text-decoration: none;
            transition: color 0.2s;
        }

        .footer-link:hover {
            color: var(--accent-cyan);
        }

        @media (max-width: 900px) {
            .fullscreen-shell { padding: 0.75rem 1rem; }
            .kpi-strip { grid-template-columns: repeat(2, 1fr); }
            .market-sessions { display: none; }
        }

        @media (max-width: 580px) {
            .kpi-strip { grid-template-columns: 1fr; }
            .controls-ribbon { width: 100%; justify-content: space-between; }
        }
    </style>
</head>
<body>
    <div class="fullscreen-shell">

        <!-- Top Navigation Ribbon -->
        <header class="nav-ribbon">
            <div class="brand-group">
                <div class="brand-icon">⚡</div>
                <div>
                    <div class="brand-title">Profity AI Command Hub</div>
                    <div style="font-size: 0.74rem; color: var(--text-muted);">Institutional Multi-Bot Algorithmic Execution Core</div>
                </div>
                <div class="vps-status-pill">
                    <span class="dot-live"></span>
                    <span id="vps-tag">169.58.190.245 • 5 BOTS LINKED</span>
                </div>
            </div>

            <!-- Global Market Clocks -->
            <div class="market-sessions" id="marketSessions">
                <span class="session-badge" id="sess-london">London: <strong id="london-status">--</strong></span>
                <span class="session-badge" id="sess-ny">New York: <strong id="ny-status">--</strong></span>
                <span class="session-badge" id="sess-tokyo">Tokyo: <strong id="tokyo-status">--</strong></span>
                <span class="clock-utc" id="clockUtc">UTC --:--:--</span>
            </div>

            <!-- Action Controls -->
            <div class="controls-ribbon">
                <div class="toggle-group">
                    <button class="toggle-btn active" id="btn-unit-usc" onclick="setUnit('USC')">USC (Cents)</button>
                    <button class="toggle-btn" id="btn-unit-usd" onclick="setUnit('USD')">USD ($)</button>
                </div>

                <div class="toggle-group">
                    <button class="toggle-btn" onclick="setPeriod('today')" id="tab-today">Today</button>
                    <button class="toggle-btn" onclick="setPeriod('7d')" id="tab-7d">7D</button>
                    <button class="toggle-btn active" onclick="setPeriod('30d')" id="tab-30d">30D</button>
                    <button class="toggle-btn" onclick="setPeriod('all')" id="tab-all">All</button>
                </div>

                <button class="btn-action" id="btn-manual-refresh" onclick="refreshData(true)" title="Instant Poll">
                    <span id="refresh-icon">🔄</span> <span id="refresh-counter">5s</span>
                </button>

                <button class="btn-action btn-fullscreen" id="btn-fullscreen" onclick="toggleFullscreen()" title="Toggle Fullscreen UI">
                    <span id="fs-icon">⛶</span> Fullscreen
                </button>
            </div>
        </header>

        <!-- 6-Card Institutional KPI Banner -->
        <section class="kpi-strip">
            <!-- 1. Equity -->
            <div class="kpi-tile">
                <div class="kpi-header">
                    <span class="kpi-label">Combined Equity</span>
                    <span class="kpi-icon" style="color: var(--accent-cyan);">💎</span>
                </div>
                <div class="kpi-val" id="kpi-equity">--</div>
                <div class="kpi-footer">
                    <span>Balance: <strong id="kpi-balance" class="mono" style="color:#fff;">--</strong></span>
                    <span id="kpi-equity-delta" class="mono">--</span>
                </div>
            </div>

            <!-- 2. Margin & Free Margin -->
            <div class="kpi-tile">
                <div class="kpi-header">
                    <span class="kpi-label">Margin Utilization</span>
                    <span class="kpi-icon" style="color: var(--accent-amber);">🛡️</span>
                </div>
                <div class="kpi-val" id="kpi-margin-level">--%</div>
                <div class="kpi-footer">
                    <span>Free: <strong id="kpi-margin-free" class="mono" style="color:#fff;">--</strong></span>
                    <span>Used: <strong id="kpi-margin-used" class="mono" style="color:var(--text-muted);">--</strong></span>
                </div>
            </div>

            <!-- 3. Floating PnL & Exposure -->
            <div class="kpi-tile">
                <div class="kpi-header">
                    <span class="kpi-label">Unrealized Floating P&L</span>
                    <span class="kpi-icon" style="color: var(--accent-green);">⚡</span>
                </div>
                <div class="kpi-val" id="kpi-floating">--</div>
                <div class="kpi-footer">
                    <span><strong id="kpi-open-trades" style="color:#fff;">0</strong> Pos (<span id="kpi-open-lots" class="mono">0.00</span> Lots)</span>
                    <span id="kpi-bias-pill" style="font-size: 0.72rem; color: var(--text-secondary);">Neutral</span>
                </div>
            </div>

            <!-- 4. Realized Period PnL -->
            <div class="kpi-tile">
                <div class="kpi-header">
                    <span class="kpi-label" id="kpi-pnl-label">Realized Profit (30D)</span>
                    <span class="kpi-icon" style="color: var(--accent-amber);">📊</span>
                </div>
                <div class="kpi-val" id="kpi-pnl">--</div>
                <div class="kpi-footer">
                    <span id="kpi-pnl-sub">All-Time: --</span>
                    <span id="kpi-roi-pill" class="mono" style="color: var(--accent-cyan);">ROI: --</span>
                </div>
            </div>

            <!-- 5. Win Rate & Trades -->
            <div class="kpi-tile">
                <div class="kpi-header">
                    <span class="kpi-label">Win Rate & Ratio</span>
                    <span class="kpi-icon" style="color: var(--accent-purple);">🎯</span>
                </div>
                <div class="kpi-val val-neutral" id="kpi-winrate">--%</div>
                <div class="kpi-footer">
                    <span><strong id="kpi-wins" class="val-positive">--</strong>W / <strong id="kpi-losses" class="val-negative">--</strong>L</span>
                    <span>PF: <strong id="kpi-pf" class="mono" style="color:#fff;">--</strong></span>
                </div>
            </div>

            <!-- 6. Total Execution Volume -->
            <div class="kpi-tile">
                <div class="kpi-header">
                    <span class="kpi-label">Volume & Extreme Deals</span>
                    <span class="kpi-icon" style="color: var(--accent-pink);">📈</span>
                </div>
                <div class="kpi-val" id="kpi-trades-count">--</div>
                <div class="kpi-footer">
                    <span>Best: <strong id="kpi-best-trade" class="val-positive mono">--</strong></span>
                    <span>Worst: <strong id="kpi-worst-trade" class="val-negative mono">--</strong></span>
                </div>
            </div>
        </section>

        <!-- Multi-Bot Profit Comparison Matrix -->
        <section>
            <div class="section-bar">
                <div class="section-heading">
                    <span>🏆</span> Multi-Bot Profit Comparison Matrix
                </div>
                <div style="font-size: 0.8rem; color: var(--text-muted);">
                    Live High-Frequency MT5 Bridge Streaming (:8001-:8005)
                </div>
            </div>

            <div class="table-card" style="margin-top: 0.75rem;">
                <div class="table-responsive">
                    <table class="comparison-table">
                        <thead>
                            <tr>
                                <th>Trading Engine / Strategy</th>
                                <th>Account & Server</th>
                                <th>Balance & Equity</th>
                                <th>Margin / Level</th>
                                <th>Floating P&L (Lots)</th>
                                <th id="th-period-pnl">Realized Profit (30D)</th>
                                <th>Win Rate & Record</th>
                                <th>Profit Factor / Payoff</th>
                                <th>Best / Worst Deal</th>
                                <th>Bridge Ping</th>
                                <th>Desk Action</th>
                            </tr>
                        </thead>
                        <tbody id="comparison-tbody">
                            <tr>
                                <td colspan="11" style="text-align: center; padding: 2.5rem; color: var(--text-muted);">
                                    Connecting to MT5 terminal bridges...
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

        <!-- Volume & Profit Allocation Bars -->
        <section class="dist-card">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
                <div style="font-weight: 700; font-size: 0.92rem; color: #fff;">
                    📊 Multi-Bot Volume & Profit Contribution Share
                </div>
                <div style="font-size: 0.78rem; color: var(--text-muted);" id="dist-period-label">
                    30-Day Distribution
                </div>
            </div>

            <div class="dist-bar" id="distribution-bar">
                <div class="dist-slice" style="width: 20%; background: #38bdf8;"></div>
                <div class="dist-slice" style="width: 20%; background: #f59e0b;"></div>
                <div class="dist-slice" style="width: 20%; background: #a855f7;"></div>
                <div class="dist-slice" style="width: 20%; background: #10b981;"></div>
                <div class="dist-slice" style="width: 20%; background: #ec4899;"></div>
            </div>

            <div class="dist-legend" id="distribution-legend">
                <div class="legend-tag"><div class="legend-dot" style="background: #38bdf8;"></div> Bot #1 Auto Grid: --</div>
                <div class="legend-tag"><div class="legend-dot" style="background: #f59e0b;"></div> Bot #2 Manual Desk: --</div>
                <div class="legend-tag"><div class="legend-dot" style="background: #a855f7;"></div> Bot #3 Trend Runner: --</div>
                <div class="legend-tag"><div class="legend-dot" style="background: #10b981;"></div> Bot #4 SMC Hunter: --</div>
                <div class="legend-tag"><div class="legend-dot" style="background: #ec4899;"></div> Bot #5 AI Ensemble: --</div>
            </div>
        </section>

        <!-- 5 Bot Dedicated Command Cards -->
        <section>
            <div class="section-bar">
                <div class="section-heading">
                    <span>🚀</span> Individual Bot Control Desks
                </div>
                <div style="font-size: 0.8rem; color: var(--text-muted);">
                    Direct Port Handshakes: 8501, 8502, 8503, 8504, 8505
                </div>
            </div>

            <div class="bots-grid" style="margin-top: 0.75rem;">
                <!-- Bot 1: Auto Grid -->
                <div class="bot-card">
                    <div>
                        <div class="bot-card-top">
                            <div class="bot-avatar icon-bot1">⚡</div>
                            <span class="port-badge">PORT 8501</span>
                        </div>
                        <div class="bot-card-title">Bot #1 — Auto Grid</div>
                        <div class="bot-card-desc">Breakout Grid Engine with Smart Runner Mode, Auto-Regime Reading, and Hardened Risk Ceilings.</div>
                        <div class="bot-stats-grid">
                            <div>
                                <div class="stat-item-label">Live Equity</div>
                                <div class="stat-item-val mono" id="b1-equity">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Floating P&L</div>
                                <div class="stat-item-val mono" id="b1-floating">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label" id="b1-pnl-label">30D Realized</div>
                                <div class="stat-item-val mono" id="b1-pnl">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Win Rate</div>
                                <div class="stat-item-val mono val-neutral" id="b1-winrate">--</div>
                            </div>
                        </div>
                    </div>
                    <a id="link-bot1" href="http://" class="btn-desk btn-blue" style="justify-content: center;">Open Auto Grid Desk &rarr;</a>
                </div>

                <!-- Bot 2: Manual Desk -->
                <div class="bot-card">
                    <div>
                        <div class="bot-card-top">
                            <div class="bot-avatar icon-bot2">🕹️</div>
                            <span class="port-badge">PORT 8502</span>
                        </div>
                        <div class="bot-card-title">Bot #2 — Manual Grid Desk</div>
                        <div class="bot-card-desc">Interactive manual control panel for precision trap deployment, live monitoring, and manual cycle executions.</div>
                        <div class="bot-stats-grid">
                            <div>
                                <div class="stat-item-label">Live Equity</div>
                                <div class="stat-item-val mono" id="b2-equity">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Floating P&L</div>
                                <div class="stat-item-val mono" id="b2-floating">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label" id="b2-pnl-label">30D Realized</div>
                                <div class="stat-item-val mono" id="b2-pnl">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Win Rate</div>
                                <div class="stat-item-val mono val-neutral" id="b2-winrate">--</div>
                            </div>
                        </div>
                    </div>
                    <a id="link-bot2" href="http://" class="btn-desk btn-gold" style="justify-content: center;">Open Manual Desk &rarr;</a>
                </div>

                <!-- Bot 3: Trend Runner -->
                <div class="bot-card">
                    <div>
                        <div class="bot-card-top">
                            <div class="bot-avatar icon-bot3">📈</div>
                            <span class="port-badge">PORT 8503</span>
                        </div>
                        <div class="bot-card-title">Bot #3 — London Asian Trend</div>
                        <div class="bot-card-desc">24/7 autonomous Asian session box breakout & London trend confirmation trading system.</div>
                        <div class="bot-stats-grid">
                            <div>
                                <div class="stat-item-label">Live Equity</div>
                                <div class="stat-item-val mono" id="b3-equity">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Floating P&L</div>
                                <div class="stat-item-val mono" id="b3-floating">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label" id="b3-pnl-label">30D Realized</div>
                                <div class="stat-item-val mono" id="b3-pnl">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Win Rate</div>
                                <div class="stat-item-val mono val-neutral" id="b3-winrate">--</div>
                            </div>
                        </div>
                    </div>
                    <a id="link-bot3" href="http://" class="btn-desk btn-purple" style="justify-content: center;">Open Trend Panel &rarr;</a>
                </div>

                <!-- Bot 4: SMC Hunter -->
                <div class="bot-card">
                    <div>
                        <div class="bot-card-top">
                            <div class="bot-avatar icon-bot4">🎯</div>
                            <span class="port-badge">PORT 8504</span>
                        </div>
                        <div class="bot-card-title">Bot #4 — SMC Liquidity Hunter</div>
                        <div class="bot-card-desc">Institutional liquidity sweep & FVG reversal engine fading fakeouts at session highs/lows.</div>
                        <div class="bot-stats-grid">
                            <div>
                                <div class="stat-item-label">Live Equity</div>
                                <div class="stat-item-val mono" id="b4-equity">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Floating P&L</div>
                                <div class="stat-item-val mono" id="b4-floating">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label" id="b4-pnl-label">30D Realized</div>
                                <div class="stat-item-val mono" id="b4-pnl">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Win Rate</div>
                                <div class="stat-item-val mono val-neutral" id="b4-winrate">--</div>
                            </div>
                        </div>
                    </div>
                    <a id="link-bot4" href="http://" class="btn-desk btn-emerald" style="justify-content: center;">Open SMC Panel &rarr;</a>
                </div>

                <!-- Bot 5: AI Ensemble -->
                <div class="bot-card">
                    <div>
                        <div class="bot-card-top">
                            <div class="bot-avatar icon-bot5">🤖</div>
                            <span class="port-badge">PORT 8505</span>
                        </div>
                        <div class="bot-card-title">Bot #5 — AI/ML Neural Trader</div>
                        <div class="bot-card-desc">Multi-model Deep RL ensemble & institutional market regime detection engine for Gold.</div>
                        <div class="bot-stats-grid">
                            <div>
                                <div class="stat-item-label">Live Equity</div>
                                <div class="stat-item-val mono" id="b5-equity">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Floating P&L</div>
                                <div class="stat-item-val mono" id="b5-floating">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label" id="b5-pnl-label">30D Realized</div>
                                <div class="stat-item-val mono" id="b5-pnl">--</div>
                            </div>
                            <div>
                                <div class="stat-item-label">Win Rate</div>
                                <div class="stat-item-val mono val-neutral" id="b5-winrate">--</div>
                            </div>
                        </div>
                    </div>
                    <a id="link-bot5" href="http://" class="btn-desk btn-pink" style="justify-content: center;">Open AI Panel &rarr;</a>
                </div>
            </div>
        </section>

        <!-- Live Active Market Positions Feed -->
        <section class="positions-card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.85rem; flex-wrap: wrap; gap: 0.5rem;">
                <div style="font-weight: 800; font-size: 1.05rem; display: flex; align-items: center; gap: 0.5rem;">
                    <span>⚡</span> Live Active Market Positions
                    <span class="vps-status-pill" id="pos-count-pill" style="font-size: 0.7rem; padding: 0.15rem 0.5rem;">0 Open</span>
                </div>
                <div style="font-size: 0.8rem; color: var(--text-muted);">
                    Real-time floating P&L synchronized across all 5 MT5 instances
                </div>
            </div>

            <div class="table-responsive">
                <table class="comparison-table" style="font-size: 0.83rem;">
                    <thead>
                        <tr>
                            <th>Ticket</th>
                            <th>Engine Source</th>
                            <th>Symbol</th>
                            <th>Direction</th>
                            <th>Volume (Lots)</th>
                            <th>Open Price</th>
                            <th>Current Price</th>
                            <th>SL / TP</th>
                            <th>Floating P&L</th>
                        </tr>
                    </thead>
                    <tbody id="positions-tbody">
                        <tr>
                            <td colspan="9" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">
                                No open positions active across engines. Market scanner standing by.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Footer -->
        <footer>
            <div>
                Profity AI Systems &bull; High Frequency / Low Latency Deployment &bull; <strong>169.58.190.245</strong>
            </div>
            <div class="footer-links">
                <a id="link-vnc" href="http://169.58.190.245:8006" target="_blank" class="footer-link">🖥️ Wine MT5 Screen (:8006)</a>
                <a href="#marketSessions" class="footer-link">Market Sessions</a>
                <a href="#comparison-tbody" class="footer-link">Comparison Matrix</a>
            </div>
        </footer>

    </div>

    <script>
        // State
        let currentUnit = 'USC';
        let currentPeriod = '30d';
        let liveData = null;
        let refreshSeconds = 5;
        let timerInterval = null;

        // Dynamic target links
        const host = window.location.hostname || "169.58.190.245";
        document.getElementById("link-bot1").href = "http://" + host + ":8501";
        document.getElementById("link-bot2").href = "http://" + host + ":8502";
        document.getElementById("link-bot3").href = "http://" + host + ":8503";
        document.getElementById("link-bot4").href = "http://" + host + ":8504";
        document.getElementById("link-bot5").href = "http://" + host + ":8505";
        document.getElementById("link-vnc").href = "http://" + host + ":8006";

        // Fullscreen API toggle
        function toggleFullscreen() {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(err => {
                    console.warn("Fullscreen request error:", err);
                });
                document.getElementById("fs-icon").innerText = "🗗";
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                    document.getElementById("fs-icon").innerText = "⛶";
                }
            }
        }

        document.addEventListener("fullscreenchange", () => {
            const isFs = !!document.fullscreenElement;
            document.getElementById("fs-icon").innerText = isFs ? "🗗" : "⛶";
            document.getElementById("btn-fullscreen").classList.toggle("active", isFs);
        });

        // Market Clocks & UTC Ticker
        function updateClocks() {
            const now = new Date();
            const utcHours = now.getUTCHours();
            const utcMins = now.getUTCMinutes();
            const utcSecs = now.getUTCSeconds();
            
            const pad = (n) => n < 10 ? '0' + n : n;
            document.getElementById("clockUtc").innerText = `UTC ${pad(utcHours)}:${pad(utcMins)}:${pad(utcSecs)}`;

            // London (08:00 - 16:30 UTC)
            const londonOpen = (utcHours >= 8 && (utcHours < 16 || (utcHours === 16 && utcMins <= 30)));
            const elLon = document.getElementById("sess-london");
            document.getElementById("london-status").innerText = londonOpen ? "OPEN" : "CLOSED";
            elLon.className = "session-badge " + (londonOpen ? "session-open" : "");

            // New York (13:00 - 21:30 UTC)
            const nyOpen = (utcHours >= 13 && (utcHours < 21 || (utcHours === 21 && utcMins <= 30)));
            const elNy = document.getElementById("sess-ny");
            document.getElementById("ny-status").innerText = nyOpen ? "OPEN" : "CLOSED";
            elNy.className = "session-badge " + (nyOpen ? "session-open" : "");

            // Tokyo (00:00 - 09:00 UTC)
            const tokyoOpen = (utcHours >= 0 && utcHours < 9);
            const elTok = document.getElementById("sess-tokyo");
            document.getElementById("tokyo-status").innerText = tokyoOpen ? "OPEN" : "CLOSED";
            elTok.className = "session-badge " + (tokyoOpen ? "session-open" : "");
        }
        setInterval(updateClocks, 1000);
        updateClocks();

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
            document.getElementById("dist-period-label").innerText = period.toUpperCase() + " Distribution";
            
            ['b1', 'b2', 'b3', 'b4', 'b5'].forEach(id => {
                const el = document.getElementById(id + "-pnl-label");
                if (el) el.innerText = period.toUpperCase() + " Realized";
            });

            renderUI();
        }

        function formatMoney(amountUsc, showSign = false) {
            const val = currentUnit === 'USD' ? (amountUsc / 100.0) : amountUsc;
            const sign = (showSign && val > 0.001) ? "+" : "";
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
                refreshSeconds = 5;
            }
        }

        function renderUI() {
            if (!liveData || !liveData.portfolio) return;
            const p = liveData.portfolio;
            const bots = liveData.bots || [];

            // 1. KPI Strip
            document.getElementById("kpi-equity").innerText = formatMoney(p.total_equity_usc);
            document.getElementById("kpi-balance").innerText = formatMoney(p.total_balance_usc);
            
            const deltaUsc = p.total_equity_usc - p.total_balance_usc;
            const deltaEl = document.getElementById("kpi-equity-delta");
            deltaEl.innerText = formatMoney(deltaUsc, true);
            deltaEl.className = "mono " + getPnlColorClass(deltaUsc);

            // Margin
            const mLevel = p.total_margin_level || 0;
            const mLevelEl = document.getElementById("kpi-margin-level");
            mLevelEl.innerText = mLevel > 0 ? mLevel.toFixed(1) + "%" : "100.0%";
            mLevelEl.className = "kpi-val " + (mLevel > 500 || mLevel === 0 ? "val-positive" : (mLevel > 200 ? "val-warning" : "val-negative"));
            document.getElementById("kpi-margin-free").innerText = formatMoney(p.total_margin_free_usc || p.total_balance_usc);
            document.getElementById("kpi-margin-used").innerText = formatMoney(p.total_margin_usc || 0);

            // Floating
            const floatingEl = document.getElementById("kpi-floating");
            floatingEl.innerText = formatMoney(p.total_floating_usc, true);
            floatingEl.className = "kpi-val " + getPnlColorClass(p.total_floating_usc);
            document.getElementById("kpi-open-trades").innerText = p.active_positions;
            document.getElementById("kpi-open-lots").innerText = (p.total_open_lots || 0).toFixed(2);

            const buyLots = p.total_buy_lots || 0;
            const sellLots = p.total_sell_lots || 0;
            const biasEl = document.getElementById("kpi-bias-pill");
            if (buyLots > sellLots) {
                biasEl.innerText = `Long Bias (${buyLots.toFixed(2)} vs ${sellLots.toFixed(2)}L)`;
                biasEl.style.color = "var(--accent-green)";
            } else if (sellLots > buyLots) {
                biasEl.innerText = `Short Bias (${sellLots.toFixed(2)} vs ${buyLots.toFixed(2)}L)`;
                biasEl.style.color = "var(--accent-rose)";
            } else {
                biasEl.innerText = `Neutral (0.00 L)`;
                biasEl.style.color = "var(--text-secondary)";
            }

            // Period PnL
            let periodPnl = p.pnl_30d_usc;
            let periodTrades = p.trades_30d;
            let periodWins = p.wins_30d;
            let periodLosses = p.losses_30d;
            let periodWinRate = p.win_rate_30d;

            if (currentPeriod === 'today') {
                periodPnl = p.pnl_today_usc;
                periodTrades = p.trades_today;
                periodWins = p.wins_today;
                periodLosses = p.losses_today;
                periodWinRate = p.win_rate_today;
            } else if (currentPeriod === '7d') {
                periodPnl = p.pnl_7d_usc;
                periodTrades = p.trades_7d;
                periodWins = p.wins_7d;
                periodLosses = p.losses_7d;
                periodWinRate = p.win_rate_7d;
            } else if (currentPeriod === 'all') {
                periodPnl = p.pnl_all_usc;
                periodTrades = p.trades_all;
                periodWins = p.wins_all;
                periodLosses = p.losses_all;
                periodWinRate = p.win_rate_all;
            }

            const pnlEl = document.getElementById("kpi-pnl");
            pnlEl.innerText = formatMoney(periodPnl, true);
            pnlEl.className = "kpi-val " + getPnlColorClass(periodPnl);
            document.getElementById("kpi-pnl-sub").innerText = "All-Time: " + formatMoney(p.pnl_all_usc, true);

            // Estimated ROI %
            const baseBal = Math.max(100.0, p.total_balance_usc - periodPnl);
            const roiPct = ((periodPnl / baseBal) * 100).toFixed(1);
            document.getElementById("kpi-roi-pill").innerText = "ROI: " + (roiPct > 0 ? "+" : "") + roiPct + "%";
            document.getElementById("kpi-roi-pill").className = "mono " + getPnlColorClass(periodPnl);

            // Win Rate & Trades
            document.getElementById("kpi-winrate").innerText = periodWinRate.toFixed(1) + "%";
            document.getElementById("kpi-wins").innerText = periodWins;
            document.getElementById("kpi-losses").innerText = periodLosses;
            document.getElementById("kpi-pf").innerText = (p.profit_factor_30d || 1.0).toFixed(2);
            document.getElementById("kpi-trades-count").innerText = periodTrades.toLocaleString() + " Deals";

            // Extreme Deals across bots
            let bestDeal = Math.max(...bots.map(b => b.best_trade_30d || 0));
            let worstDeal = Math.min(...bots.map(b => b.worst_trade_30d || 0));
            document.getElementById("kpi-best-trade").innerText = formatMoney(bestDeal, true);
            document.getElementById("kpi-worst-trade").innerText = formatMoney(worstDeal, true);

            // 2. Comparison Table
            const tbody = document.getElementById("comparison-tbody");
            tbody.innerHTML = "";

            const btnColors = {
                1: "btn-blue",
                2: "btn-gold",
                3: "btn-purple",
                4: "btn-emerald",
                5: "btn-pink"
            };

            bots.forEach(b => {
                let botPnl = b.pnl_30d;
                let botTrades = b.trades_30d;
                let botWins = b.wins_30d;
                let botLosses = b.losses_30d;
                let botWinRate = b.win_rate_30d;

                if (currentPeriod === 'today') {
                    botPnl = b.pnl_today;
                    botTrades = b.trades_today;
                    botWins = b.wins_today;
                    botLosses = b.losses_today;
                    botWinRate = b.win_rate_today;
                } else if (currentPeriod === '7d') {
                    botPnl = b.pnl_7d;
                    botTrades = b.trades_7d;
                    botWins = b.wins_7d;
                    botLosses = b.losses_7d;
                    botWinRate = b.win_rate_7d;
                } else if (currentPeriod === 'all') {
                    botPnl = b.pnl_all;
                    botTrades = b.trades_all;
                    botWins = b.wins_all;
                    botLosses = b.losses_all;
                    botWinRate = b.win_rate_all;
                }

                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>
                        <div class="bot-cell">
                            <div class="bot-avatar icon-bot${b.id}">${b.icon}</div>
                            <div>
                                <div class="bot-name">
                                    ${b.name}
                                    <span class="badge-strategy" style="background: ${b.color}22; color: ${b.color}; border: 1px solid ${b.color}44;">${b.tag}</span>
                                </div>
                                <div class="bot-strategy-desc">${b.strategy}</div>
                            </div>
                        </div>
                    </td>
                    <td>
                        <div class="mono" style="color: #fff; font-size: 0.9rem;">#${b.account}</div>
                        <div style="font-size: 0.74rem; color: var(--text-muted);">${b.server} &bull; 1:${b.leverage || 2000}</div>
                    </td>
                    <td>
                        <div class="mono" style="color: #fff; font-size: 0.95rem;">${formatMoney(b.equity)}</div>
                        <div style="font-size: 0.75rem; color: var(--text-muted);">Bal: ${formatMoney(b.balance)}</div>
                    </td>
                    <td>
                        <div class="mono" style="color: ${(b.margin_level > 500 || b.margin_level === 0) ? 'var(--accent-green)' : 'var(--accent-amber)'}; font-size: 0.9rem;">
                            ${b.margin_level > 0 ? b.margin_level.toFixed(1) + '%' : '100.0%'}
                        </div>
                        <div style="font-size: 0.74rem; color: var(--text-muted);">Used: ${formatMoney(b.margin || 0)}</div>
                    </td>
                    <td>
                        <span class="mono ${getPnlColorClass(b.floating_pnl)}" style="font-size: 0.95rem;">
                            ${formatMoney(b.floating_pnl, true)}
                        </span>
                        <div style="font-size: 0.75rem; color: var(--text-muted);">${b.active_positions} Pos (${(b.open_lots || 0).toFixed(2)}L)</div>
                    </td>
                    <td>
                        <div class="${getPnlBadgeClass(botPnl)}">
                            ${formatMoney(botPnl, true)}
                        </div>
                    </td>
                    <td>
                        <div class="win-bar-wrap">
                            <div style="display: flex; justify-content: space-between; font-size: 0.8rem;">
                                <span class="mono" style="color: #fff; font-weight: 700;">${botWinRate.toFixed(1)}%</span>
                                <span style="color: var(--text-muted); font-size: 0.74rem;">${botWins}W/${botLosses}L</span>
                            </div>
                            <div class="win-bar-bg">
                                <div class="win-bar-fill" style="width: ${Math.min(100, Math.max(0, botWinRate))}%; background: ${b.color};"></div>
                            </div>
                        </div>
                    </td>
                    <td>
                        <span class="mono" style="color: #cbd5e1; font-size: 0.9rem;">PF: ${b.profit_factor_30d || '1.0'}</span>
                        <div style="font-size: 0.74rem; color: var(--text-muted);">Payoff: ${b.payoff_ratio_30d || '1.0'}x</div>
                    </td>
                    <td>
                        <div class="val-positive mono" style="font-size: 0.82rem;">${formatMoney(b.best_trade_30d || 0, true)}</div>
                        <div class="val-negative mono" style="font-size: 0.82rem;">${formatMoney(b.worst_trade_30d || 0, true)}</div>
                    </td>
                    <td>
                        <span class="status-pill">
                            <span class="dot-live" style="width: 5px; height: 5px;"></span>
                            ${b.latency_ms || 12}ms
                        </span>
                    </td>
                    <td>
                        <a href="http://${host}:${b.panel_port}" class="btn-desk ${btnColors[b.id] || 'btn-blue'}">
                            Open Desk &rarr;
                        </a>
                    </td>
                `;
                tbody.appendChild(tr);

                // Update Bot Card
                const bId = "b" + b.id;
                const eqEl = document.getElementById(bId + "-equity");
                if (eqEl) eqEl.innerText = formatMoney(b.equity);

                const flEl = document.getElementById(bId + "-floating");
                if (flEl) {
                    flEl.innerText = formatMoney(b.floating_pnl, true);
                    flEl.className = "stat-item-val mono " + getPnlColorClass(b.floating_pnl);
                }

                const pnlCardEl = document.getElementById(bId + "-pnl");
                if (pnlCardEl) {
                    pnlCardEl.innerText = formatMoney(botPnl, true);
                    pnlCardEl.className = "stat-item-val mono " + getPnlColorClass(botPnl);
                }

                const wrCardEl = document.getElementById(bId + "-winrate");
                if (wrCardEl) wrCardEl.innerText = botWinRate.toFixed(1) + "%";
            });

            // 3. Update Volume Distribution Bar
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
                    slice.className = "dist-slice";
                    slice.style.width = pct + "%";
                    slice.style.background = b.color;
                    slice.title = `${b.name}: ${pct}% (${bTrades} deals)`;
                    distContainer.appendChild(slice);

                    const leg = document.createElement("div");
                    leg.className = "legend-tag";
                    leg.innerHTML = `<div class="legend-dot" style="background: ${b.color};"></div> ${b.name}: <strong>${pct}%</strong> (${bTrades} deals)`;
                    legendContainer.appendChild(leg);
                });
            }

            // 4. Update Live Positions Feed
            const posTbody = document.getElementById("positions-tbody");
            const posCountPill = document.getElementById("pos-count-pill");
            const allPositions = p.all_positions || [];

            posCountPill.innerText = `${allPositions.length} Open (${(p.total_open_lots || 0).toFixed(2)} Lots)`;

            if (allPositions.length === 0) {
                posTbody.innerHTML = `
                    <tr>
                        <td colspan="9" style="text-align: center; padding: 2rem; color: var(--text-muted);">
                            ✨ All 5 engines are flat. No floating drawdown. Standing by for high-probability setups.
                        </td>
                    </tr>
                `;
            } else {
                posTbody.innerHTML = "";
                allPositions.forEach(pos => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td class="mono" style="color: #fff; font-size: 0.85rem;">#${pos.ticket}</td>
                        <td>
                            <span class="badge-strategy" style="background: ${pos.bot_color}22; color: ${pos.bot_color}; border: 1px solid ${pos.bot_color}44;">
                                ${pos.bot_tag}
                            </span>
                        </td>
                        <td class="mono" style="font-weight: 700; color: #fff;">${pos.symbol}</td>
                        <td>
                            <span class="${pos.type === 'BUY' ? 'badge-buy' : 'badge-sell'}">${pos.type}</span>
                        </td>
                        <td class="mono">${pos.volume.toFixed(2)}</td>
                        <td class="mono">${pos.price_open.toFixed(3)}</td>
                        <td class="mono" style="color: #fff;">${pos.price_current.toFixed(3)}</td>
                        <td class="mono" style="font-size: 0.76rem; color: var(--text-muted);">
                            SL: ${pos.sl > 0 ? pos.sl.toFixed(3) : '--'} / TP: ${pos.tp > 0 ? pos.tp.toFixed(3) : '--'}
                        </td>
                        <td>
                            <span class="mono ${getPnlColorClass(pos.profit)}" style="font-weight: 700; font-size: 0.95rem;">
                                ${formatMoney(pos.profit, true)}
                            </span>
                        </td>
                    `;
                    posTbody.appendChild(tr);
                });
            }
        }

        // Auto-refresh countdown interval
        setInterval(() => {
            refreshSeconds--;
            if (refreshSeconds <= 0) {
                refreshData();
                refreshSeconds = 5;
            }
            const cnt = document.getElementById("refresh-counter");
            if (cnt) cnt.innerText = refreshSeconds + "s";
        }, 1000);

        // Initial fetch
        refreshData();
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
                "bot4": is_port_listening(8504),
                "bot5": is_port_listening(8505),
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
        pass

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), PortalHandler) as httpd:
        print(f"Profity AI Fullscreen Command Hub running on http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run()
