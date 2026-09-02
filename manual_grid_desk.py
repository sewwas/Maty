"""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘           ðŸŽ›ï¸  PROFITY AI â€” MANUAL GRID DESK                     â•‘
â•‘        Standalone Manual Grid Trading App for XAUUSD            â•‘
â•‘                                                                  â•‘
â•‘  âš¡ 100% ISOLATED from app.py auto-bot                           â•‘
â•‘  ðŸª„ Magic Number: 777001  |  Port: 8503                         â•‘
â•‘  ðŸ“¦ Uses ONLY: core.data, core.mt5_broker                       â•‘
â•‘  âŒ NO: engine.py, auto_reading.py, grid_risk.py                â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import warnings
warnings.filterwarnings("ignore")

import time
import datetime
import os
import json
import threading
import logging

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# â”€â”€ Core Imports (ONLY data + broker, never engine or auto_reading) â”€â”€â”€â”€â”€â”€â”€â”€â”€
from core.data import get_live_price, get_historical_klines, get_default_price
from core.mt5_broker import MT5Broker, MT5_AVAILABLE
import core.mt5_broker as _brk_mod

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  CONSTANTS & CONFIGURATION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

MANUAL_MAGIC       = 777001                # Dedicated magic â€” isolated from auto bots
SYMBOL             = "PAXGUSDT"            # Binance / Coinbase price feed key
EXNESS_SYMBOL      = "XAUUSD"              # MT5 broker symbol
STATE_FILE         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_state.json")
CHART_CANDLES      = 120                   # Candles to show on chart
CHART_INTERVAL     = "15m"                 # Chart timeframe
REFRESH_SECS       = 2.0                   # Auto-refresh rate
MAX_HISTORY_ROWS   = 300                   # Max trade history rows to store

# â”€â”€ Bot #1 Bridge â€” Manual Desk reads from Bot #1's MT5 terminal (port 8001) â”€â”€
MT5_BRIDGE_PORT = "8002"
os.environ["WINE_BRIDGE_PORT"] = MT5_BRIDGE_PORT

# ── Force REST-bridge-only mode in THIS process ───────────────────────────
# We null the module-level mt5 reference so every broker call falls through 
# to the REST bridge at 8002. This prevents it from falling back to native MT5
# which is logged into Bot #1.
_brk_mod.mt5 = None


# â”€â”€ Force REST-bridge-only mode in THIS process â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The native MT5 DLL always returns the locally logged-in account (Bot #1).
# This process (port 8503) is completely isolated, so we null the module-level
# mt5 reference so every broker call falls through to the REST bridge at 8002.
# Zero effect on auto-bot processes which run in separate Python interpreters.



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  STATE PERSISTENCE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def load_state() -> dict:
    """Loads persisted manual desk state from disk."""
    default = {
        "grid_config": {
            "center_mode": "Live Price (Auto-Centered)",
            "center_price": 0.0,
            "levels_above": 3,
            "levels_below": 3,
            "offset_mode": "USD ($)",
            "offset_value": 1.50,
            "offset_pct": 0.05,
            "gap_mode": "USD ($)",
            "gap_value": 2.0,
            "gap_pct": 0.07,
            "lot_size": 0.01,
            "lot_mult": 1.0,
            "target_profit": 5.0,
            "stop_loss": 25.0,
        },
        "trade_history": [],
        "deployed": False,
        "grid_levels": [],
    }
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Merge with defaults so new keys always exist
                for k, v in default.items():
                    if k not in data:
                        data[k] = v
                if "grid_config" in data:
                    for ck, cv in default["grid_config"].items():
                        if ck not in data["grid_config"]:
                            data["grid_config"][ck] = cv
                return data
    except Exception as e:
        logging.warning(f"Manual state load: {e}")
    return default


def save_state(state: dict):
    """Saves manual desk state to disk."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.warning(f"Manual state save: {e}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  MT5 BROKER SINGLETON (cached, never recreated across refreshes)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@st.cache_resource
def get_manual_broker() -> MT5Broker:
    """
    Creates the Manual Grid Desk MT5Broker singleton with magic 777001.
    Linked to Bot #1's MT5 bridge (port 8001) â€” no hardcoded credentials.
    Account login/server/equity are read dynamically from the bridge.
    """
    # WINE_BRIDGE_PORT is already set to 8002 at module load (top of file).
    # MT5Broker picks it up automatically in every bridge call.
    _env_pass = os.environ.get("EXNESS_PASSWORD", "")
    brk = MT5Broker(
        symbol=SYMBOL,
        login=None,        # Let bridge supply login dynamically
        password=_env_pass,
        server="",         # Let bridge supply server dynamically
        magic_number=MANUAL_MAGIC,
    )
    print(f"âœ… [Manual Grid Desk] MT5Broker linked to Bot #1 bridge (port {MT5_BRIDGE_PORT}) | Magic: {MANUAL_MAGIC} | Connected: {brk.ensure_connected()}")
    return brk


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  GRID MATH  (pure function â€” no broker calls)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def get_mt5_live_price(brk: MT5Broker = None) -> float:
    """
    Fetches real-time bid/ask mid price directly from MT5 bridge for EXNESS_SYMBOL.
    Guarantees the Manual Desk is 100% centered to the broker's real market price.
    """
    try:
        import requests as _req
        r = _req.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/symbol_info?symbol={EXNESS_SYMBOL}", timeout=0.8)
        if r.status_code == 200:
            d = r.json()
            ask = float(d.get("ask", 0.0) or 0.0)
            bid = float(d.get("bid", 0.0) or 0.0)
            if ask > 0 and bid > 0:
                return round((ask + bid) / 2.0, 2)
    except Exception:
        pass
    p = get_live_price(EXNESS_SYMBOL) or get_live_price(SYMBOL) or get_default_price(EXNESS_SYMBOL)
    return round(float(p), 2)


# ══════════════════════════════════════════════════════════════════════════════
#  GRID MATH (supports live-price offset and USD ($) / % gap modes)
# ══════════════════════════════════════════════════════════════════════════════

def compute_grid_levels(
    center: float,
    gap_val: float,
    levels_above: int,
    levels_below: int,
    gap_mode: str = "USD ($)",
    offset_val: float = 1.5,
    offset_mode: str = "USD ($)"
) -> dict:
    """
    Computes grid price levels around a center price with initial Offset and consecutive Gaps.
    Supports USD ($) and Percentage (%) for both Offset and Gap.
    
    Level 1 Buy  = center + offset
    Level i Buy  = center + offset + (i-1) * gap
    Level 1 Sell = center - offset
    Level i Sell = center - offset - (i-1) * gap
    """
    # Offset calculation
    if "USD" in str(offset_mode).upper() or str(offset_mode) == "$":
        off_step = max(0.01, round(float(offset_val), 2))
    else:
        off_step = max(0.01, round(center * (float(offset_val) / 100.0), 2))

    # Gap calculation
    if "USD" in str(gap_mode).upper() or str(gap_mode) == "$":
        gap_step = max(0.01, round(float(gap_val), 2))
    else:
        gap_step = max(0.01, round(center * (float(gap_val) / 100.0), 2))

    buy_stops = sorted([
        round(center + off_step + (gap_step * i), 2)
        for i in range(levels_above)
    ])
    sell_stops = sorted([
        round(center - off_step - (gap_step * i), 2)
        for i in range(levels_below)
    ], reverse=True)

    return {
        "buy_stops": buy_stops,
        "sell_stops": sell_stops,
        "step": gap_step,
        "offset": off_step,
    }


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  LIVE MT5 DATA HELPERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def get_live_positions(brk: MT5Broker) -> list:
    """Returns open positions for magic 777001 only."""
    raw = brk._fetch_live_positions(symbol=EXNESS_SYMBOL)
    if not raw:
        raw = brk._fetch_live_positions()
    if not raw:
        return []
    return [p for p in raw if getattr(p, "magic", 0) == MANUAL_MAGIC]


def get_live_pending(brk: MT5Broker) -> list:
    """Returns pending orders for magic 777001 only."""
    raw = brk._fetch_live_orders(symbol=EXNESS_SYMBOL)
    if not raw:
        raw = brk._fetch_live_orders()
    if not raw:
        return []
    return [o for o in raw if getattr(o, "magic", 0) == MANUAL_MAGIC]


def get_total_floating_pnl(brk: MT5Broker) -> float:
    """Sums floating P&L across all open positions for magic 777001."""
    positions = get_live_positions(brk)
    return sum(float(getattr(p, "profit", 0.0)) for p in positions)


def get_account_summary(brk: MT5Broker) -> dict:
    """
    Returns live account info.
    Priority: ONLY Bot #2 bridge (port 8002). No native fallback to avoid linking to Bot #1.
    """
    try:
        import requests as _req
        r = _req.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/account", timeout=1.5)
        if r.status_code == 200:
            d = r.json()
            if d.get("connected") and int(d.get("login", 0)) > 0:
                return {
                    "login":    int(d.get("login",    0)),
                    "server":   str(d.get("server",   "")),
                    "balance":  float(d.get("balance", 0.0)),
                    "equity":   float(d.get("equity",  0.0)),
                    "leverage": int(d.get("leverage", 0)),
                    "currency": str(d.get("currency", "USD")),
                }
    except Exception:
        pass
        
    return {"login": 0, "server": "", "balance": 0.0, "equity": 0.0, "leverage": 0, "currency": "USD"}




# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  GRID ACTIONS (deploy / flatten / cancel)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def deploy_grid(brk: MT5Broker, levels: dict, lot_size: float, lot_mult: float = 1.0) -> tuple:
    """
    Places BUY_STOP orders above center and SELL_STOP orders below center.
    Applies lot multiplier per level (Martingale scaling).
    Returns (placed_count, errors_list).
    """
    placed, errors = 0, []
    ts = time.time()

    current_lot = lot_size
    for price in levels["buy_stops"]:
        try:
            actual_lot = round(current_lot, 2)
            order = brk.place_order("BUY_STOP", price=price, size=actual_lot, timestamp=ts)
            if order:
                placed += 1
        except Exception as e:
            errors.append(f"BUY_STOP @ {price:.2f} ({actual_lot}L): {e}")
        current_lot *= lot_mult

    current_lot = lot_size
    for price in levels["sell_stops"]:
        try:
            actual_lot = round(current_lot, 2)
            order = brk.place_order("SELL_STOP", price=price, size=actual_lot, timestamp=ts)
            if order:
                placed += 1
        except Exception as e:
            errors.append(f"SELL_STOP @ {price:.2f} ({actual_lot}L): {e}")
        current_lot *= lot_mult

    return placed, errors


def cancel_all_pending(brk: MT5Broker) -> str:
    """Cancels all pending orders for magic 777001."""
    try:
        brk.cancel_all_orders()
        return "âœ… All pending orders cancelled."
    except Exception as e:
        return f"âš ï¸ Cancel error: {e}"


def flatten_all(brk: MT5Broker, state: dict) -> str:
    """Cancels all pending + closes all open positions for magic 777001."""
    try:
        brk.cancel_all_orders()
    except Exception as e:
        logging.warning(f"Cancel pending: {e}")

    try:
        closed = brk.close_all_positions(
            exit_price=get_live_price(SYMBOL) or get_default_price(SYMBOL),
            timestamp=time.time(),
            symbol=SYMBOL,
        )
        total_pnl = sum(float(r.get("pnl", 0.0)) for r in closed)

        # Record to trade history
        if closed:
            ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record = {
                "time":      ts_str,
                "action":    "FLATTEN ALL",
                "count":     len(closed),
                "total_pnl": round(total_pnl, 2),
            }
            state["trade_history"].insert(0, record)
            state["trade_history"] = state["trade_history"][:MAX_HISTORY_ROWS]
        
        state["deployed"] = False
        state["grid_levels"] = []
        save_state(state)
        return f"âœ… Flattened {len(closed)} positions | Net P&L: ${total_pnl:+.2f}"
    except Exception as e:
        return f"âš ï¸ Flatten error: {e}"


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  BACKGROUND P&L MONITOR (auto-flatten daemon)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@st.cache_resource
def get_pnl_monitor():
    """
    Starts a background daemon that watches floating P&L every 1 second.
    Auto-flattens when Target Profit or Stop Loss is hit.
    Uses a shared dict for cross-thread communication.
    """
    shared = {
        "active":        False,
        "target_profit": 5.0,
        "stop_loss":     25.0,
        "last_pnl":      0.0,
        "last_msg":      "",
        "triggered":     False,
    }

    def _monitor_loop():
        while True:
            try:
                if shared["active"]:
                    brk = get_manual_broker()
                    pnl = get_total_floating_pnl(brk)
                    shared["last_pnl"] = round(pnl, 2)

                    if pnl >= shared["target_profit"] and not shared["triggered"]:
                        shared["triggered"] = True
                        shared["last_msg"] = f"ðŸŽ¯ TARGET HIT ${pnl:+.2f} â€” Auto-Flattening!"
                        try:
                            state = load_state()
                            flatten_all(brk, state)
                            shared["active"] = False
                        except Exception as fe:
                            shared["last_msg"] = f"âš ï¸ Auto-flatten error: {fe}"
                            shared["triggered"] = False

                    elif pnl <= -abs(shared["stop_loss"]) and not shared["triggered"]:
                        shared["triggered"] = True
                        shared["last_msg"] = f"ðŸ›‘ STOP LOSS ${pnl:+.2f} â€” Auto-Flattening!"
                        try:
                            state = load_state()
                            flatten_all(brk, state)
                            shared["active"] = False
                        except Exception as fe:
                            shared["last_msg"] = f"âš ï¸ Auto-flatten error: {fe}"
                            shared["triggered"] = False
                    else:
                        shared["triggered"] = False
            except Exception as e:
                logging.warning(f"[PnL Monitor] {e}")
            time.sleep(1.0)

    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    return shared


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  CHART BUILDER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def build_chart(df: pd.DataFrame, grid_levels: dict, center_price: float, current_price: float) -> go.Figure:
    """
    Builds a Plotly candlestick chart with grid level lines overlaid.
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.80, 0.20],
        vertical_spacing=0.03,
    )

    # Candlestick (aligned with MT5 live price)
    if df is not None and len(df) > 0:
        df = df.copy()
        if current_price > 0 and "close" in df.columns:
            last_close = float(df["close"].iloc[-1])
            diff = current_price - last_close
            if abs(diff) > 0.5:
                df["open"] = df["open"] + diff
                df["high"] = df["high"] + diff
                df["low"] = df["low"] + diff
                df["close"] = df["close"] + diff
        times = pd.to_datetime(df["timestamp"], unit="s")
        fig.add_trace(go.Candlestick(
            x=times,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="XAUUSD",
            increasing=dict(fillcolor="#22c55e", line=dict(color="#22c55e", width=1)),
            decreasing=dict(fillcolor="#ef4444", line=dict(color="#ef4444", width=1)),
            showlegend=False,
        ), row=1, col=1)

        # Volume bars
        vol_colors = ["#22c55e" if c >= o else "#ef4444"
                      for c, o in zip(df["close"], df["open"])]
        fig.add_trace(go.Bar(
            x=times, y=df["volume"],
            marker_color=vol_colors,
            name="Volume",
            showlegend=False,
            opacity=0.6,
        ), row=2, col=1)

    # Current price line
    if current_price > 0:
        fig.add_hline(
            y=current_price,
            line=dict(color="#facc15", width=1.5, dash="dot"),
            row=1, col=1,
        )

    # Center price line
    if center_price > 0:
        fig.add_hline(
            y=center_price,
            line=dict(color="#a78bfa", width=1, dash="dash"),
            annotation_text="Center",
            annotation_font_color="#a78bfa",
            annotation_position="right",
            row=1, col=1,
        )

    # BUY_STOP grid lines (above â€” green dashed)
    for i, price in enumerate(grid_levels.get("buy_stops", [])):
        fig.add_hline(
            y=price,
            line=dict(color="#22c55e", width=1, dash="dash"),
            annotation_text=f"BUY L{i+1} {price:.2f}",
            annotation_font_color="#22c55e",
            annotation_font_size=10,
            annotation_position="right",
            row=1, col=1,
        )

    # SELL_STOP grid lines (below â€” red dashed)
    for i, price in enumerate(grid_levels.get("sell_stops", [])):
        fig.add_hline(
            y=price,
            line=dict(color="#ef4444", width=1, dash="dash"),
            annotation_text=f"SELL L{i+1} {price:.2f}",
            annotation_font_color="#ef4444",
            annotation_font_size=10,
            annotation_position="right",
            row=1, col=1,
        )

    fig.update_layout(
        height=520,
        margin=dict(l=10, r=120, t=30, b=10),
        paper_bgcolor="#09090b",
        plot_bgcolor="#0f0f12",
        font=dict(family="Inter, sans-serif", color="#a1a1aa", size=11),
        xaxis=dict(
            rangeslider=dict(visible=False),
            gridcolor="#1f1f23",
            showgrid=True,
        ),
        xaxis2=dict(gridcolor="#1f1f23"),
        yaxis=dict(
            gridcolor="#1f1f23",
            showgrid=True,
            tickformat=".2f",
        ),
        yaxis2=dict(gridcolor="#1f1f23", showgrid=True),
    )
    fig.update_xaxes(showspikes=True, spikecolor="#3f3f46", spikethickness=1)
    fig.update_yaxes(showspikes=True, spikecolor="#3f3f46", spikethickness=1)
    return fig


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  CSS DESIGN SYSTEM  (dark theme matching app.py)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

html, body, .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background-color: #09090b !important;
    color: #f4f4f5 !important;
}
.stApp { background-color: #09090b !important; }
.stMarkdown, p, span, label, h1, h2, h3, h4 { color: #f4f4f5 !important; }

/* â”€â”€ Header â”€â”€ */
.mgd-header {
    display: flex;
    align-items: center;
    gap: 12px;
    background: linear-gradient(135deg, #18181b 0%, #1a1a2e 100%);
    border: 1px solid #27272a;
    border-radius: 12px;
    padding: 16px 24px;
    margin-bottom: 16px;
}
.mgd-logo {
    font-size: 2rem;
    line-height: 1;
}
.mgd-title {
    font-size: 1.4rem;
    font-weight: 800;
    letter-spacing: -0.5px;
    color: #fff;
}
.mgd-sub {
    font-size: 0.75rem;
    color: #71717a;
    margin-top: 2px;
}
.mgd-badge {
    margin-left: auto;
    background: #1e3a5f;
    color: #60a5fa;
    border: 1px solid #1d4ed8;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 6px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.mgd-badge-manual {
    background: #3b1f5e;
    color: #c084fc;
    border-color: #7c3aed;
}

/* â”€â”€ Metric Cards â”€â”€ */
.metric-row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 8px;
    margin-bottom: 14px;
}
.metric-card {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 10px;
    padding: 12px 14px;
    transition: border-color 0.2s;
}
.metric-card:hover { border-color: #3f3f46; }
.metric-label {
    font-size: 0.68rem;
    font-weight: 600;
    color: #71717a;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-bottom: 4px;
}
.metric-val {
    font-size: 1.15rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: #f4f4f5;
}
.metric-val.green  { color: #22c55e; }
.metric-val.red    { color: #ef4444; }
.metric-val.yellow { color: #facc15; }
.metric-val.purple { color: #c084fc; }

/* â”€â”€ Config Panel â”€â”€ */
.config-panel {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 12px;
}
.config-title {
    font-size: 0.82rem;
    font-weight: 700;
    color: #a1a1aa;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid #27272a;
}

/* â”€â”€ Action Buttons â”€â”€ */
.stButton > button {
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    transition: all 0.15s ease !important;
    border: none !important;
    width: 100% !important;
    padding: 10px 0 !important;
}
.stButton > button:hover {
    transform: translateY(-1px) !important;
    filter: brightness(1.1) !important;
}

/* â”€â”€ Tables â”€â”€ */
.data-table {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 12px;
}
.table-header {
    background: #27272a;
    padding: 10px 16px;
    font-size: 0.75rem;
    font-weight: 700;
    color: #a1a1aa;
    text-transform: uppercase;
    letter-spacing: 0.6px;
}

/* â”€â”€ PnL Monitor Bar â”€â”€ */
.pnl-bar {
    background: #18181b;
    border: 1px solid #27272a;
    border-radius: 10px;
    padding: 12px 18px;
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 12px;
}
.pnl-live {
    font-size: 1.5rem;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
}
.pnl-green { color: #22c55e; }
.pnl-red   { color: #ef4444; }
.pnl-zero  { color: #71717a; }

/* â”€â”€ Monitor Alert â”€â”€ */
.monitor-alert {
    background: #1c1c1e;
    border: 1px solid #3f3f46;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 0.82rem;
    color: #a1a1aa;
    margin-bottom: 12px;
    font-family: 'JetBrains Mono', monospace;
}
.monitor-active   { border-color: #22c55e; color: #22c55e; }
.monitor-inactive { border-color: #52525b; color: #71717a; }
.monitor-trigger  { border-color: #ef4444; color: #fca5a5; background: #1a0a0a; }

/* â”€â”€ Status Dots â”€â”€ */
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot-green  { background: #22c55e; box-shadow: 0 0 6px #22c55e80; }
.dot-red    { background: #ef4444; box-shadow: 0 0 6px #ef444480; }
.dot-yellow { background: #facc15; box-shadow: 0 0 6px #facc1580; }
.dot-gray   { background: #52525b; }

/* â”€â”€ Divider â”€â”€ */
.divider {
    border: none;
    border-top: 1px solid #27272a;
    margin: 14px 0;
}

/* â”€â”€ Deployed Grid Levels â”€â”€ */
.grid-level-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 14px;
    font-size: 0.80rem;
    font-family: 'JetBrains Mono', monospace;
    border-bottom: 1px solid #1f1f23;
}
.grid-level-buy  { color: #22c55e; }
.grid-level-sell { color: #ef4444; }

/* Streamlit overrides */
div[data-testid="stVerticalBlock"] > div { gap: 0px !important; }
.stDataFrame { border-radius: 10px; overflow: hidden; }
div[data-testid="stNumberInput"] input { background: #27272a !important; border: 1px solid #3f3f46 !important; color: #f4f4f5 !important; border-radius: 6px !important; }
div[data-testid="stSlider"] > div { color: #a1a1aa; }
section[data-testid="stSidebar"] { background: #111113 !important; border-right: 1px solid #27272a !important; }
</style>
"""

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  STREAMLIT PAGE CONFIG
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

st.set_page_config(
    page_title="Manual Grid Desk â€” Profity AI",
    page_icon="ðŸŽ›ï¸",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(CSS, unsafe_allow_html=True)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  SESSION STATE INIT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

if "mgd_state" not in st.session_state:
    st.session_state.mgd_state = load_state()

if "mgd_action_msg" not in st.session_state:
    st.session_state.mgd_action_msg = ""

if "mgd_preview_levels" not in st.session_state:
    st.session_state.mgd_preview_levels = {"buy_stops": [], "sell_stops": []}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  LOAD RESOURCES
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

state  = st.session_state.mgd_state
brk    = get_manual_broker()
monitor = get_pnl_monitor()

# â”€â”€ Live Data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
current_price = get_mt5_live_price(brk)
df_candles    = get_historical_klines(SYMBOL, interval=CHART_INTERVAL, limit=CHART_CANDLES)
floating_pnl  = get_total_floating_pnl(brk)
open_pos      = get_live_positions(brk)
pending_ord   = get_live_pending(brk)
acc           = get_account_summary(brk)
cfg           = state["grid_config"]

# Update monitor's target/SL from current config
monitor["target_profit"] = cfg["target_profit"]
monitor["stop_loss"]     = cfg["stop_loss"]

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” HEADER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

connected   = brk.ensure_connected()
conn_label  = "CONNECTED" if connected else "OFFLINE"
conn_color  = "#22c55e" if connected else "#ef4444"
conn_bg     = "#0f2b1a" if connected else "#2b0f0f"
conn_border = "#166534" if connected else "#991b1b"

# Resolve displayed login/server â€” live from Bot #1 bridge, no hardcoded fallback
display_login  = acc.get("login")  or "â€”"
display_server = acc.get("server") or "â€”"
display_equity = acc.get("equity", 0.0)
display_curr   = acc.get("currency", "USD")
equity_str     = f"${display_equity:,.2f} {display_curr}" if display_equity else f"â€” {display_curr}"

st.markdown(f"""
<div class="mgd-header">
    <div class="mgd-logo">ðŸŽ›ï¸</div>
    <div style="flex:1">
        <div class="mgd-title">Manual Grid Desk</div>
        <div class="mgd-sub" style="display:flex;gap:14px;align-items:center;margin-top:4px;">
            <span style="font-family:'JetBrains Mono',monospace;color:#a1a1aa;font-size:0.78rem;">
                ðŸ§¾ #{display_login}
            </span>
            <span style="color:#3f3f46">|</span>
            <span style="color:#71717a;font-size:0.78rem;">{display_server}</span>
            <span style="color:#3f3f46">|</span>
            <span style="color:#71717a;font-size:0.78rem;">Equity: <span style="color:#f4f4f5;font-weight:600;font-family:'JetBrains Mono',monospace;">{equity_str}</span></span>
            <span style="color:#3f3f46">|</span>
            <span style="color:#71717a;font-size:0.78rem;">Magic: <span style="color:#c084fc;font-weight:600;">#{MANUAL_MAGIC}</span></span>
        </div>
    </div>
    <div class="mgd-badge mgd-badge-manual">MANUAL MODE</div>
    <div style="
        background:{conn_bg};
        color:{conn_color};
        border:1px solid {conn_border};
        font-size:0.72rem;
        font-weight:700;
        padding:6px 14px;
        border-radius:8px;
        letter-spacing:0.8px;
        font-family:'JetBrains Mono',monospace;
        display:flex;
        align-items:center;
        gap:6px;
    ">
        <span style="width:8px;height:8px;border-radius:50%;background:{conn_color};display:inline-block;box-shadow:0 0 8px {conn_color}80;"></span>
        {conn_label}
    </div>
</div>
""", unsafe_allow_html=True)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” METRIC STRIP
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

pnl_cls  = "green" if floating_pnl > 0 else ("red" if floating_pnl < 0 else "metric-val")
pnl_sign = "+" if floating_pnl >= 0 else ""

st.markdown(f"""
<div class="metric-row">
    <div class="metric-card">
        <div class="metric-label">XAUUSD Live</div>
        <div class="metric-val yellow">${current_price:,.2f}</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Floating P&L</div>
        <div class="metric-val {pnl_cls}">{pnl_sign}${floating_pnl:.2f}</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Open Positions</div>
        <div class="metric-val">{len(open_pos)}</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Pending Orders</div>
        <div class="metric-val purple">{len(pending_ord)}</div>
    </div>
    <div class="metric-card">
        <div class="metric-label">Balance / Equity</div>
        <div class="metric-val">${acc['balance']:,.0f} / ${acc['equity']:,.0f}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” P&L MONITOR STATUS BAR
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

mon_cls  = "monitor-active" if monitor["active"] else "monitor-inactive"
if monitor.get("last_msg") and monitor["triggered"]:
    mon_cls = "monitor-trigger"
mon_msg = monitor.get("last_msg") or (
    f"ðŸŸ¢ Auto-Flatten ACTIVE Â· Target: +${cfg['target_profit']:.2f} Â· SL: -${cfg['stop_loss']:.2f}"
    if monitor["active"]
    else f"âš« Auto-Flatten INACTIVE Â· Enable by clicking Deploy Grid"
)
st.markdown(f'<div class="monitor-alert {mon_cls}">{mon_msg}</div>', unsafe_allow_html=True)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” ACTION MESSAGE BANNER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

if st.session_state.mgd_action_msg:
    msg = st.session_state.mgd_action_msg
    if "âœ…" in msg:
        st.success(msg)
    elif "âš ï¸" in msg or "âŒ" in msg:
        st.warning(msg)
    else:
        st.info(msg)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” MAIN LAYOUT (Chart | Config + Actions)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

chart_col, config_col = st.columns([3, 1.2], gap="medium")

with chart_col:
    # Merge saved grid levels with preview
    grid_display = state.get("grid_levels") or st.session_state.mgd_preview_levels
    chart = build_chart(df_candles, grid_display, cfg.get("center_price", 0.0), current_price)
    st.plotly_chart(chart, width='stretch', config={"displayModeBar": False})

with config_col:
    st.markdown('<div class="config-title">âš™ï¸ Grid Configuration</div>', unsafe_allow_html=True)

    # â”€â”€ Config Inputs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # ── Center Price Mode & Display ───────────────────────────
    center_mode_opts = ["Live Price (Auto-Centered)", "Manual Custom Price"]
    saved_cmode = cfg.get("center_mode", "Live Price (Auto-Centered)")
    cmode_idx = 0 if saved_cmode == "Live Price (Auto-Centered)" else 1

    col_cm1, col_cm2 = st.columns([1.1, 1.3])
    with col_cm1:
        center_mode = st.radio("Center Anchor", center_mode_opts, index=cmode_idx, horizontal=False, key="mgd_center_mode")

    with col_cm2:
        if center_mode == "Live Price (Auto-Centered)":
            center_price_input = round(float(current_price), 2)
            st.markdown(
                f'''<div style="background:#13231b;border:1px solid #166534;border-radius:8px;padding:10px 12px;margin-top:2px;">
                    <div style="color:#4ade80;font-size:0.68rem;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;">● Live MT5 Anchor</div>
                    <div style="color:#22c55e;font-family:'JetBrains Mono',monospace;font-weight:800;font-size:1.15rem;">${center_price_input:,.2f}</div>
                    <div style="color:#86efac;font-size:0.68rem;margin-top:2px;">Auto-aligned to live broker tick</div>
                </div>''',
                unsafe_allow_html=True
            )
        else:
            default_manual = float(cfg.get("center_price") or current_price)
            center_price_input = st.number_input(
                "Manual Center ($)",
                value=round(default_manual, 2),
                step=0.50,
                format="%.2f",
                help="Fixed center price to anchor grid",
                key="mgd_custom_center"
            )

    col_a, col_b = st.columns(2)
    with col_a:
        levels_above = st.number_input("Levels (BUY)", value=int(cfg.get("levels_above", 3)), min_value=1, max_value=20, step=1, key="mgd_labs")
    with col_b:
        levels_below = st.number_input("Levels (SELL)", value=int(cfg.get("levels_below", 3)), min_value=1, max_value=20, step=1, key="mgd_lbel")

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="config-title">📏 Spacing: Offset & Gap</div>', unsafe_allow_html=True)

    # ── Offset from Live Price to 1st Trap ───────────────────
    col_om, col_ov = st.columns([1, 1.2])
    with col_om:
        offset_mode = st.radio("Offset Unit", ["USD ($)", "Percentage (%)"], index=0 if "USD" in cfg.get("offset_mode", "USD") else 1, key="mgd_offset_mode")
    with col_ov:
        if offset_mode == "USD ($)":
            saved_off = float(cfg.get("offset_value", 1.50))
            offset_val = st.number_input("1st Level Offset ($)", value=saved_off, min_value=0.10, max_value=100.0, step=0.25, format="%.2f", help="Buffer from live center to 1st trap", key="mgd_offset_val")
            pct_off = (offset_val / max(1.0, current_price)) * 100.0
            st.caption(f"≈ {pct_off:.3f}% from live")
        else:
            saved_off_pct = float(cfg.get("offset_pct", 0.05))
            offset_val = st.number_input("1st Level Offset (%)", value=saved_off_pct, min_value=0.01, max_value=5.0, step=0.01, format="%.3f", help="Percentage buffer to 1st trap", key="mgd_offset_val")
            usd_off = current_price * (offset_val / 100.0)
            st.caption(f"≈ ${usd_off:.2f} buffer")

    # ── Grid Gap between Consecutive Traps ───────────────────
    col_gm, col_gv = st.columns([1, 1.2])
    with col_gm:
        gap_mode = st.radio("Gap Unit", ["USD ($)", "Percentage (%)"], index=0 if "USD" in cfg.get("gap_mode", "USD") else 1, key="mgd_gap_mode")
    with col_gv:
        if gap_mode == "USD ($)":
            saved_gap_usd = float(cfg.get("gap_value", 2.0))
            gap_val = st.number_input("Grid Gap ($)", value=saved_gap_usd, min_value=0.10, max_value=100.0, step=0.50, format="%.2f", help="Dollar spacing between consecutive levels", key="mgd_gap_val")
            pct_equiv = (gap_val / max(1.0, current_price)) * 100.0
            st.caption(f"≈ {pct_equiv:.3f}% between levels")
        else:
            saved_gap_pct = float(cfg.get("gap_pct", 0.07))
            gap_val = st.number_input("Grid Gap (%)", value=saved_gap_pct, min_value=0.01, max_value=5.0, step=0.01, format="%.3f", help="Percentage spacing between consecutive levels", key="mgd_gap_val")
            usd_equiv = current_price * (gap_val / 100.0)
            st.caption(f"≈ ${usd_equiv:.2f} per level")

    col_c, col_d = st.columns(2)
    with col_c:
        lot_size = st.number_input("Base Lot", value=float(cfg.get("lot_size", 0.01)), min_value=0.01, max_value=100.0, step=0.01, format="%.2f", help="Starting lot size for level 1", key="mgd_lot")
    with col_d:
        lot_mult = st.number_input("Lot Multiplier", value=float(cfg.get("lot_mult", 1.0)), min_value=1.0, max_value=5.0, step=0.1, format="%.2f", help="1.0 = equal lots; > 1.0 increases size per level", key="mgd_lmult")

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="config-title">🎯 Risk Controls</div>', unsafe_allow_html=True)

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        target_profit = st.number_input(
            "Target Profit ($)",
            value=float(cfg.get("target_profit", 5.0)),
            min_value=0.10,
            max_value=10000.0,
            step=0.50,
            format="%.2f",
            help="Auto-flatten all when total floating P&L reaches this profit.",
            key="mgd_tp",
        )
    with col_r2:
        stop_loss = st.number_input(
            "Stop Loss ($)",
            value=float(cfg.get("stop_loss", 25.0)),
            min_value=0.10,
            max_value=100000.0,
            step=1.0,
            format="%.2f",
            help="Auto-flatten all when total floating loss hits this amount.",
            key="mgd_sl",
        )

    # Persist config changes
    cfg.update({
        "center_mode":   center_mode,
        "center_price":  center_price_input,
        "levels_above":  int(levels_above),
        "levels_below":  int(levels_below),
        "offset_mode":   offset_mode,
        "offset_value":  offset_val if offset_mode == "USD ($)" else float(cfg.get("offset_value", 1.50)),
        "offset_pct":    offset_val if offset_mode == "Percentage (%)" else float(cfg.get("offset_pct", 0.05)),
        "gap_mode":      gap_mode,
        "gap_value":     gap_val if gap_mode == "USD ($)" else float(cfg.get("gap_value", 2.0)),
        "gap_pct":       gap_val if gap_mode == "Percentage (%)" else float(cfg.get("gap_pct", 0.07)),
        "lot_size":      lot_size,
        "lot_mult":      lot_mult,
        "target_profit": target_profit,
        "stop_loss":     stop_loss,
    })
    state["grid_config"] = cfg

    # ── Preview levels for chart ──────────────────────────────────────────────
    preview = compute_grid_levels(
        center_price_input,
        gap_val,
        int(levels_above),
        int(levels_below),
        gap_mode=gap_mode,
        offset_val=offset_val,
        offset_mode=offset_mode,
    )
    st.session_state.mgd_preview_levels = preview
    step_amt = preview.get("step", gap_val)
    off_amt = preview.get("offset", offset_val)

    # ── Level Preview List with Lot Sizes ──────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown(f'<div class="config-title">📋 Preview (Offset: ${off_amt:.2f} · Gap: ${step_amt:.2f})</div>', unsafe_allow_html=True)

    level_html = ""
    # Buy levels: index 0 is closest to center
    for i, p in reversed(list(enumerate(preview["buy_stops"]))):
        dist = abs(p - center_price_input)
        calc_lot = round(lot_size * (lot_mult ** i), 2)
        level_tag = f"L{i+1}"
        level_html += f'<div class="grid-level-row grid-level-buy">▲ BUY {level_tag} ${p:,.2f} <span style="color:#60a5fa;font-size:0.72rem">({calc_lot:.2f}L)</span> <span style="color:#52525b;font-size:0.72rem">+{dist:.2f}</span></div>'
    
    center_label = "Live MT5 Market" if center_mode == "Live Price (Auto-Centered)" else "Manual Center"
    level_html += f'<div class="grid-level-row" style="background:#1a1a2e;color:#a78bfa">◆ CENTER ${center_price_input:,.2f} ({center_label})</div>'
    
    # Sell levels: index 0 is closest to center
    for i, p in enumerate(preview["sell_stops"]):
        dist = abs(p - center_price_input)
        calc_lot = round(lot_size * (lot_mult ** i), 2)
        level_tag = f"L{i+1}"
        level_html += f'<div class="grid-level-row grid-level-sell">▼ SELL {level_tag} ${p:,.2f} <span style="color:#f87171;font-size:0.72rem">({calc_lot:.2f}L)</span> <span style="color:#52525b;font-size:0.72rem">-{dist:.2f}</span></div>'
    st.markdown(f'<div class="data-table">{level_html}</div>', unsafe_allow_html=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    # ── ACTION BUTTONS ────────────────────────────────────────────────────────
    if st.button("🚀  DEPLOY GRID", type="primary", key="btn_deploy", width='stretch'):
        if not connected:
            st.session_state.mgd_action_msg = "❌ MT5 not connected. Cannot deploy."
        else:
            # Re-fetch real-time tick right at deployment instant to guarantee exact centering
            if center_mode == "Live Price (Auto-Centered)":
                center_to_deploy = get_mt5_live_price(brk)
            else:
                center_to_deploy = center_price_input

            levels = compute_grid_levels(
                center_to_deploy,
                gap_val,
                int(levels_above),
                int(levels_below),
                gap_mode=gap_mode,
                offset_val=offset_val,
                offset_mode=offset_mode,
            )
            placed, errors = deploy_grid(brk, levels, lot_size, lot_mult)
            if errors:
                st.session_state.mgd_action_msg = f"⚠️ Placed {placed} orders. Errors: {'; '.join(errors[:3])}"
            else:
                step_disp = f"${levels['step']:.2f}" if gap_mode == "USD ($)" else f"{gap_val:.3f}%"
                off_disp = f"${levels['offset']:.2f}" if offset_mode == "USD ($)" else f"{offset_val:.3f}%"
                st.session_state.mgd_action_msg = f"✅ Grid deployed! {placed} orders placed centered at ${center_to_deploy:,.2f} (Offset: {off_disp}, Gap: {step_disp}, Magic #{MANUAL_MAGIC})"
            state["deployed"]     = True
            state["grid_levels"]  = levels
            state["grid_config"]["center_price"] = center_to_deploy
            monitor["active"]     = True
            monitor["triggered"]  = False
            save_state(state)
        st.rerun()

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("🟢 CLOSE BUY", key="btn_cbuys", width='stretch'):
            if not connected:
                st.session_state.mgd_action_msg = "❌ MT5 not connected."
            else:
                res = brk.close_buy_positions(symbol=SYMBOL)
                st.session_state.mgd_action_msg = f"✅ Closed {len(res)} BUY position(s)."
            st.rerun()

    with col_b2:
        if st.button("🔴 CLOSE SELL", key="btn_csell", width='stretch'):
            if not connected:
                st.session_state.mgd_action_msg = "❌ MT5 not connected."
            else:
                res = brk.close_sell_positions(symbol=SYMBOL)
                st.session_state.mgd_action_msg = f"✅ Closed {len(res)} SELL position(s)."
            st.rerun()

    if st.button("🗑️  CANCEL PENDING", key="btn_cancel", width='stretch'):
        msg = cancel_all_pending(brk)
        state["deployed"] = False
        state["grid_levels"] = []
        monitor["active"] = False
        save_state(state)
        st.session_state.mgd_action_msg = msg
        st.rerun()

    if st.button("🚨  FLATTEN ALL", type="secondary", key="btn_flatten", width='stretch'):
        msg = flatten_all(brk, state)
        monitor["active"] = False
        st.session_state.mgd_action_msg = msg
        st.rerun()

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    if st.button("🔄  Refresh", key="btn_refresh", width='stretch'):
        save_state(state)
        st.session_state.mgd_action_msg = ""
        st.rerun()

    # Lock Center = Live Price
    if st.button("📍 Lock Center = Live Price", key="btn_live_center", width='stretch'):
        fresh_p = get_mt5_live_price(brk)
        cfg["center_mode"] = "Live Price (Auto-Centered)"
        cfg["center_price"] = fresh_p
        state["grid_config"] = cfg
        save_state(state)
        st.session_state.mgd_action_msg = f"✅ Center locked to live price ${fresh_p:,.2f}"
        st.rerun()

# Save any config changes to disk
save_state(state)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” OPEN POSITIONS TABLE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

st.markdown("---")
pos_col, pend_col = st.columns([1, 1], gap="medium")

with pos_col:
    st.markdown('<div class="table-header">ðŸ“‚ Open Positions (Magic #777001)</div>', unsafe_allow_html=True)
    if open_pos:
        rows = []
        for p in open_pos:
            side    = "BUY" if getattr(p, "type", 0) == 0 else "SELL"
            profit  = float(getattr(p, "profit", 0.0))
            rows.append({
                "Ticket":     getattr(p, "ticket", "â€”"),
                "Side":       side,
                "Lots":       f"{getattr(p, 'volume', 0.0):.2f}",
                "Entry":      f"{getattr(p, 'price_open', 0.0):.2f}",
                "Current":    f"{getattr(p, 'price_current', current_price):.2f}",
                "P&L ($)":    f"{profit:+.2f}",
            })
        df_pos = pd.DataFrame(rows)
        st.dataframe(
            df_pos,
            width='stretch',
            hide_index=True,
            column_config={
                "P&L ($)": st.column_config.TextColumn("P&L ($)"),
            },
        )
    else:
        st.markdown(
            '<div style="padding:16px;text-align:center;color:#52525b;font-size:0.82rem;">No open positions for Magic #777001</div>',
            unsafe_allow_html=True,
        )

with pend_col:
    st.markdown('<div class="table-header">â³ Pending Orders (Magic #777001)</div>', unsafe_allow_html=True)
    if pending_ord:
        ORDER_TYPE_MAP = {2: "BUY_LIMIT", 3: "SELL_LIMIT", 4: "BUY_STOP", 5: "SELL_STOP"}
        rows = []
        for o in pending_ord:
            o_type   = ORDER_TYPE_MAP.get(getattr(o, "type", -1), str(getattr(o, "type", "?")))
            o_price  = float(getattr(o, "price_open", 0.0))
            distance = o_price - current_price
            rows.append({
                "Ticket":    getattr(o, "ticket", "â€”"),
                "Type":      o_type,
                "Price":     f"{o_price:.2f}",
                "Lots":      f"{getattr(o, 'volume_initial', 0.0):.2f}",
                "Distance":  f"{distance:+.2f}",
            })
        df_pend = pd.DataFrame(rows)
        st.dataframe(df_pend, width='stretch', hide_index=True)
    else:
        st.markdown(
            '<div style="padding:16px;text-align:center;color:#52525b;font-size:0.82rem;">No pending orders for Magic #777001</div>',
            unsafe_allow_html=True,
        )

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  UI â€” TRADE HISTORY
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

st.markdown("---")
st.markdown('<div class="table-header">ðŸ“‹ Trade History</div>', unsafe_allow_html=True)

hist = state.get("trade_history", [])
# Also pull from broker's closed_trades
broker_history = list(getattr(brk, "closed_trades", []))
if broker_history:
    # Convert broker records to display format
    for rec in broker_history[-MAX_HISTORY_ROWS:]:
        ts_str = datetime.datetime.fromtimestamp(
            float(rec.get("exit_time", time.time()))
        ).strftime("%Y-%m-%d %H:%M:%S")
        hist_rec = {
            "time":      ts_str,
            "action":    rec.get("type", "CLOSE"),
            "entry":     f"{float(rec.get('entry_price', 0.0)):.2f}",
            "exit":      f"{float(rec.get('exit_price', 0.0)):.2f}",
            "lots":      f"{float(rec.get('size', 0.0)):.2f}",
            "total_pnl": round(float(rec.get("pnl", 0.0)), 2),
        }
        if not any(h.get("time") == ts_str and h.get("total_pnl") == hist_rec["total_pnl"] for h in hist):
            hist.insert(0, hist_rec)

hist = hist[:MAX_HISTORY_ROWS]
state["trade_history"] = hist

if hist:
    df_hist = pd.DataFrame(hist)
    st.dataframe(df_hist, width='stretch', hide_index=True, height=250)
else:
    st.markdown(
        '<div style="padding:20px;text-align:center;color:#52525b;font-size:0.82rem;">No trade history yet. Deploy a grid and let it run!</div>',
        unsafe_allow_html=True,
    )

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  AUTO-REFRESH
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

st.markdown(
    f'<div style="text-align:right;font-size:0.68rem;color:#3f3f46;padding-top:8px;">'
    f'Last updated: {datetime.datetime.now().strftime("%H:%M:%S")} Â· Auto-refresh every {REFRESH_SECS:.0f}s</div>',
    unsafe_allow_html=True,
)

time.sleep(REFRESH_SECS)
st.rerun()

