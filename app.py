from typing import Optional
import streamlit as st
# Trigger hot reload 2
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
from datetime import datetime
import textwrap
import pickle
import os

# Global process-level shared state to prevent duplicate loop execution in multiple tabs.
# NOTE: This dict lives in the Python process memory. A server restart clears it,
# allowing a second tab to briefly claim the lock — acceptable since a restart = clean slate.
if "GLOBAL_RUNNERS" not in globals():
    global GLOBAL_RUNNERS
    GLOBAL_RUNNERS: dict = {}

# Import core bot logic
from core.mt5_broker import MT5Broker, SimulatedBroker, MT5_AVAILABLE, get_symbol_magic_number, TradeDisabledError
from core.engine import BreakoutGridBot
from core.data import get_live_price, get_historical_klines, interpolate_ticks

# 1. PAGE CONFIGURATION
st.set_page_config(
    page_title="Maty ◆ Breakout Grid Bot",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 2. THEME STATE INITIALIZATION
if "theme" not in st.session_state:
    st.session_state.theme = "dark"

def toggle_theme():
    st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"

IS_DARK = st.session_state.theme == "dark"

# 3. PREMIUM ZINC DESIGN SYSTEM CSS
# Dynamic variables based on theme
if IS_DARK:
    vars_css = """
    :root {
        --bg: #09090b;
        --bg-subtle: #0c0c0f;
        --card: #0c0c0f;
        --card-hover: #131316;
        --border: #1e1e24;
        --border-subtle: #16161a;
        --text: #fafafa;
        --text-muted: #71717a;
        --text-dim: #52525b;
        --accent: #3b82f6;
        --accent-muted: #1d4ed8;
        --green: #22c55e;
        --green-muted: rgba(34, 197, 94, 0.12);
        --red: #ef4444;
        --red-muted: rgba(239, 68, 68, 0.12);
        --amber: #f59e0b;
        --amber-muted: rgba(245, 158, 11, 0.12);
        --shadow: none;
        --radius: 10px;
    }
    """
else:
    vars_css = """
    :root {
        --bg: #ffffff;
        --bg-subtle: #f9fafb;
        --card: #ffffff;
        --card-hover: #f4f4f5;
        --border: #e4e4e7;
        --border-subtle: #f0f0f2;
        --text: #09090b;
        --text-muted: #71717a;
        --text-dim: #a1a1aa;
        --accent: #2563eb;
        --accent-muted: #1d4ed8;
        --green: #16a34a;
        --green-muted: rgba(22, 163, 74, 0.08);
        --red: #dc2626;
        --red-muted: rgba(220, 38, 38, 0.08);
        --amber: #d97706;
        --amber-muted: rgba(217, 119, 6, 0.08);
        --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03);
        --radius: 10px;
    }
    """

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
{vars_css}

/* Hide default streamlit headers/footers */
header[data-testid="stHeader"], footer, [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"], .stDeployButton,
div[data-testid="stSidebarCollapsedControl"] {{
    display: none !important;
}}

/* Global resets & typography */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], .main, .block-container, section[data-testid="stMain"] {{
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'DM Sans', -apple-system, sans-serif !important;
}}

.block-container {{
    padding: 1.5rem 2rem 2rem !important;
    max-width: 1400px !important;
}}

/* Grid layout gap */
[data-testid="stHorizontalBlock"] {{
    gap: 1.25rem !important;
}}

/* Cards styling */
.metric-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.1rem 1.25rem;
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 90px;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}}
.metric-card:hover {{
    border-color: rgba(59,130,246,0.35);
    box-shadow: 0 4px 20px rgba(59,130,246,0.08);
}}
.metric-label {{
    font-size: 0.76rem;
    color: var(--text-muted);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}}
.metric-value {{
    font-size: 1.6rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.02em;
    margin-top: 0.2rem;
    font-family: 'JetBrains Mono', monospace;
}}
.metric-delta {{
    font-size: 0.72rem;
    font-weight: 500;
    margin-top: 0.35rem;
    padding: 2px 7px;
    border-radius: 5px;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    width: fit-content;
}}
.delta-up {{ color: var(--green); background: var(--green-muted); }}
.delta-down {{ color: var(--red); background: var(--red-muted); }}
.delta-warn {{ color: var(--amber); background: var(--amber-muted); }}

/* Chart Card Wrap */
.chart-wrap {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.2rem;
    box-shadow: var(--shadow);
    margin-bottom: 1rem;
}}
.chart-title {{
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text);
}}
.chart-subtitle {{
    font-size: 0.74rem;
    color: var(--text-dim);
    margin-bottom: 0.8rem;
}}

/* Form Control Cards — gradient top accent */
.control-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-top: 2px solid var(--accent);
    border-radius: var(--radius);
    padding: 1.2rem;
    box-shadow: var(--shadow);
    margin-bottom: 1rem;
    transition: box-shadow 0.2s ease;
}}
.control-card:hover {{
    box-shadow: 0 4px 24px rgba(59,130,246,0.07);
}}
.control-title {{
    font-size: 0.85rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border-subtle);
    text-transform: uppercase;
    letter-spacing: 0.07em;
    display: flex;
    align-items: center;
    gap: 6px;
}}

/* Data Table custom design */
.table-wrap {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem;
    box-shadow: var(--shadow);
    overflow-x: auto;
    margin-bottom: 1rem;
}}
.data-table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.78rem;
}}
.data-table th {{
    text-align: left;
    padding: 0.6rem 0.8rem;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
}}
.data-table td {{
    padding: 0.6rem 0.8rem;
    color: var(--text);
    border-bottom: 1px solid var(--border-subtle);
    font-family: 'JetBrains Mono', monospace;
}}
.data-table tr:last-child td {{
    border-bottom: none;
}}
.data-table tbody tr:hover td {{
    background: rgba(59,130,246,0.03);
}}
.data-table tfoot td {{
    border-top: 2px solid var(--border);
    border-bottom: none !important;
    font-weight: 700;
    background: var(--bg-subtle);
    color: var(--text-muted);
    font-family: 'DM Sans', sans-serif;
    font-size: 0.74rem;
}}

/* Badge styles */
.badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 0.7rem;
    font-weight: 600;
}}
.badge-green {{ color: var(--green); background: var(--green-muted); }}
.badge-red {{ color: var(--red); background: var(--red-muted); }}
.badge-amber {{ color: var(--amber); background: var(--amber-muted); }}
.badge-blue {{ color: var(--accent); background: rgba(59, 130, 246, 0.1); }}

/* Empty state placeholder */
.empty-state {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
    border: 1px dashed var(--border);
    background: var(--bg-subtle);
    border-radius: var(--radius);
    text-align: center;
    color: var(--text-muted);
    font-size: 0.76rem;
    margin-top: 0.5rem;
}}
.empty-state-icon {{
    font-size: 1.4rem;
    margin-bottom: 0.3rem;
    color: var(--text-dim);
    opacity: 0.75;
}}

/* Top Brand Row */
.brand-container {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
}}
.brand-logo {{
    font-weight: 800;
    font-size: 1.35rem;
    letter-spacing: -0.04em;
    color: var(--text);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}}
.brand-logo span {{ color: var(--accent); }}
.brand-meta {{
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.72rem;
    color: var(--text-muted);
}}
.brand-badge {{
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.03em;
}}

/* Pulse animation for RUNNING status dot */
@keyframes pulse-dot {{
    0%   {{ box-shadow: 0 0 0 0 rgba(34,197,94,0.65); }}
    70%  {{ box-shadow: 0 0 0 7px rgba(34,197,94,0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(34,197,94,0); }}
}}
.pulse-dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse-dot 1.8s infinite;
    flex-shrink: 0;
    vertical-align: middle;
}}
.idle-dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-dim);
    flex-shrink: 0;
    vertical-align: middle;
}}

/* KPI mega strip bar */
.kpi-bar {{
    display: flex;
    gap: 0;
    background: var(--card);
    border: 1px solid var(--border);
    border-top: 2px solid rgba(59,130,246,0.4);
    border-radius: var(--radius);
    margin-bottom: 1rem;
    overflow: hidden;
}}
.kpi-item {{
    flex: 1;
    padding: 0.75rem 1rem;
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    gap: 3px;
    transition: background 0.15s ease;
}}
.kpi-item:last-child {{ border-right: none; }}
.kpi-item:hover {{ background: var(--card-hover); }}
.kpi-lbl {{
    font-size: 0.67rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    font-weight: 600;
}}
.kpi-val {{
    font-size: 1.05rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.01em;
    color: var(--text);
}}
.kpi-sub {{
    font-size: 0.66rem;
    color: var(--text-dim);
}}

/* Active params glassmorphism banner */
.params-banner {{
    background: linear-gradient(135deg, rgba(59,130,246,0.06) 0%, rgba(245,158,11,0.04) 100%);
    border: 1px solid rgba(59,130,246,0.18);
    border-radius: var(--radius);
    padding: 10px 14px;
    margin: 6px 0 12px 0;
    display: flex;
    flex-direction: column;
    gap: 7px;
}}
.params-banner-header {{
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 0.77rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: 0.01em;
}}
.params-banner-pills {{
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
}}
.param-pill {{
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 0.7rem;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
    transition: border-color 0.15s;
}}
.param-pill:hover {{ border-color: rgba(59,130,246,0.4); }}
.param-pill-label {{
    color: var(--text-muted);
    font-size: 0.63rem;
    font-family: 'DM Sans', sans-serif;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.param-pill-value {{
    color: var(--text);
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
}}
.params-banner-note {{
    font-size: 0.67rem;
    color: var(--text-dim);
    padding-top: 2px;
    border-top: 1px solid var(--border-subtle);
}}

/* Glassmorphism & Hover Animations */
.metric-card, .chart-wrap, .control-card, .table-wrap, .kpi-bar, .params-banner {{
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}}

.metric-card:hover, .control-card:hover, .table-wrap:hover {{
    border-color: rgba(59, 130, 246, 0.4) !important;
    box-shadow: 0 8px 30px rgba(59, 130, 246, 0.12) !important;
    transform: translateY(-1px);
}}

/* Custom Streamlit Button Styling Overrides */
div.stButton > button {{
    border-radius: var(--radius) !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.02em !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    padding: 0.55rem 1rem !important;
    border: 1px solid var(--border) !important;
    background: var(--card) !important;
    color: var(--text) !important;
}}

div.stButton > button:hover {{
    border-color: var(--accent) !important;
    box-shadow: 0 4px 16px rgba(59, 130, 246, 0.2) !important;
    color: var(--text) !important;
    transform: translateY(-1px);
}}

/* Primary Button Styling Override */
div.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
    border: 1px solid #10b981 !important;
    color: #ffffff !important;
    box-shadow: 0 4px 14px rgba(16, 185, 129, 0.25) !important;
}}

div.stButton > button[kind="primary"]:hover {{
    box-shadow: 0 6px 20px rgba(16, 185, 129, 0.4) !important;
    transform: translateY(-1px);
}}

/* Pill styled tabs overriding */
button[data-baseweb="tab"] {{
    background: transparent !important;
    color: var(--text-muted) !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 0.5rem 1.1rem !important;
    border: 1px solid transparent !important;
    border-radius: 7px !important;
    transition: all 0.2s ease !important;
}}
button[data-baseweb="tab"]:hover {{ color: var(--text) !important; }}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: var(--text) !important;
    background: var(--card) !important;
    border-color: var(--border) !important;
    box-shadow: var(--shadow) !important;
}}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {{ display: none !important; }}
[data-baseweb="tab-list"] {{
    gap: 4px !important;
    background: var(--bg-subtle) !important;
    border: 1px solid var(--border) !important;
    border-radius: 9px !important;
    padding: 4px !important;
    margin-bottom: 1rem !important;
}}
</style>
""", unsafe_allow_html=True)

# 4. CUSTOM COMPONENTS UTILS
def metric_card(label: str, value: str, delta: str = None, delta_type: str = "up"):
    delta_class = f"delta-{delta_type}"
    arrow = "↑" if delta_type == "up" else ("↓" if delta_type == "down" else "•")
    delta_html = f'<div class="metric-delta {delta_class}">{arrow} {delta}</div>' if delta else ""
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)

def render_badge(text: str, type: str = "blue") -> str:
    return f'<span class="badge badge-{type}">{text}</span>'

# Plotly theme settings
PLOT_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="DM Sans, sans-serif", color="#71717a" if not IS_DARK else "#a1a1aa", size=11),
    margin=dict(l=40, r=40, t=15, b=25),
    xaxis=dict(
        gridcolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.05)",
        zerolinecolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.05)",
        tickfont=dict(size=10, color="#71717a"),
        showgrid=True,
    ),
    yaxis=dict(
        gridcolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.05)",
        zerolinecolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.05)",
        tickfont=dict(size=10, color="#71717a"),
        showgrid=True,
        side="right"
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(size=10)
    )
)

# --- STATE PERSISTENCE HELPERS ---
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.pkl")
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

DEFAULT_PRICES = {
    "BTCUSDT": 65000.0,
    "ETHUSDT": 2500.0,
    "SOLUSDT": 175.0,
    "BNBUSDT": 600.0,
    "DOGEUSDT": 0.14,
    "PAXGUSDT": 2400.0
}

def get_default_price(symbol: str) -> float:
    return DEFAULT_PRICES.get(symbol.upper(), 100.0)

def fmt_size(val: float) -> str:
    if val is None:
        return "0"
    if val >= 100:
        return f"{val:,.2f}".rstrip('0').rstrip('.')
    elif val >= 1:
        return f"{val:,.4f}".rstrip('0').rstrip('.')
    else:
        return f"{val:.6f}".rstrip('0').rstrip('.')

def get_current_live_price(symbol: str = None) -> Optional[float]:
    if symbol is None:
        symbol = st.session_state.live_symbol
    # Check if MT5 is active and connected
    broker = None # type: ignore
    if "markets" in st.session_state and symbol in st.session_state.markets:
        broker = st.session_state.markets[symbol]["broker"]
    elif "broker" in st.session_state:
        broker = st.session_state.broker
        
    if broker and broker.__class__.__name__ == "MT5Broker":
        if broker.ensure_connected():
            import MetaTrader5 as mt5_ref
            exness_symbol = broker.get_exness_symbol(symbol)
            tick = mt5_ref.symbol_info_tick(exness_symbol)  # symbol_select already done in get_exness_symbol
            if tick is not None and getattr(tick, "bid", 0) > 0 and getattr(tick, "ask", 0) > 0:
                # Center around the mid price to keep the buy/sell stops perfectly balanced
                return (float(tick.bid) + float(tick.ask)) / 2.0
    return get_live_price(symbol)

_sym_short = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "BNBUSDT": "BNB",
    "DOGEUSDT": "DOGE",
    "PAXGUSDT": "XAU"
}

_coin_label_map = {
    "BTCUSDT": "BTC/USD",
    "ETHUSDT": "ETH/USD",
    "SOLUSDT": "SOL/USD",
    "BNBUSDT": "BNB/USD",
    "DOGEUSDT": "DOGE/USD",
    "PAXGUSDT": "XAU/USD",
}

GOLDEN_SETTINGS = {
    "BTCUSDT": {"gap": 0.22, "offset": 0.33, "multiplier": 1.5, "order_size": 0.01, "target_profit": 10.0, "stop_loss": 250.0},
    "ETHUSDT": {"gap": 0.22, "offset": 0.33, "multiplier": 1.5, "order_size": 0.10, "target_profit": 10.0, "stop_loss": 250.0},
    "SOLUSDT": {"gap": 0.08, "offset": 0.12, "multiplier": 1.5, "order_size": 1.50, "target_profit": 10.0, "stop_loss": 150.0},
    "BNBUSDT": {"gap": 0.12, "offset": 0.18, "multiplier": 1.5, "order_size": 0.08, "target_profit": 10.0, "stop_loss": 150.0},
    "DOGEUSDT": {"gap": 0.08, "offset": 0.12, "multiplier": 1.5, "order_size": 1500.0, "target_profit": 10.0, "stop_loss": 150.0},
    "PAXGUSDT": {"gap": 0.10, "offset": 0.15, "multiplier": 1.5, "order_size": 0.01, "target_profit": 10.0, "stop_loss": 250.0},
}

def get_coin_golden_settings(symbol: str) -> dict:
    return GOLDEN_SETTINGS.get(symbol.upper(), {"gap": 0.22, "offset": 0.33, "multiplier": 1.5, "order_size": 0.01, "target_profit": 10.0, "stop_loss": 250.0})

def get_default_order_size(symbol: str) -> float:
    return get_coin_golden_settings(symbol)["order_size"]

def sync_active_market_primitives():
    if "markets" in st.session_state and "live_symbol" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
        active = st.session_state.markets[st.session_state.live_symbol]
        active["running"] = st.session_state.running
        active["last_price"] = st.session_state.last_price
        active["price_history"] = st.session_state.price_history
        active["strat_offset"] = st.session_state.strat_offset
        active["strat_gap"] = st.session_state.strat_gap
        active["strat_is_percent"] = st.session_state.strat_is_percent
        active["strat_order_size"] = st.session_state.strat_order_size
        active["strat_size_multiplier"] = st.session_state.strat_size_multiplier
        active["strat_target_profit"] = st.session_state.strat_target_profit
        active["strat_sl"] = st.session_state.strat_sl
        active["strat_trailing"] = st.session_state.strat_trailing
        active["strat_trailing_dist"] = st.session_state.strat_trailing_dist
        active["strat_breakeven"] = st.session_state.get("strat_breakeven", False)
        active["strat_breakeven_trigger"] = st.session_state.get("strat_breakeven_trigger", 0.5)
        active["strat_smart_trailing"] = st.session_state.get("strat_smart_trailing", True)
        active["strat_profit_lock_pct"] = st.session_state.get("strat_profit_lock_pct", 0.80)
        # Per-market price source (Live API vs Simulated)
        _ps_key = f"price_source_select_{st.session_state.live_symbol}"
        active["price_source"] = st.session_state.get(_ps_key, active.get("price_source", "Live Market API"))

def serialize_market_state(m_state):
    broker = m_state["broker"]
    bot = m_state["bot"]
    
    # Serialize open positions
    ser_positions = {}
    for pos_id, pos in broker.open_positions.items():
        ser_positions[pos_id] = {
            "position_id": pos.position_id,
            "type": pos.type,
            "entry_price": pos.entry_price,
            "size": pos.size,
            "entry_time": pos.entry_time
        }
        
    # Serialize pending orders
    ser_orders = {}
    for order_id, o in broker.pending_orders.items():
        ser_orders[order_id] = {
            "order_id": o.order_id,
            "type": o.type,
            "trigger_price": o.trigger_price,
            "size": o.size,
            "timestamp": o.timestamp
        }
        
    serialized = {
        "last_price": m_state.get("last_price"),
        "price_history": [],  # not persisted — rebuilt from live API on startup
        "running": m_state.get("running", False),
        "price_source": m_state.get("price_source", "Live Market API"),
        "strat_offset": m_state.get("strat_offset"),
        "strat_gap": m_state.get("strat_gap"),
        "strat_is_percent": m_state.get("strat_is_percent"),
        "strat_order_size": m_state.get("strat_order_size"),
        "strat_size_multiplier": m_state.get("strat_size_multiplier"),
        "strat_target_profit": m_state.get("strat_target_profit"),
        "strat_sl": m_state.get("strat_sl"),
        "strat_trailing": m_state.get("strat_trailing"),
        "strat_trailing_dist": m_state.get("strat_trailing_dist"),
        "strat_breakeven": m_state.get("strat_breakeven", False),
        "strat_breakeven_trigger": m_state.get("strat_breakeven_trigger", 0.5),
        "strat_smart_trailing": m_state.get("strat_smart_trailing", True),
        "strat_profit_lock_pct": m_state.get("strat_profit_lock_pct", 0.80),
        
        # Broker details
        "broker_class": broker.__class__.__name__,
        "broker_balance": broker._balance if isinstance(broker, SimulatedBroker) else 0.0,
        "broker_realized_pnl": broker.realized_pnl,
        "broker_closed_trades": broker.closed_trades,
        "broker_open_positions": ser_positions,
        "broker_pending_orders": ser_orders,
        "broker_login": getattr(broker, "login", 0),
        "broker_server": getattr(broker, "server", ""),
        "broker_suffix": getattr(broker, "symbol_suffix", ""),
        
        # Bot details
        "bot_deployed": bot.deployed,
        "bot_deploy_price": bot.deploy_price,
        "bot_current_cycle_id": bot.current_cycle_id,
        "bot_cycle_start_time": bot.cycle_start_time,
        "bot_cycle_history": bot.cycle_history,
        "bot_max_floating_pnl": getattr(bot, "max_floating_pnl", -float("inf")),
        "bot_breakeven_activated": getattr(bot, "breakeven_activated", False),
        "bot_in_runner_mode": getattr(bot, "in_runner_mode", False)
    }
    return serialized

def deserialize_market_state(ser, symbol):
    from core.mt5_broker import MT5Broker, SimulatedBroker, MT5_AVAILABLE
    from core.engine import BreakoutGridBot, Position, Order
    
    # Recreate Broker based on the saved broker class
    broker_class = ser.get("broker_class", "SimulatedBroker")
    if broker_class == "SimulatedBroker":
        broker = SimulatedBroker(
            symbol=symbol,
            initial_balance=ser.get("broker_balance", 10000.0)
        )
    else:
        # MT5Broker: only attempt if MT5 is available on this machine
        if not MT5_AVAILABLE:
            # MT5 not installed — fall back to SimulatedBroker so the app stays usable
            print(f"[{symbol}] MT5 not available; restoring as SimulatedBroker instead of MT5Broker.")
            broker_class = "SimulatedBroker"
            broker = SimulatedBroker(symbol=symbol, initial_balance=10000.0)
        else:
            try:
                broker = MT5Broker(
                    login=ser.get("broker_login", 0),
                    password=st.session_state.get("mt5_pwd", ""),
                    server=ser.get("broker_server", ""),
                    symbol=symbol,
                    symbol_suffix=ser.get("broker_suffix", ""),
                    magic_number=get_symbol_magic_number(symbol)
                )
            except Exception as mt5_err:
                print(f"[{symbol}] MT5 connection failed during deserialization ({mt5_err}); falling back to SimulatedBroker.")
                broker_class = "SimulatedBroker"
                broker = SimulatedBroker(symbol=symbol, initial_balance=ser.get("broker_balance", 10000.0))
        
    broker.realized_pnl = ser.get("broker_realized_pnl", 0.0)
    broker.closed_trades = ser.get("broker_closed_trades", [])
    
    # Recreate broker open positions
    broker.open_positions = {}
    for pos_id, pos_dict in ser.get("broker_open_positions", {}).items():
        pos = Position(pos_dict["type"], pos_dict["entry_price"], pos_dict["size"], pos_dict["entry_time"])
        pos.position_id = pos_dict["position_id"]
        broker.open_positions[pos_id] = pos
        if broker_class != "SimulatedBroker":
            try:
                # Populate ticket mapping back (MT5Broker only)
                ticket_num = int(pos_id.replace("live_", ""))
                broker.ticket_to_position_id[ticket_num] = pos_id
            except:
                pass
                
    # Recreate broker pending orders
    broker.pending_orders = {}
    for order_id, o_dict in ser.get("broker_pending_orders", {}).items():
        o = Order(o_dict["type"], o_dict["trigger_price"], o_dict["size"], o_dict["timestamp"])
        o.order_id = o_dict["order_id"]
        broker.pending_orders[order_id] = o
        if broker_class != "SimulatedBroker":
            try:
                broker.ticket_to_order_id[int(order_id)] = order_id
            except:
                pass
                
    # Recreate Bot using safe fallbacks
    gs = get_coin_golden_settings(symbol)
    bot = BreakoutGridBot(
        broker,
        grid_levels=10,
        grid_gap=ser.get("strat_gap", gs["gap"]),
        trap_offset=ser.get("strat_offset", gs["offset"]),
        order_size=ser.get("strat_order_size", gs["order_size"]),
        order_size_multiplier=ser.get("strat_size_multiplier", gs["multiplier"]),
        target_profit=ser.get("strat_target_profit", gs["target_profit"]),
        auto_restart=True,
        is_percent=ser.get("strat_is_percent", True),
        stop_loss=ser.get("strat_sl", gs["stop_loss"]),
        max_cycle_duration=float('inf'),
        cancel_opposite_on_trigger=False,
        use_trailing_stop=ser.get("strat_trailing", False),
        trailing_stop_distance=ser.get("strat_trailing_dist", 1.5),
        use_breakeven=ser.get("strat_breakeven", False),
        breakeven_trigger=ser.get("strat_breakeven_trigger", 0.5),
        use_smart_trailing=ser.get("strat_smart_trailing", True),
        profit_lock_pct=ser.get("strat_profit_lock_pct", 0.80)
    )
    
    bot.deployed = ser.get("bot_deployed", False)
    bot.deploy_price = ser.get("bot_deploy_price", 0.0)
    bot.current_cycle_id = ser.get("bot_current_cycle_id", 1)
    bot.cycle_start_time = ser.get("bot_cycle_start_time", 0.0)
    bot.cycle_history = ser.get("bot_cycle_history", [])
    bot.max_floating_pnl = ser.get("bot_max_floating_pnl", -float("inf"))
    bot.breakeven_activated = ser.get("bot_breakeven_activated", False)
    bot.in_runner_mode = ser.get("bot_in_runner_mode", False)
    
    m_state = {
        "broker": broker,
        "bot": bot,
        "price_history": ser.get("price_history", []),
        "last_price": ser.get("last_price", get_default_price(symbol)),
        "running": ser.get("running", False),
        "price_source": ser.get("price_source", "Live Market API"),
        "strat_offset": ser.get("strat_offset", gs["offset"]),
        "strat_gap": ser.get("strat_gap", gs["gap"]),
        "strat_is_percent": ser.get("strat_is_percent", True),
        "strat_order_size": ser.get("strat_order_size", gs["order_size"]),
        "strat_size_multiplier": ser.get("strat_size_multiplier", gs["multiplier"]),
        "strat_target_profit": ser.get("strat_target_profit", gs["target_profit"]),
        "strat_sl": ser.get("strat_sl", gs["stop_loss"]),
        "strat_trailing": ser.get("strat_trailing", False),
        "strat_trailing_dist": ser.get("strat_trailing_dist", 1.5),
        "strat_breakeven": ser.get("strat_breakeven", False),
        "strat_breakeven_trigger": ser.get("strat_breakeven_trigger", 0.5),
        "strat_smart_trailing": ser.get("strat_smart_trailing", True),
        "strat_profit_lock_pct": ser.get("strat_profit_lock_pct", 0.80),
        "strat_use_adaptive_gap": ser.get("strat_use_adaptive_gap", False)
    }
    return m_state

def save_bot_state():
    try:
        if "markets" in st.session_state:
            sync_active_market_primitives()
            
            serialized_markets = {}
            for sym, m_state in st.session_state.markets.items():
                serialized_markets[sym] = serialize_market_state(m_state)
                
            state = {
                "markets": serialized_markets,
                "live_symbol": st.session_state.live_symbol,
                "mt5_pwd": st.session_state.get("mt5_pwd", "")
            }
            # Write to a temporary file first and rename atomically to prevent state file corruption on reload/crashes
            import tempfile
            temp_dir = os.path.dirname(STATE_FILE)
            with tempfile.NamedTemporaryFile("wb", dir=temp_dir, delete=False) as tf:
                pickle.dump(state, tf)
                temp_name = tf.name
            os.replace(temp_name, STATE_FILE)
    except Exception as e:
        print(f"Error saving bot state: {e}")

def load_bot_state() -> bool:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                state = pickle.load(f)
            
            if "markets" in state:
                st.session_state.live_symbol = state["live_symbol"]
                st.session_state.mt5_pwd = state.get("mt5_pwd", "")
                
                # Reconstruct markets dictionary
                st.session_state.markets = {}
                for sym, ser_m in state["markets"].items():
                    st.session_state.markets[sym] = deserialize_market_state(ser_m, sym)
                return True
        except Exception as e:
            print(f"Error loading bot state: {e}")
    return False

def clear_bot_state():
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except Exception as e:
            print(f"Error deleting state file: {e}")

# 5. INITIALIZE CORE ENGINES IN SESSION STATE
# Attempt to load state from disk only on the first run of this session
if "state_loaded" not in st.session_state:
    state_loaded = load_bot_state()
    st.session_state.state_loaded = True
else:
    state_loaded = True

# Re-initialize MT5 connection on script startup if active market is using MT5Broker
if "markets" in st.session_state:
    for sym, m_state in st.session_state.markets.items():
        brk = m_state.get("broker")
        if brk and brk.__class__.__name__ == "MT5Broker":
            try:
                import MetaTrader5 as mt5
                if not mt5.initialize():
                    st.session_state.mt5_startup_error = f"MT5 failed to initialize: {mt5.last_error()}"
                else:
                    authorized = mt5.login(login=brk.login, password=brk.password, server=brk.server)
                    if not authorized:
                        st.session_state.mt5_startup_error = f"MT5 login failed: {mt5.last_error()}"
                    else:
                        st.session_state.mt5_startup_error = None
            except Exception as e:
                st.session_state.mt5_startup_error = f"Failed to reconnect to MT5 on startup: {e}"

if "error_message" not in st.session_state:
    st.session_state.error_message = None

if not state_loaded:
    if "markets" not in st.session_state:
        st.session_state.markets = {}
    if "live_symbol" not in st.session_state:
        st.session_state.live_symbol = "BTCUSDT"

# Ensure the active symbol state exists in markets dict
if "markets" not in st.session_state:
    st.session_state.markets = {}

if st.session_state.live_symbol not in st.session_state.markets:
    # Initialize state for this specific symbol. If MT5 is globally connected for another symbol, use MT5Broker.
    mt5_template = None
    if "markets" in st.session_state:
        for sym, m_state in st.session_state.markets.items():
            brk = m_state.get("broker")
            if brk and brk.__class__.__name__ == "MT5Broker":
                mt5_template = brk
                break
                
    if mt5_template:
        broker = MT5Broker(
            login=mt5_template.login,
            password=mt5_template.password,
            server=mt5_template.server,
            symbol=st.session_state.live_symbol,
            symbol_suffix=mt5_template.symbol_suffix,
            magic_number=get_symbol_magic_number(st.session_state.live_symbol)
        )
    else:
        broker = SimulatedBroker(symbol=st.session_state.live_symbol)
    
    price_history = []
    price = None
    
    is_simulated = st.session_state.get("price_source_select", "Live Market API") == "Simulated Market (Demo)"
    
    try:
        df_hist = get_historical_klines(st.session_state.live_symbol, interval="1m", limit=30)
        if df_hist is not None and not df_hist.empty:
            df_ticks = interpolate_ticks(df_hist)
            ticks = list(zip(df_ticks["timestamp"], df_ticks["price"]))
            price_history = ticks
            price = ticks[-1][1]
    except Exception as e:
        print(f"Error pre-populating historical klines for {st.session_state.live_symbol}: {e}")
        
    if price is None:
        price = get_live_price(st.session_state.live_symbol)
        if price is None:
            price = get_default_price(st.session_state.live_symbol)
        price_history = [(time.time(), price)]
        
    gs = get_coin_golden_settings(st.session_state.live_symbol)
    bot = BreakoutGridBot(
        broker,
        grid_levels=10,
        grid_gap=gs["gap"],
        trap_offset=gs["offset"],
        order_size=gs["order_size"],
        order_size_multiplier=gs["multiplier"],
        target_profit=gs["target_profit"],
        auto_restart=True,
        is_percent=True,
        stop_loss=gs["stop_loss"],
        max_cycle_duration=float('inf'),
        cancel_opposite_on_trigger=True,
        use_breakeven=False,
        breakeven_trigger=0.5
    )
    
    # Only deploy traps initially if it is SimulatedBroker; live broker requires explicit bot start
    if isinstance(broker, SimulatedBroker):
        bot.deploy_traps(price, time.time())
    else:
        bot.deployed = False
    
    st.session_state.markets[st.session_state.live_symbol] = {
        "broker": broker,
        "bot": bot,
        "price_history": price_history,
        "last_price": price,
        "running": False,
        "price_source": "Live Market API",
        "strat_grid_levels": gs.get("grid_levels", 10),
        "strat_offset": gs["offset"],
        "strat_gap": gs["gap"],
        "strat_is_percent": True,
        "strat_order_size": gs["order_size"],
        "strat_size_multiplier": gs["multiplier"],
        "strat_target_profit": gs["target_profit"],
        "strat_sl": gs["stop_loss"],
        "strat_trailing": False,
        "strat_trailing_dist": 1.5,
        "strat_breakeven": False,
        "strat_breakeven_trigger": 0.5,
        "strat_smart_trailing": True,
        "strat_profit_lock_pct": 0.85,
        "strat_use_adaptive_gap": True
    }

# Sync references to current active market
active_market = st.session_state.markets[st.session_state.live_symbol]
st.session_state.broker = active_market["broker"]
st.session_state.bot = active_market["bot"]
st.session_state.price_history = active_market["price_history"]
st.session_state.last_price = active_market["last_price"]
st.session_state.running = active_market["running"]

try:
    for _m_sym, _m_data in st.session_state.markets.items():
        _brk = _m_data.get("broker")
        _bot = _m_data.get("bot")
        if _brk:
            _brk.sync()
            if _bot and hasattr(_bot, "sync_cycle_history_from_trades"):
                _bot.sync_cycle_history_from_trades()
except Exception as e:
    print(f"Failed to synchronize broker state: {e}")

# Initialize or sync current symbol to avoid resetting strategy parameter states on every rerun
if "current_symbol" not in st.session_state or st.session_state.current_symbol != st.session_state.live_symbol:
    st.session_state.current_symbol = st.session_state.live_symbol
    gs = get_coin_golden_settings(st.session_state.live_symbol)
    # Load each coin's saved settings from its market dict (no widget key clearing needed —
    # widget keys are now namespaced per-symbol so they are naturally isolated).
    st.session_state.strat_grid_levels = active_market.get("strat_grid_levels", gs.get("grid_levels", 10))
    st.session_state.strat_offset = active_market.get("strat_offset", gs["offset"])
    st.session_state.strat_gap = active_market.get("strat_gap", gs["gap"])
    st.session_state.strat_is_percent = active_market.get("strat_is_percent", True)
    st.session_state.strat_order_size = active_market.get("strat_order_size", gs["order_size"])
    st.session_state.strat_size_multiplier = active_market.get("strat_size_multiplier", gs["multiplier"])
    st.session_state.strat_target_profit = active_market.get("strat_target_profit", gs["target_profit"])
    st.session_state.strat_sl = active_market.get("strat_sl", gs["stop_loss"])
    st.session_state.strat_trailing = active_market.get("strat_trailing", False)
    st.session_state.strat_trailing_dist = active_market.get("strat_trailing_dist", 1.5)
    st.session_state.strat_breakeven = active_market.get("strat_breakeven", False)
    st.session_state.strat_breakeven_trigger = active_market.get("strat_breakeven_trigger", 0.5)
    st.session_state.strat_smart_trailing = active_market.get("strat_smart_trailing", True)
    st.session_state.strat_profit_lock_pct = active_market.get("strat_profit_lock_pct", 0.85)
    st.session_state.strat_use_adaptive_gap = active_market.get("strat_use_adaptive_gap", True)

# --- SYNC WIDGET INPUTS TO STATE VARIABLES ON RERUN BEFORE RENDERING ---
# Widget keys are namespaced per-symbol so each coin has fully independent Streamlit state.
_sym_key = st.session_state.live_symbol

_is_pct_key = f"strat_is_percent_select_{_sym_key}"
if _is_pct_key in st.session_state:
    st.session_state.strat_is_percent = (st.session_state[_is_pct_key] == "Percentage (%)")

if f"strat_size_multiplier_input_{_sym_key}" in st.session_state:
    st.session_state.strat_size_multiplier = st.session_state[f"strat_size_multiplier_input_{_sym_key}"]
if f"strat_order_size_input_{_sym_key}" in st.session_state:
    st.session_state.strat_order_size = st.session_state[f"strat_order_size_input_{_sym_key}"]
if f"strat_target_profit_input_{_sym_key}" in st.session_state:
    st.session_state.strat_target_profit = st.session_state[f"strat_target_profit_input_{_sym_key}"]
if f"strat_sl_input_{_sym_key}" in st.session_state:
    st.session_state.strat_sl = st.session_state[f"strat_sl_input_{_sym_key}"]
if f"strat_trailing_input_{_sym_key}" in st.session_state:
    st.session_state.strat_trailing = st.session_state[f"strat_trailing_input_{_sym_key}"]
if f"strat_trailing_dist_input_{_sym_key}" in st.session_state:
    st.session_state.strat_trailing_dist = st.session_state[f"strat_trailing_dist_input_{_sym_key}"]
if f"strat_breakeven_input_{_sym_key}" in st.session_state:
    st.session_state.strat_breakeven = st.session_state[f"strat_breakeven_input_{_sym_key}"]
if f"strat_breakeven_trigger_input_{_sym_key}" in st.session_state:
    st.session_state.strat_breakeven_trigger = st.session_state[f"strat_breakeven_trigger_input_{_sym_key}"] / 100.0
if f"strat_smart_trailing_input_{_sym_key}" in st.session_state:
    st.session_state.strat_smart_trailing = st.session_state[f"strat_smart_trailing_input_{_sym_key}"]
if f"strat_profit_lock_pct_input_{_sym_key}" in st.session_state:
    st.session_state.strat_profit_lock_pct = st.session_state[f"strat_profit_lock_pct_input_{_sym_key}"] / 100.0
if f"strat_use_adaptive_gap_input_{_sym_key}" in st.session_state:
    st.session_state.strat_use_adaptive_gap = st.session_state[f"strat_use_adaptive_gap_input_{_sym_key}"]

if st.session_state.get("strat_is_percent", True):
    if f"strat_gap_input_pct_{_sym_key}" in st.session_state:
        st.session_state.strat_gap = st.session_state[f"strat_gap_input_pct_{_sym_key}"]
    if f"strat_offset_input_pct_{_sym_key}" in st.session_state:
        st.session_state.strat_offset = st.session_state[f"strat_offset_input_pct_{_sym_key}"]
else:
    if f"strat_gap_input_usd_{_sym_key}" in st.session_state:
        st.session_state.strat_gap = st.session_state[f"strat_gap_input_usd_{_sym_key}"]
    if f"strat_offset_input_usd_{_sym_key}" in st.session_state:
        st.session_state.strat_offset = st.session_state[f"strat_offset_input_usd_{_sym_key}"]
# -----------------------------------------------------------------------

# Detect if parameters affecting grid layout or sizing have changed
bot = st.session_state.bot
broker = st.session_state.broker

# Only compare grid-placement settings and lot size settings — TP/SL/Trailing are locked mid-cycle
settings_changed = (
    bot.grid_gap != st.session_state.strat_gap or
    bot.trap_offset != st.session_state.strat_offset or
    bot.is_percent != st.session_state.strat_is_percent or
    bot.order_size != st.session_state.strat_order_size or
    bot.order_size_multiplier != st.session_state.strat_size_multiplier
)

# Apply settings to the bot instance
bot.grid_levels = 10
bot.grid_gap = st.session_state.strat_gap
bot.trap_offset = st.session_state.strat_offset
bot.auto_restart = True
bot.is_percent = st.session_state.strat_is_percent
bot.max_cycle_duration = float('inf')
bot.cancel_opposite_on_trigger = True
# Target Profit, Stop Loss, Trailing Stop, and Breakeven exit levels update dynamically even during active cycles
bot.target_profit = st.session_state.strat_target_profit
bot.stop_loss = st.session_state.strat_sl
bot.use_trailing_stop = st.session_state.strat_trailing
bot.trailing_stop_distance = st.session_state.strat_trailing_dist
bot.use_breakeven = st.session_state.strat_breakeven
bot.breakeven_trigger = st.session_state.strat_breakeven_trigger
bot.use_smart_trailing = st.session_state.get("strat_smart_trailing", True)
bot.profit_lock_pct = st.session_state.get("strat_profit_lock_pct", 0.80)
bot.use_adaptive_gap = st.session_state.get("strat_use_adaptive_gap", False)

# Lock lot size settings when positions are open — prevent mid-cycle trap volume mismatches
if len(broker.open_positions) == 0:
    bot.order_size = st.session_state.strat_order_size
    bot.order_size_multiplier = st.session_state.strat_size_multiplier
bot.use_bb_filter = False

# Always sync active market primitives dictionary after updating bot settings and persist to disk
sync_active_market_primitives()
save_bot_state()

# If settings that affect grid placement/sizing changed, redeploy traps immediately
# provided that no positions are currently open.
if settings_changed and bot.deployed and len(broker.open_positions) == 0:
    try:
        bot.deploy_traps(st.session_state.last_price, time.time())
        st.session_state.error_message = None
    except Exception as e:
        st.session_state.error_message = f"Grid deployment failed: {e}"

# Helper to reset real-time dashboard data
def reset_realtime_sandbox():
    clear_bot_state()
    # Stop bot and cancel orders BEFORE deleting state to prevent KeyError on next rerun
    st.session_state.running = False
    if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
        m = st.session_state.markets[st.session_state.live_symbol]
        try:
            m["broker"].cancel_all_orders()
        except Exception:
            pass
        m["running"] = False
        del st.session_state.markets[st.session_state.live_symbol]
    if "current_symbol" in st.session_state:
        del st.session_state.current_symbol

def init_mt5_broker(login, password, server, suffix):
    try:
        # Loop through all configured symbols and apply MT5Broker globally
        for sym in list(st.session_state.markets.keys()):
            broker = MT5Broker(
                login=login,
                password=password,
                server=server,
                symbol=sym,
                symbol_suffix=suffix,
                magic_number=get_symbol_magic_number(sym)
            )
            st.session_state.markets[sym]["broker"] = broker
            st.session_state.markets[sym]["bot"].broker = broker
            
        # Sync active references
        active_market = st.session_state.markets[st.session_state.live_symbol]
        st.session_state.broker = active_market["broker"]
        st.session_state.bot = active_market["bot"]
        
        # Pull current live price from MT5 if available
        import MetaTrader5 as mt5
        exness_symbol = st.session_state.broker.get_exness_symbol(st.session_state.live_symbol)
        mt5.symbol_select(exness_symbol, True)
        tick = mt5.symbol_info_tick(exness_symbol)
        if tick:
            current_price = tick.bid
            st.session_state.last_price = current_price
            st.session_state.markets[st.session_state.live_symbol]["last_price"] = current_price
            if st.session_state.price_history:
                st.session_state.price_history[-1] = (time.time(), current_price)
                
        # Avoid placing live orders on account link. Mark bot as not deployed so it places them when START BOT is clicked.
        st.session_state.bot.deployed = False
            
        st.session_state.mt5_startup_error = None
        save_bot_state()
        return True
    except Exception as e:
        st.session_state.mt5_startup_error = str(e)
        return False

def init_simulated_broker():
    # Loop through all configured symbols and apply SimulatedBroker globally
    for sym in list(st.session_state.markets.keys()):
        existing_broker = st.session_state.markets[sym].get("broker")
        # Preserve balance if switching back from MT5; otherwise default to $10,000
        saved_balance = getattr(existing_broker, "_balance", 10000.0) if isinstance(existing_broker, SimulatedBroker) else 10000.0
        broker = SimulatedBroker(symbol=sym, initial_balance=saved_balance)
        # Reset open positions / pending orders so the simulated sandbox starts clean
        broker.realized_pnl = 0.0
        st.session_state.markets[sym]["broker"] = broker
        st.session_state.markets[sym]["bot"].broker = broker
        
    # Sync active references
    active_market = st.session_state.markets[st.session_state.live_symbol]
    st.session_state.broker = active_market["broker"]
    st.session_state.bot = active_market["bot"]
    
    # Deploy simulated traps for ALL configured symbols at their current prices
    for sym in list(st.session_state.markets.keys()):
        sym_bot = st.session_state.markets[sym]["bot"]
        sym_price = st.session_state.markets[sym].get("last_price") or get_default_price(sym)
        try:
            sym_bot.deploy_traps(sym_price, time.time())
        except Exception as e:
            print(f"Failed to deploy traps for {sym} on sandbox init: {e}")
    st.session_state.mt5_startup_error = None
    save_bot_state()

# Initialize history if empty
if not st.session_state.price_history:
    reset_realtime_sandbox()

# 6. HEADER RENDERING
_now_str = datetime.now().strftime("%a %d %b %Y  %H:%M:%S")
_active_markets_count = sum(1 for m in st.session_state.markets.values() if m.get("running", False))
_broker_type_hdr = "Simulated Sandbox" if isinstance(st.session_state.broker, SimulatedBroker) else "MT5 Live"
_broker_color = "#3b82f6" if _broker_type_hdr == "Simulated Sandbox" else "#f59e0b"
_running_dot = '<span class="pulse-dot"></span>' if _active_markets_count > 0 else '<span class="idle-dot"></span>'
st.markdown(f"""
<div class="brand-container">
    <div class="brand-logo">
        ◆ MATY <span>BREAKOUT GRID BOT</span>
    </div>
    <div class="brand-meta">
        {_running_dot}
        <span style="font-weight:600;color:{'var(--green)' if _active_markets_count > 0 else 'var(--text-dim)'}">
            {_active_markets_count} RUNNING
        </span>
        &nbsp;·&nbsp;
        <span class="brand-badge" style="background:{_broker_color}18;color:{_broker_color};border:1px solid {_broker_color}33;">{_broker_type_hdr}</span>
        &nbsp;·&nbsp;
        <span style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;">{_now_str}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 7. EXECUTION CONTROLS & STRATEGY TUNING
col_controls, col_strategy = st.columns([5, 7])

with col_controls:
    st.markdown('<div class="control-title">🎮 Execution & Market Controls</div>', unsafe_allow_html=True)
    
    # --- SECTION A: MARKET SELECTORS (3 COLUMNS) ---
    sel_col1, sel_col2, sel_col3 = st.columns([4, 4, 4])
    
    with sel_col1:
        market_options = {
            "BTCUSDT (Bitcoin)": "BTCUSDT",
            "ETHUSDT (Ethereum)": "ETHUSDT",
            "SOLUSDT (Solana)": "SOLUSDT",
            "BNBUSDT (Binance Coin)": "BNBUSDT",
            "DOGEUSDT (Dogecoin)": "DOGEUSDT",
            "XAUUSD (Gold)": "PAXGUSDT"
        }
        
        current_sym = st.session_state.get("live_symbol", "BTCUSDT")
        default_idx = 0
        for i, (label, val) in enumerate(market_options.items()):
            if val == current_sym:
                default_idx = i
                break
                
        selected_label = st.selectbox(
            "Market / Symbol",
            list(market_options.keys()),
            index=default_idx,
            key="symbol_select_dropdown"
        )
        symbol = market_options[selected_label]
        
        if symbol != st.session_state.live_symbol:
            sync_active_market_primitives()
            st.session_state.live_symbol = symbol
            st.session_state.running = st.session_state.markets[symbol].get("running", False) if symbol in st.session_state.markets else False
            
            st.session_state.pop("current_symbol", None)
            
            default_p = get_default_price(symbol)
            new_price_history = []
            new_price = None
            
            try:
                df_hist = get_historical_klines(symbol, interval="1m", limit=30)
                if df_hist is not None and not df_hist.empty:
                    df_ticks = interpolate_ticks(df_hist)
                    new_price_history = list(zip(df_ticks["timestamp"], df_ticks["price"]))
                    new_price = new_price_history[-1][1]
            except Exception as e:
                print(f"Error fetching klines on symbol switch: {e}")
            
            if new_price is None:
                new_price = get_current_live_price(symbol)
                if new_price is None:
                    new_price = st.session_state.markets[symbol]["last_price"] if (symbol in st.session_state.markets and st.session_state.markets[symbol].get("last_price")) else default_p
                new_price_history = [(time.time(), new_price)]
            
            if symbol in st.session_state.markets:
                if not st.session_state.markets[symbol].get("running", False):
                    st.session_state.markets[symbol]["price_history"] = new_price_history
                    st.session_state.markets[symbol]["last_price"] = new_price
                
                st.session_state.broker = st.session_state.markets[symbol]["broker"]
                st.session_state.bot = st.session_state.markets[symbol]["bot"]
                st.session_state.price_history = st.session_state.markets[symbol]["price_history"]
                st.session_state.last_price = st.session_state.markets[symbol]["last_price"]

                curr_broker = st.session_state.markets[symbol]["broker"]
                curr_bot = st.session_state.markets[symbol]["bot"]
                curr_gs = get_coin_golden_settings(symbol)
                curr_bot.order_size = st.session_state.markets[symbol].get("strat_order_size", curr_gs["order_size"])
                curr_bot.order_size_multiplier = st.session_state.markets[symbol].get("strat_size_multiplier", curr_gs["multiplier"])
                curr_bot.grid_gap = st.session_state.markets[symbol].get("strat_gap", curr_gs["gap"])
                curr_bot.trap_offset = st.session_state.markets[symbol].get("strat_offset", curr_gs["offset"])
                curr_bot.is_percent = st.session_state.markets[symbol].get("strat_is_percent", True)
                if len(curr_broker.open_positions) == 0 and isinstance(curr_broker, SimulatedBroker) and not st.session_state.markets[symbol].get("running", False):
                    try:
                        curr_bot.deploy_traps(st.session_state.markets[symbol]["last_price"], time.time())
                        st.session_state.error_message = None
                    except Exception as e:
                        st.session_state.error_message = f"Failed to deploy traps for {symbol}: {e}"
            
            save_bot_state()
            st.rerun()

    with sel_col2:
        timeframe = st.selectbox(
            "Chart Timeframe",
            ["5 Seconds", "1 Minute"],
            key="timeframe_select"
        )

    with sel_col3:
        curr_ps = st.session_state.markets.get(st.session_state.live_symbol, {}).get("price_source", "Live Market API")
        price_source_idx = 0 if curr_ps == "Live Market API" else 1
        price_source = st.selectbox(
            "Price Source",
            ["Live Market API", "Simulated Market (Demo)"],
            index=price_source_idx,
            key=f"price_source_select_{st.session_state.live_symbol}"
        )
        if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
            st.session_state.markets[st.session_state.live_symbol]["price_source"] = price_source

    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    _active_label = _sym_short.get(st.session_state.live_symbol, st.session_state.live_symbol)

    # --- SECTION B: 6-BUTTON UNIFIED COMMAND GRID (2 ROWS x 3 COLUMNS) ---
    
    # ROW 1: PRIMARY BOT STATE & GRID MAINTENANCE ACTIONS
    cmd_r1_c1, cmd_r1_c2, cmd_r1_c3 = st.columns(3)
    
    with cmd_r1_c1:
        if not st.session_state.running:
            if st.button("▶ START BOT", type="primary", help="Start bot engine loop for active market", use_container_width=True):
                try:
                    st.session_state.broker.sync()
                except Exception as sync_err:
                    print(f"Failed to sync broker on startup: {sync_err}")
                    
                has_existing_grid = len(st.session_state.broker.open_positions) > 0 or len(st.session_state.broker.pending_orders) > 0
                
                if has_existing_grid:
                    curr_price = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
                    if not getattr(st.session_state.bot, "deploy_price", 0.0):
                        buy_stops = [o.trigger_price for o in st.session_state.broker.pending_orders.values() if o.type == "BUY_STOP"]
                        sell_stops = [o.trigger_price for o in st.session_state.broker.pending_orders.values() if o.type == "SELL_STOP"]
                        if buy_stops and sell_stops:
                            st.session_state.bot.deploy_price = (min(buy_stops) + max(sell_stops)) / 2.0
                        elif st.session_state.broker.open_positions:
                            st.session_state.bot.deploy_price = list(st.session_state.broker.open_positions.values())[0].entry_price
                        else:
                            st.session_state.bot.deploy_price = curr_price
                    
                    st.session_state.bot.deployed = True
                    st.session_state.running = True
                    if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
                        st.session_state.markets[st.session_state.live_symbol]["running"] = True
                else:
                    try:
                        curr_price = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
                        st.session_state.broker.close_all_positions(curr_price, time.time())
                        st.session_state.broker.cancel_all_orders()
                    except Exception as e:
                        print(f"Startup cleanup failed: {e}")
                    
                    st.session_state.bot.deployed = False
                    st.session_state.running = True
                    if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
                        st.session_state.markets[st.session_state.live_symbol]["running"] = True
                
                sync_active_market_primitives()
                save_bot_state()
                st.rerun()
        else:
            if st.button("⏸ PAUSE BOT", type="secondary", help="Pause bot engine tick loop", use_container_width=True):
                st.session_state.running = False
                if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
                    st.session_state.markets[st.session_state.live_symbol]["running"] = False
                sync_active_market_primitives()
                save_bot_state()
                st.rerun()

    with cmd_r1_c2:
        if st.button("🔧 REPAIR GRID", type="secondary", help=f"Clean duplicates & restore missing trap levels for {_active_label}", use_container_width=True):
            curr_m = st.session_state.markets.get(st.session_state.live_symbol)
            if curr_m:
                bt = curr_m["bot"]
                curr_p = (
                    (curr_m["price_history"][-1][1] if curr_m.get("price_history") else None)
                    or curr_m.get("last_price")
                    or get_default_price(st.session_state.live_symbol)
                )
                from core.engine import BreakoutGridBot
                if not hasattr(bt, "cleanup_grid"):
                    bt.cleanup_grid = BreakoutGridBot.cleanup_grid.__get__(bt, BreakoutGridBot)
                if not hasattr(bt, "repair_grid"):
                    bt.repair_grid = BreakoutGridBot.repair_grid.__get__(bt, BreakoutGridBot)
                cleaned_cnt = bt.cleanup_grid(curr_p)
                added_cnt = bt.repair_grid(curr_p, time.time())
                sync_active_market_primitives()
                save_bot_state()
                msg = f"🔧 {_active_label}: removed {cleaned_cnt} duplicate/orphan orders, added {added_cnt} missing levels."
                st.toast(msg)
                st.rerun()

    with cmd_r1_c3:
        if st.button("🧹 CLEAN UP", type="secondary", help=f"Remove duplicate & orphan pending orders for {_active_label}", use_container_width=True):
            curr_m = st.session_state.markets.get(st.session_state.live_symbol)
            if curr_m:
                bt = curr_m["bot"]
                curr_p = (
                    (curr_m["price_history"][-1][1] if curr_m.get("price_history") else None)
                    or curr_m.get("last_price")
                    or get_default_price(st.session_state.live_symbol)
                )
                from core.engine import BreakoutGridBot
                if not hasattr(bt, "cleanup_grid"):
                    bt.cleanup_grid = BreakoutGridBot.cleanup_grid.__get__(bt, BreakoutGridBot)
                cleaned_cnt = bt.cleanup_grid(curr_p)
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"🧹 {_active_label}: cleaned up {cleaned_cnt} duplicate/orphan orders.")
                st.rerun()

    # ROW 2: SAFETY, EMERGENCY CLOSE & ENVIRONMENT RESET ACTIONS
    cmd_r2_c1, cmd_r2_c2, cmd_r2_c3 = st.columns(3)

    with cmd_r2_c1:
        if st.button(f"🚨 CLOSE {_active_label}", type="secondary", help=f"Emergency close trades & traps for {_active_label} only", use_container_width=True):
            curr_m = st.session_state.markets.get(st.session_state.live_symbol)
            if curr_m:
                brk = curr_m["broker"]
                bt = curr_m["bot"]
                curr_p = (
                    (curr_m["price_history"][-1][1] if curr_m.get("price_history") else None)
                    or curr_m.get("last_price")
                    or get_default_price(st.session_state.live_symbol)
                )
                
                closed_cnt = 0
                try:
                    closed = brk.close_all_positions(curr_p, time.time())
                    brk.cancel_all_orders()
                    closed_cnt = len(closed)
                except Exception as e:
                    print(f"Close active pair failed for {st.session_state.live_symbol}: {e}")
                
                bt.deployed = False
                curr_m["running"] = False
                st.session_state.running = False
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"Emergency closed {closed_cnt} trades for {_active_label}.")
                st.rerun()

    with cmd_r2_c2:
        if st.button("⚡ PANIC ALL", type="secondary", help="Global emergency stop across all market pairs", use_container_width=True):
            total_closed_count = 0
            for sym, m_state in st.session_state.markets.items():
                brk = m_state["broker"]
                bt = m_state["bot"]
                
                curr_p = (
                    (m_state["price_history"][-1][1] if m_state.get("price_history") else None)
                    or m_state.get("last_price")
                    or get_default_price(sym)
                )
                    
                try:
                    closed = brk.close_all_positions(curr_p, time.time())
                    brk.cancel_all_orders()
                    total_closed_count += len(closed)
                except Exception as e:
                    print(f"Panic close failed for {sym}: {e}")
                    
                bt.deployed = False
                m_state["running"] = False
            
            st.session_state.running = False
            sync_active_market_primitives()
            save_bot_state()
            st.warning(f"Global panic close executed! Closed {total_closed_count} open trades across all pairs.")
            st.rerun()

    with cmd_r2_c3:
        if st.button("🔄 RESET", type="secondary", help="Reset simulated sandbox state", use_container_width=True):
            reset_realtime_sandbox()
            st.success("Environment reset complete.")
            st.rerun()

    # Exness MT5 connection UI
    broker_type = "Simulated Sandbox" if isinstance(st.session_state.broker, SimulatedBroker) else "Exness MT5 Live"
    status_color = "#3b82f6" if broker_type == "Simulated Sandbox" else "#f59e0b"
    
    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 8px; margin-top: 8px; margin-bottom: 8px; font-size: 0.8rem; font-weight: 500;">
        <span style="color: var(--text-muted);">Active Broker:</span>
        <span style="background: {status_color}22; color: {status_color}; border: 1px solid {status_color}44; padding: 2px 8px; border-radius: 12px; font-size: 0.72rem;">{broker_type}</span>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("🔌 EXNESS MT5 LIVE ACCOUNT LINK", expanded=(broker_type == "Exness MT5 Live")):
        import sys
        if sys.platform != "win32":
            st.info("ℹ️ **Exness MT5 Live Trading** is only supported when running this application locally on a Windows machine with the MetaTrader 5 desktop application open in the background.")
        elif not MT5_AVAILABLE:
            st.warning(
                "⚠️ **MT5 Live Trading is blocked by Windows Application Control policy** on this machine. "
                "The `MetaTrader5` package is installed, but its native DLL (`_core.pyd`) is unsigned and "
                "is being blocked by AppLocker/WDAC. To resolve this, ask your IT admin to whitelist the file, "
                "or run the app on a machine without Application Control restrictions. "
                "**Simulated Sandbox mode is fully functional in the meantime.**"
            )
        else:
            is_live = (broker_type == "Exness MT5 Live")
            current_login = st.session_state.broker.login if is_live else 0
            current_server = st.session_state.broker.server if is_live else "Exness-MT5-Trial"
            current_suffix = st.session_state.broker.symbol_suffix if is_live else "m"
            
            mt5_login = st.number_input("MT5 Login (Account ID)", min_value=0, value=current_login or 0, step=1, key="mt5_login_input")
            mt5_password = st.text_input("MT5 Password", type="password", value=st.session_state.get("mt5_pwd", ""), key="mt5_pwd_input")
            mt5_server = st.text_input("MT5 Server (e.g., Exness-MT5-Trial)", value=current_server, key="mt5_server_input")
            mt5_suffix = st.text_input("Exness Symbol Suffix (e.g., 'm' for Mini/Cent)", value=current_suffix, key="mt5_suffix_input")
            
            # If successfully connected to MT5, render a real-time account status panel
            if is_live and st.session_state.broker.ensure_connected():
                import MetaTrader5 as mt5_ref
                acc = mt5_ref.account_info()
                if acc:
                    st.markdown(f"""
                    <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.2); border-radius: 8px; padding: 12px; margin-bottom: 12px; font-size: 0.8rem;">
                        <div style="color: #f59e0b; font-weight: bold; margin-bottom: 8px; font-size: 0.85rem;">CONNECTED ACCOUNT INFO</div>
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; color: var(--text-color);">
                            <div><strong>Account Name:</strong> {acc.name}</div>
                            <div><strong>Account Login:</strong> {acc.login}</div>
                            <div><strong>Server:</strong> {acc.server}</div>
                            <div><strong>Company:</strong> {acc.company}</div>
                            <div><strong>Leverage:</strong> 1:{acc.leverage}</div>
                            <div><strong>Currency:</strong> {acc.currency}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            
            if st.session_state.get("mt5_startup_error"):
                st.error(st.session_state.mt5_startup_error)
            
            conn_col1, conn_col2 = st.columns(2)
            with conn_col1:
                if st.button("CONNECT MT5", type="primary", use_container_width=True):
                    if mt5_login == 0 or not mt5_password or not mt5_server:
                        st.error("Please fill in Login, Password, and Server fields.")
                    else:
                        st.session_state.mt5_pwd = mt5_password
                        success = init_mt5_broker(mt5_login, mt5_password, mt5_server, mt5_suffix)
                        if success:
                            st.rerun()
            with conn_col2:
                if is_live:
                    if st.button("DISCONNECT (GO SANDBOX)", type="secondary", use_container_width=True):
                        init_simulated_broker()
                        st.success("Disconnected from MT5. Switched back to Simulated Sandbox.")
                        st.rerun()

with col_strategy:
    _strat_sym_label = {"BTCUSDT":"BTC","ETHUSDT":"ETH","SOLUSDT":"SOL","BNBUSDT":"BNB","DOGEUSDT":"DOGE","PAXGUSDT":"XAU"}.get(st.session_state.live_symbol, st.session_state.live_symbol)
    
    st_header_col1, st_header_col2 = st.columns([2, 1])
    with st_header_col1:
        st.markdown(f'<div class="control-title">🎯 Strategy Tuning &nbsp;<span style="font-size:0.7rem;font-weight:400;opacity:0.55;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:1px 7px;">for {_strat_sym_label}</span></div>', unsafe_allow_html=True)
    with st_header_col2:
        if st.button(f"🎯 DEFAULTS ({_strat_sym_label})", type="secondary", help=f"Reset strategy parameters for {_strat_sym_label} to Golden Settings defaults", use_container_width=True):
            gs = get_coin_golden_settings(st.session_state.live_symbol)
            st.session_state.strat_offset = gs["offset"]
            st.session_state.strat_gap = gs["gap"]
            st.session_state.strat_is_percent = True
            st.session_state.strat_order_size = gs["order_size"]
            st.session_state.strat_size_multiplier = gs["multiplier"]
            st.session_state.strat_target_profit = gs["target_profit"]
            st.session_state.strat_sl = gs["stop_loss"]
            
            # Clear per-symbol namespaced widget keys so input boxes visually reset to golden defaults
            _sym_wk_reset = st.session_state.live_symbol
            _strat_widget_keys = [
                f"strat_is_percent_select_{_sym_wk_reset}",
                f"strat_offset_input_pct_{_sym_wk_reset}", f"strat_offset_input_usd_{_sym_wk_reset}",
                f"strat_gap_input_pct_{_sym_wk_reset}",    f"strat_gap_input_usd_{_sym_wk_reset}",
                f"strat_target_profit_input_{_sym_wk_reset}", f"strat_sl_input_{_sym_wk_reset}",
                f"strat_order_size_input_{_sym_wk_reset}", f"strat_size_multiplier_input_{_sym_wk_reset}",
                f"strat_trailing_input_{_sym_wk_reset}", f"strat_trailing_dist_input_{_sym_wk_reset}",
                f"strat_breakeven_input_{_sym_wk_reset}", f"strat_breakeven_trigger_input_{_sym_wk_reset}",
            ]
            for _k in _strat_widget_keys:
                st.session_state.pop(_k, None)
                
            sync_active_market_primitives()
            save_bot_state()
            st.toast(f"Reset strategy settings for {_strat_sym_label} to Golden Defaults.")
            st.rerun()

    _cur_gap = st.session_state.strat_gap
    _cur_off = st.session_state.strat_offset
    _cur_is_pct = st.session_state.get("strat_is_percent", True)
    gap_str = f"{_cur_gap:.2f}%" if _cur_is_pct else f"${_cur_gap:.1f}"
    offset_str = f"{_cur_off:.2f}%" if _cur_is_pct else f"${_cur_off:.1f}"
    _is_running_strat = st.session_state.running
    _run_dot_html = '<span class="pulse-dot"></span> <span style="color:var(--green);font-size:0.68rem;font-weight:700;">RUNNING</span>' if _is_running_strat else '<span class="idle-dot"></span> <span style="color:var(--text-dim);font-size:0.68rem;font-weight:700;">IDLE</span>'
    _pills = [
        ("GAP",    gap_str),
        ("OFFSET", offset_str),
        ("MULT",   f"{st.session_state.strat_size_multiplier:.1f}x"),
        ("SIZE",   fmt_size(st.session_state.strat_order_size)),
        ("TARGET", f"${st.session_state.strat_target_profit:.1f}"),
        ("STOP",   f"${st.session_state.strat_sl:.1f}"),
    ]
    _pills_html = "".join(
        f'<span class="param-pill"><span class="param-pill-label">{lbl}</span><span class="param-pill-value">{val}</span></span>'
        for lbl, val in _pills
    )
    st.markdown(
        f'<div class="params-banner">'
        f'<div class="params-banner-header">📌 Active Parameters &nbsp;&mdash;&nbsp; <strong>{_strat_sym_label}</strong>&nbsp;&nbsp;{_run_dot_html}</div>'
        f'<div class="params-banner-pills">{_pills_html}</div>'
        f'<div class="params-banner-note">💡 Changes apply immediately if no trades are open, or activate on the next cycle completion.</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    _sym_wk = st.session_state.live_symbol  # widget key namespace for this coin
    strat_col1, strat_col2, strat_col3 = st.columns(3)
    with strat_col1:
        # Spacing Mode selectbox
        spacing_mode = st.selectbox(
            "Spacing Mode",
            ["Percentage (%)", "USD Points / Pips"],
            index=0 if st.session_state.get("strat_is_percent", True) else 1,
            key=f"strat_is_percent_select_{_sym_wk}"
        )
        st.session_state.strat_is_percent = (spacing_mode == "Percentage (%)")
        
        # Determine labels, bounds, and step sizes based on spacing mode
        if st.session_state.strat_is_percent:
            offset_label = "Trap Offset (%)"
            offset_min, offset_max, offset_step = 0.01, 5.0, 0.01
            gap_label = "Grid Gap (%)"
            gap_min, gap_max, gap_step = 0.01, 5.0, 0.01
            default_offset = 0.15 if st.session_state.strat_offset > 5.0 else st.session_state.strat_offset
            default_gap = 0.10 if st.session_state.strat_gap > 5.0 else st.session_state.strat_gap
        else:
            offset_label = "Trap Offset (USD)"
            offset_min, offset_max, offset_step = 0.1, max(100000.0, float(st.session_state.last_price) * 2.0), 1.0
            gap_label = "Grid Gap (USD)"
            gap_min, gap_max, gap_step = 0.1, max(100000.0, float(st.session_state.last_price) * 2.0), 1.0
            if st.session_state.strat_offset < 5.0:
                default_offset = max(0.5, round(st.session_state.last_price * (st.session_state.strat_offset / 100.0), 2))
                default_gap = max(0.5, round(st.session_state.last_price * (st.session_state.strat_gap / 100.0), 2))
            else:
                default_offset = st.session_state.strat_offset
                default_gap = st.session_state.strat_gap

        trap_offset_val = st.number_input(
            offset_label,
            min_value=offset_min,
            max_value=offset_max,
            value=default_offset,
            step=offset_step,
            format="%.2f" if st.session_state.strat_is_percent or default_offset % 1 != 0 else "%.1f",
            key=f"strat_offset_input_{'pct' if st.session_state.strat_is_percent else 'usd'}_{_sym_wk}"
        )
        st.session_state.strat_offset = trap_offset_val
        
        grid_gap_val = st.number_input(
            gap_label,
            min_value=gap_min,
            max_value=gap_max,
            value=default_gap,
            step=gap_step,
            format="%.2f" if st.session_state.strat_is_percent or default_gap % 1 != 0 else "%.1f",
            key=f"strat_gap_input_{'pct' if st.session_state.strat_is_percent else 'usd'}_{_sym_wk}"
        )
        st.session_state.strat_gap = grid_gap_val

        grid_levels_val = st.number_input(
            "Grid Levels per Side",
            min_value=1,
            max_value=30,
            value=int(st.session_state.get("strat_grid_levels", 10)),
            step=1,
            help="Number of pending stop orders placed per side (e.g. 10 = 10 BUY_STOP + 10 SELL_STOP = 20 total orders; 20 = 20 BUY_STOP + 20 SELL_STOP = 40 total orders).",
            key=f"strat_grid_levels_input_{_sym_wk}"
        )
        st.session_state.strat_grid_levels = grid_levels_val
        if hasattr(st.session_state, "bot") and st.session_state.bot:
            st.session_state.bot.grid_levels = grid_levels_val
        
    with strat_col2:
        target_profit_val = st.number_input(
            "Target Profit (USD)",
            min_value=1.0,
            max_value=10000.0,
            value=float(st.session_state.strat_target_profit),
            step=1.0,
            key=f"strat_target_profit_input_{_sym_wk}"
        )
        st.session_state.strat_target_profit = target_profit_val

        sl_val = st.number_input(
            "Stop Loss (USD)",
            min_value=5.0,
            max_value=100000.0,
            value=float(st.session_state.get("strat_sl", 150.0)),
            step=10.0,
            key=f"strat_sl_input_{_sym_wk}"
        )
        st.session_state.strat_sl = sl_val

        smart_trailing_val = st.toggle(
            "Enable Smart Profit Expansion (Runner Mode)",
            value=st.session_state.get("strat_smart_trailing", True),
            key=f"strat_smart_trailing_input_{_sym_wk}"
        )
        st.session_state.strat_smart_trailing = smart_trailing_val

        profit_lock_val = st.slider(
            "Runner Profit Lock %",
            min_value=50,
            max_value=95,
            value=int(st.session_state.get("strat_profit_lock_pct", 0.80) * 100),
            step=5,
            disabled=not smart_trailing_val,
            key=f"strat_profit_lock_pct_input_{_sym_wk}"
        )
        st.session_state.strat_profit_lock_pct = profit_lock_val / 100.0

        trailing_stop_val = st.toggle(
            "Enable Standard Trailing Stop",
            value=st.session_state.strat_trailing,
            key=f"strat_trailing_input_{_sym_wk}"
        )
        st.session_state.strat_trailing = trailing_stop_val
        
        trailing_dist_val = st.number_input(
            "Trailing Distance (USD)",
            min_value=0.1,
            max_value=1000.0,
            value=float(st.session_state.strat_trailing_dist),
            step=0.5,
            disabled=not trailing_stop_val,
            key=f"strat_trailing_dist_input_{_sym_wk}"
        )
        st.session_state.strat_trailing_dist = trailing_dist_val

        breakeven_val = st.toggle(
            "Enable Breakeven Protection",
            value=st.session_state.get("strat_breakeven", False),
            key=f"strat_breakeven_input_{_sym_wk}"
        )
        st.session_state.strat_breakeven = breakeven_val

        be_trigger_pct = int(round(st.session_state.get("strat_breakeven_trigger", 0.5) * 100))
        breakeven_trigger_val = st.number_input(
            "Breakeven Trigger (% Target)",
            min_value=10,
            max_value=90,
            value=be_trigger_pct,
            step=5,
            disabled=not breakeven_val,
            key=f"strat_breakeven_trigger_input_{_sym_wk}"
        )
        st.session_state.strat_breakeven_trigger = breakeven_trigger_val / 100.0

        adaptive_gap_val = st.toggle(
            "Enable Volatility-Adaptive Gap (Auto Spacing)",
            value=st.session_state.get("strat_use_adaptive_gap", False),
            help="Dynamically shrinks grid gap during quiet markets for faster micro-fills, and widens gap up to 2.5x during volatile breakout spikes to protect capital.",
            key=f"strat_use_adaptive_gap_input_{_sym_wk}"
        )
        st.session_state.strat_use_adaptive_gap = adaptive_gap_val
        
    with strat_col3:
        order_size_val = st.number_input(
            "Base Order Size (Quantity)",
            min_value=0.00001,
            max_value=1000000.0,
            value=float(st.session_state.strat_order_size),
            step=0.0001 if st.session_state.strat_order_size < 0.1 else (0.01 if st.session_state.strat_order_size < 10.0 else 1.0),
            format="%.5f" if st.session_state.strat_order_size < 1.0 else ("%.2f" if st.session_state.strat_order_size < 100.0 else "%.1f"),
            key=f"strat_order_size_input_{_sym_wk}"
        )
        st.session_state.strat_order_size = order_size_val

        size_mult_val = st.number_input(
            "Size Multiplier (Martingale)",
            min_value=0.5,
            max_value=5.0,
            value=float(st.session_state.strat_size_multiplier),
            step=0.1,
            format="%.2f" if st.session_state.strat_size_multiplier % 0.1 != 0 else "%.1f",
            key=f"strat_size_multiplier_input_{_sym_wk}"
        )
        st.session_state.strat_size_multiplier = size_mult_val
        if hasattr(st.session_state, "bot") and st.session_state.bot:
            st.session_state.bot.order_size_multiplier = size_mult_val
            st.session_state.bot.order_size = st.session_state.strat_order_size
        
        cur_brk = st.session_state.get("broker")
        _vol_cache_key = f"mt5_vol_{st.session_state.live_symbol}"
        if _vol_cache_key not in st.session_state and cur_brk and cur_brk.__class__.__name__ == "MT5Broker":
            try:
                import MetaTrader5 as mt5_ref
                ex_s = cur_brk.get_exness_symbol(st.session_state.live_symbol)
                inf = mt5_ref.symbol_info(ex_s)
                if inf:
                    st.session_state[_vol_cache_key] = (inf.volume_min, inf.volume_step)
            except Exception:
                pass
        mt5_vol_min, mt5_vol_step = st.session_state.get(_vol_cache_key, (0.0, 0.0))

        def calc_level_sz(base_s, mult_s, idx):
            if hasattr(st.session_state.bot, "calculate_level_size"):
                sz = st.session_state.bot.calculate_level_size(base_s, mult_s, idx)
            else:
                sz = round(base_s * (mult_s ** idx), 8) if (mult_s > 1.0 and idx > 0) else round(base_s, 8)
            if mt5_vol_step > 0:
                sz = round(round((sz / mt5_vol_step) + 1e-9) * mt5_vol_step, 8)
            if mt5_vol_min > 0 and sz < mt5_vol_min:
                sz = mt5_vol_min
            return sz

        progression_10 = [fmt_size(calc_level_sz(st.session_state.strat_order_size, st.session_state.strat_size_multiplier, i)) for i in range(10)]
        st.caption(f"📐 10-Level Martingale Progression:  \nL1–L5: {' ➔ '.join(progression_10[:5])}  \nL6–L10: {' ➔ '.join(progression_10[5:])}")
        if mt5_vol_min > 0 and st.session_state.strat_order_size < mt5_vol_min:
            st.warning(f"⚠️ Note: Exness MT5 requires minimum **{fmt_size(mt5_vol_min)} lots** for {st.session_state.live_symbol}. Order sizes below this will be clamped to {fmt_size(mt5_vol_min)} by the broker.")

# ── Per-market status bar ─────────────────────────────────────────────────────
# Shows all configured markets at a glance: running state, open positions, P&L
_sym_short = {"BTCUSDT":"BTC","ETHUSDT":"ETH","SOLUSDT":"SOL",
              "BNBUSDT":"BNB","DOGEUSDT":"DOGE","PAXGUSDT":"XAU"}
_status_chips = []
for _s, _m in st.session_state.markets.items():
    _brk = _m.get("broker")
    _is_running = _m.get("running", False)
    _open_pos = len(_brk.open_positions) if _brk else 0
    _price_for_pnl = (
        (_m["price_history"][-1][1] if _m.get("price_history") else None)
        or _m.get("last_price")
        or get_default_price(_s)
    )
    _pnl = sum(p.get_pnl(_price_for_pnl) for p in _brk.open_positions.values()) if _brk and _open_pos > 0 else 0.0
    _realized = getattr(_brk, "realized_pnl", 0.0) if _brk else 0.0
    _is_active = (_s == st.session_state.live_symbol)
    _label = _sym_short.get(_s, _s)
    _dot = "🟢" if _is_running else ("🟡" if _open_pos > 0 else "⚫")
    _pnl_txt = f"+${_pnl:.2f}" if _pnl >= 0 else f"-${abs(_pnl):.2f}"
    _border = "2px solid #f59e0b" if _is_active else "1px solid rgba(255,255,255,0.08)"
    _bg = "rgba(245,158,11,0.08)" if _is_active else "rgba(255,255,255,0.03)"
    _status_chips.append(
        f'<div style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;'
        f'border-radius:8px;border:{_border};background:{_bg};margin:2px 4px 2px 0;'
        f'font-size:0.72rem;font-weight:500;white-space:nowrap;">'
        f'{_dot} <strong>{_label}</strong>'
        f'{" ▶ RUNNING" if _is_running else (" ⏸ PAUSED" if _open_pos > 0 else " IDLE")}'
        f' &nbsp;|&nbsp; {_open_pos} pos &nbsp;|&nbsp; '
        f'<span style="color:{"#22c55e" if _pnl >= 0 else "#ef4444"}">{_pnl_txt}</span>'
        f'</div>'
    )
st.markdown(
    f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:2px;'
    f'padding:6px 2px;margin-bottom:4px;">'
    f'<span style="font-size:0.68rem;color:var(--text-muted);margin-right:6px;font-weight:600;">'
    f'ALL MARKETS:</span>' + "".join(_status_chips) + "</div>",
    unsafe_allow_html=True
)

# Run calculation tick if any bot is running
any_running = any(m.get("running", False) for m in st.session_state.markets.values())

if any_running:
    # Multi-tab concurrency safety lock to prevent duplicate orders from multiple browser windows
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    session_id = ctx.session_id if ctx else "default"
    
    # Prune inactive sessions (no heartbeat for more than 3.0 seconds)
    now_t = time.time()
    dead_sessions = [sid for sid, t in list(GLOBAL_RUNNERS.items()) if now_t - t > 3.0]
    for sid in dead_sessions:
        GLOBAL_RUNNERS.pop(sid, None)
        
    # Check if another session is already active
    other_active = [sid for sid in GLOBAL_RUNNERS.keys() if sid != session_id]
    if other_active:
        # Pause all sessions/markets to protect the account
        for sym, m_state in st.session_state.markets.items():
            m_state["running"] = False
        st.session_state.running = False
        st.session_state.error_message = "⚠️ Bot execution paused in this tab because another browser window is already running the bot loop."
        save_bot_state()
        st.rerun()
        
    # Register this session's heartbeat
    GLOBAL_RUNNERS[session_id] = now_t

    # Process ticks for all running markets
    for sym, m_state in list(st.session_state.markets.items()):
        if not m_state.get("running", False):
            continue
            
        try:
            # 1. Fetch latest price
            price_source_sel = m_state.get("price_source", "Live Market API")
            if price_source_sel == "Simulated Market (Demo)":
                last_p = m_state["price_history"][-1][1] if m_state.get("price_history") else m_state.get("last_price")
                if last_p is None:
                    last_p = get_default_price(sym)
                vol = 0.0008 if sym == "PAXGUSDT" else 0.0005
                change = np.random.normal(0, vol)
                latest_price = round(last_p * (1 + change), 2)
            else:
                latest_price = get_current_live_price(sym)
                if latest_price is None:
                    latest_price = m_state["price_history"][-1][1] if m_state.get("price_history") else m_state.get("last_price")

            if latest_price is None:
                continue

            # Record price tick
            now = time.time()
            previous_price = m_state["price_history"][-1][1] if m_state.get("price_history") else latest_price
            
            if "price_history" not in m_state:
                m_state["price_history"] = []
            m_state["price_history"].append((now, latest_price))
            m_state["last_price"] = latest_price
            
            # Keep history to last 3000 points for charting performance (slicing is O(1) vs pop(0) O(n))
            if len(m_state["price_history"]) > 3000:
                m_state["price_history"] = m_state["price_history"][-3000:]
                
            # Update references if this is the active symbol
            if sym == st.session_state.live_symbol:
                st.session_state.last_price = latest_price
                st.session_state.price_history = m_state["price_history"]
                
            # 2. Update engine
            bot = m_state["bot"]
            bb_w = None
            if getattr(bot, "use_adaptive_gap", False) and len(m_state.get("price_history", [])) >= 20:
                rec_p = [p[1] for p in m_state["price_history"][-20:]]
                _sma = np.mean(rec_p)
                _std = np.std(rec_p)
                if _sma > 0:
                    bb_w = (4.0 * _std) / _sma
            cycle_hit = bot.process_tick(previous_price, latest_price, now, bb_width=bb_w)
            if cycle_hit:
                _reason = cycle_hit.get('exit_reason', 'EXIT')
                _icon = {
                    "TARGET_PROFIT": "🎉", "RUNNER_EXPANSION": "🚀",
                    "STOP_LOSS": "🛑", "TRAILING_STOP": "🔔",
                    "BREAKEVEN": "🛡️", "TIMEOUT": "⏱️"
                }.get(_reason, "📋")
                _label = {
                    "TARGET_PROFIT": "Target Profit hit", "RUNNER_EXPANSION": "Runner Profit!",
                    "STOP_LOSS": "Stop Loss hit", "TRAILING_STOP": "Trailing Stop hit",
                    "BREAKEVEN": "Breakeven exit", "TIMEOUT": "Cycle timeout"
                }.get(_reason, _reason)
                st.toast(f"{_icon} {sym} Cycle {cycle_hit['cycle_id']}: {_label}! PnL: ${cycle_hit['pnl']:+.2f}")
            if sym == st.session_state.live_symbol:
                st.session_state.error_message = None
        except TradeDisabledError as tde:
            # Symbol not tradeable on this MT5 account — pause it gracefully, don't crash
            _tde_msg = (
                f"⛔ {sym} is not available for trading on your Exness MT5 account. "
                f"This symbol has been paused. "
                f"Only BTC/USD, ETH/USD, and XAU/USD are typically available on Exness Standard accounts."
            )
            print(f"TradeDisabledError for {sym}: {tde}")
            m_state["running"] = False
            m_state["trade_disabled"] = True
            if sym == st.session_state.live_symbol:
                st.session_state.running = False
                st.session_state.error_message = _tde_msg
            import pathlib
            _log_path = pathlib.Path(__file__).parent / "last_error.txt"
            with open(_log_path, "w") as f:
                f.write(f"TradeDisabledError for {sym}: {tde}")
        except Exception as e:
            import traceback
            err_str = f"Tick processing failed for {sym}: {e}\n{traceback.format_exc()}"
            print(err_str)
            m_state["running"] = False
            if sym == st.session_state.live_symbol:
                st.session_state.running = False
                st.session_state.error_message = f"Tick processing failed for {sym}: {e}"
            
            import pathlib
            _log_path = pathlib.Path(__file__).parent / "last_error.txt"
            with open(_log_path, "w") as f:
                f.write(err_str)
                
    save_bot_state()

# For symbols that are NOT running, we keep the active symbol price fresh on page load/interaction
if not st.session_state.running:
    now = time.time()
    if not st.session_state.price_history or (now - st.session_state.price_history[-1][0] > 5.0):
        active_ps = st.session_state.markets.get(st.session_state.live_symbol, {}).get("price_source", "Live Market API")
        if active_ps == "Simulated Market (Demo)":
            latest_price = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
        else:
            latest_price = get_current_live_price(st.session_state.live_symbol)
            if latest_price is not None:
                if st.session_state.price_history:
                    st.session_state.price_history[-1] = (now, latest_price)
                else:
                    st.session_state.price_history = [(now, latest_price)]
                st.session_state.last_price = latest_price
                
                # Update in active market dict
                if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
                    st.session_state.markets[st.session_state.live_symbol]["price_history"] = st.session_state.price_history
                    st.session_state.markets[st.session_state.live_symbol]["last_price"] = latest_price
                st.session_state.error_message = None
                # Note: no save_bot_state() here — idle price refresh saves nothing meaningful


# Get current state pointers — always use live_symbol as the authoritative source
# so the chart updates correctly after a symbol switch + rerun
_active_sym = st.session_state.live_symbol
if "price_history" in st.session_state and st.session_state.price_history and len(st.session_state.price_history) > 0 and st.session_state.price_history[-1][1] is not None:
    curr_price = st.session_state.price_history[-1][1]
elif "last_price" in st.session_state and st.session_state.last_price is not None:
    curr_price = st.session_state.last_price
else:
    curr_price = get_default_price(_active_sym)
broker_instance = st.session_state.broker
bot_instance = st.session_state.bot
broker_type = "Simulated Sandbox" if isinstance(broker_instance, SimulatedBroker) else "Exness MT5 Live"
display_symbol = "XAUUSD" if _active_sym == "PAXGUSDT" else _active_sym
_coin_label_map = {
    "BTCUSDT": "BTC/USD", "ETHUSDT": "ETH/USD", "SOLUSDT": "SOL/USD",
    "BNBUSDT": "BNB/USD", "DOGEUSDT": "DOGE/USD", "PAXGUSDT": "XAU/USD",
}
chart_coin_label = _coin_label_map.get(_active_sym, display_symbol)

# 9. KPI METRIC CARDS — full-width strip + 5 per-coin cards
# All-markets combined totals for the KPI strip
_all_real_pnl = sum(m.get("broker").realized_pnl for m in st.session_state.markets.values() if m.get("broker"))
_all_open_pos = sum(len(m.get("broker").open_positions) for m in st.session_state.markets.values() if m.get("broker"))
_all_float_pnl = sum(
    m.get("broker").get_floating_pnl(
        m.get("price_history", [])[-1][1] if m.get("price_history") else m.get("last_price", 0)
    )
    for m in st.session_state.markets.values() if m.get("broker")
)
_all_cycles = sum(len(m.get("bot").cycle_history) for m in st.session_state.markets.values() if m.get("bot"))
# Wins = TARGET_PROFIT + RUNNER_EXPANSION + TRAILING_STOP + BREAKEVEN (all profitable exits)
_WIN_REASONS = {"TARGET_PROFIT", "RUNNER_EXPANSION", "TRAILING_STOP", "BREAKEVEN"}
_all_wins = sum(
    sum(1 for c in m["bot"].cycle_history if c.get("exit_reason") in _WIN_REASONS)
    for m in st.session_state.markets.values() if m.get("bot")
)
_win_rate = (_all_wins / _all_cycles * 100) if _all_cycles > 0 else 0.0
_total_pnl_color = "var(--green)" if _all_real_pnl >= 0 else "var(--red)"
_float_color = "var(--green)" if _all_float_pnl >= 0 else "var(--red)"

# Price change calculation
_price_change_pct = ""
if len(st.session_state.price_history) >= 2:
    _p_first = st.session_state.price_history[0][1]
    _p_last  = curr_price
    if _p_first > 0:
        _chg = (_p_last - _p_first) / _p_first * 100
        _price_change_pct = f"{'↑' if _chg >= 0 else '↓'} {abs(_chg):.2f}%"

st.markdown(f"""
<div class="kpi-bar">
    <div class="kpi-item">
        <div class="kpi-lbl">📡 {chart_coin_label} Price</div>
        <div class="kpi-val">${curr_price:,.2f}</div>
        <div class="kpi-sub" style="color:{'var(--green)' if '↑' in _price_change_pct else 'var(--red)' if '↓' in _price_change_pct else 'var(--text-dim)'}">{_price_change_pct or 'Session Start'}</div>
    </div>
    <div class="kpi-item">
        <div class="kpi-lbl">💰 Total Realized PnL</div>
        <div class="kpi-val" style="color:{_total_pnl_color}">${_all_real_pnl:+,.2f}</div>
        <div class="kpi-sub">All {len(st.session_state.markets)} markets combined</div>
    </div>
    <div class="kpi-item">
        <div class="kpi-lbl">📈 Floating PnL</div>
        <div class="kpi-val" style="color:{_float_color}">${_all_float_pnl:+,.2f}</div>
        <div class="kpi-sub">{_all_open_pos} open position{'' if _all_open_pos == 1 else 's'}</div>
    </div>
    <div class="kpi-item">
        <div class="kpi-lbl">🎯 Win Rate</div>
        <div class="kpi-val">{_win_rate:.1f}%</div>
        <div class="kpi-sub">{_all_wins} TP hits / {_all_cycles} cycles</div>
    </div>
    <div class="kpi-item">
        <div class="kpi-lbl">⚡ Active Markets</div>
        <div class="kpi-val">{_active_markets_count} / {len(st.session_state.markets)}</div>
        <div class="kpi-sub">{'Running' if _active_markets_count > 0 else 'All idle'}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Per-active-coin 5-card metric row
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
with kpi1:
    metric_card("Current Price", f"${curr_price:,.2f}")
with kpi2:
    metric_card("Account Balance", f"${broker_instance.balance:,.2f}")
with kpi3:
    equity = broker_instance.get_equity(curr_price)
    metric_card("Account Equity", f"${equity:,.2f}")
with kpi4:
    float_pnl = broker_instance.get_floating_pnl(curr_price)
    pnl_type = "up" if float_pnl > 0 else ("down" if float_pnl < 0 else "warn")
    runner_tag = " 🚀 RUNNER" if getattr(bot_instance, "in_runner_mode", False) else ""
    metric_card(f"Floating PnL{runner_tag}", f"${float_pnl:,.2f}", delta=f"{float_pnl:+.2f}" if float_pnl != 0 else None, delta_type=pnl_type)
with kpi5:
    real_pnl = broker_instance.realized_pnl
    pnl_type = "up" if real_pnl > 0 else ("down" if real_pnl < 0 else "warn")
    metric_card("Realized PnL", f"${real_pnl:,.2f}", delta=f"{real_pnl:+.2f}" if real_pnl != 0 else None, delta_type=pnl_type)

# Alerts if any
if st.session_state.error_message:
    st.warning(st.session_state.error_message)

# Smart Runner Mode Live Status Banner
if getattr(bot_instance, "in_runner_mode", False):
    lock_pct = int(round(getattr(bot_instance, "profit_lock_pct", 0.80) * 100))
    peak_pnl = getattr(bot_instance, "max_floating_pnl", float_pnl)
    num_pos = len(broker_instance.open_positions)
    friction_floor = max(3.00, 3.00 + (num_pos * 0.75))
    floor_val = max(bot_instance.target_profit * 0.80, peak_pnl * (lock_pct / 100.0), friction_floor)
    st.markdown(f"""
    <div style="background: rgba(34, 197, 94, 0.1); border: 1px solid rgba(34, 197, 94, 0.4); border-radius: 8px; padding: 12px 18px; margin-top: 10px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;">
        <div>
            <div style="font-weight: 700; color: #22c55e; font-size: 0.95rem; display: flex; align-items: center; gap: 8px;">
                <span>🚀 SMART PROFIT EXPANSION ACTIVE ({chart_coin_label})</span>
                <span class="badge badge-green" style="font-size:0.7rem;">RUNNER MODE</span>
            </div>
            <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 3px;">
                Target Profit (${bot_instance.target_profit:.2f}) surpassed! Peak PnL reached <strong>${peak_pnl:+,.2f}</strong>. Ratcheting {lock_pct}% floor to maximize trend upside.
            </div>
        </div>
        <div style="text-align: right; background: rgba(34, 197, 94, 0.15); padding: 6px 14px; border-radius: 6px;">
            <div style="font-size: 0.68rem; color: var(--text-muted); text-transform: uppercase; font-weight:600;">Locked Profit Floor</div>
            <div style="font-size: 1.15rem; font-weight: 800; color: #22c55e;">+${floor_val:,.2f} USD</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# 10. PLOTLY LIVE CHART
# Convert ticks to candlesticks based on selected timeframe
timeframe_choice = st.session_state.get("timeframe_select", "5 Seconds")
if timeframe_choice == "1 Minute":
    interval_seconds = 60.0
else:
    interval_seconds = 5.0
ticks = st.session_state.price_history
ohlc_df = pd.DataFrame()

if len(ticks) >= 1:
    df_ticks = pd.DataFrame(ticks, columns=["time", "price"])
    df_ticks["interval_id"] = (df_ticks["time"] // interval_seconds) * interval_seconds
    ohlc = df_ticks.groupby("interval_id")["price"].agg(
        open="first",
        high="max",
        low="min",
        close="last"
    ).reset_index()
    ohlc["datetime"] = pd.to_datetime(ohlc["interval_id"], unit="s")
    ohlc_df = ohlc

fig = go.Figure()

if not ohlc_df.empty:
    fig.add_trace(go.Candlestick(
        x=ohlc_df["datetime"],
        open=ohlc_df["open"],
        high=ohlc_df["high"],
        low=ohlc_df["low"],
        close=ohlc_df["close"],
        name=f"{display_symbol} Price",
        increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444",
        increasing_fillcolor="rgba(34, 197, 94, 0.2)",
        decreasing_fillcolor="rgba(239, 68, 68, 0.2)"
    ))

# Current price indicator line
fig.add_hline(
    y=curr_price,
    line_dash="dot",
    line_color="#a1a1aa",
    annotation_text=f"Current: ${curr_price:.2f}",
    annotation_position="bottom right"
)

# Trap levels lines
if broker_instance.pending_orders:
    # Place buy/sell stops in chart
    for o in list(broker_instance.pending_orders.values()):
        if o.type == "BUY_STOP":
            line_color = "rgba(34, 197, 94, 0.35)" if IS_DARK else "rgba(22, 163, 74, 0.4)"
            fig.add_hline(
                y=o.trigger_price,
                line_dash="dash",
                line_color=line_color,
                annotation_text=f"BUY STOP: ${o.trigger_price:.2f}",
                annotation_position="top left",
                annotation_font=dict(size=8, color=line_color)
            )
        elif o.type == "SELL_STOP":
            line_color = "rgba(239, 68, 68, 0.35)" if IS_DARK else "rgba(220, 38, 38, 0.4)"
            fig.add_hline(
                y=o.trigger_price,
                line_dash="dash",
                line_color=line_color,
                annotation_text=f"SELL STOP: ${o.trigger_price:.2f}",
                annotation_position="bottom left",
                annotation_font=dict(size=8, color=line_color)
            )
else:
    # Render proposed preview traps on chart before deployment to MT5
    if st.session_state.strat_is_percent:
        offset_val = curr_price * (st.session_state.strat_offset / 100.0)
        gap_val = curr_price * (st.session_state.strat_gap / 100.0)
    else:
        offset_val = st.session_state.strat_offset
        gap_val = st.session_state.strat_gap

    # Proposed BUY STOP levels
    for i in range(10):
        trigger_price = curr_price + offset_val + (i * gap_val)
        if broker_type == "Exness MT5 Live" and broker_instance.ensure_connected():
            import MetaTrader5 as mt5_ref
            exness_symbol = broker_instance.get_exness_symbol(broker_instance.symbol)
            tick = mt5_ref.symbol_info_tick(exness_symbol)
            info = mt5_ref.symbol_info(exness_symbol)
            if tick and info:
                spread_pts = (tick.ask - tick.bid) / info.point if info.point > 0 else 0
                stop_level_pts = int(max(info.trade_stops_level, spread_pts * 2.5)) + 2
                min_allowed = tick.ask + stop_level_pts * info.point
                if trigger_price < min_allowed:
                    trigger_price = min_allowed
        
        line_color = "rgba(59, 130, 246, 0.15)" if IS_DARK else "rgba(37, 99, 235, 0.15)"
        fig.add_hline(
            y=trigger_price,
            line_dash="dot",
            line_color=line_color,
            annotation_text=f"Proposed BUY STOP #{i+1}: ${trigger_price:.2f}",
            annotation_position="top left",
            annotation_font=dict(size=7, color=line_color)
        )

    # Proposed SELL STOP levels
    for i in range(10):
        trigger_price = curr_price - offset_val - (i * gap_val)
        if broker_type == "Exness MT5 Live" and broker_instance.ensure_connected():
            import MetaTrader5 as mt5_ref
            exness_symbol = broker_instance.get_exness_symbol(broker_instance.symbol)
            tick = mt5_ref.symbol_info_tick(exness_symbol)
            info = mt5_ref.symbol_info(exness_symbol)
            if tick and info:
                spread_pts = (tick.ask - tick.bid) / info.point if info.point > 0 else 0
                stop_level_pts = int(max(info.trade_stops_level, spread_pts * 2.5)) + 2
                max_allowed = tick.bid - stop_level_pts * info.point
                if trigger_price > max_allowed:
                    trigger_price = max_allowed
        
        line_color = "rgba(245, 158, 11, 0.15)" if IS_DARK else "rgba(217, 119, 6, 0.15)"
        fig.add_hline(
            y=trigger_price,
            line_dash="dot",
            line_color=line_color,
            annotation_text=f"Proposed SELL STOP #{i+1}: ${trigger_price:.2f}",
            annotation_position="bottom left",
            annotation_font=dict(size=7, color=line_color)
        )

# Plot open positions
for pos_id, pos in list(broker_instance.open_positions.items()):
    pos_color = "#22c55e" if pos.type == "BUY" else "#ef4444"
    fig.add_hline(
        y=pos.entry_price,
        line_color=pos_color,
        line_width=1.5,
        annotation_text=f"Open {pos.type} {pos.size}: ${pos.entry_price:.2f}",
        annotation_position="top right",
        annotation_font=dict(size=9, color=pos_color)
    )

fig.update_layout(PLOT_LAYOUT)
fig.update_layout(
    xaxis_rangeslider_visible=False,
    # Reset Y-axis autorange on every render so it scales correctly to the active coin's price
    yaxis=dict(autorange=True, fixedrange=False),
    title=None,  # Title rendered via markdown below
)
fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)" if IS_DARK else "rgba(0,0,0,0.05)")
fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)" if IS_DARK else "rgba(0,0,0,0.05)")

with st.container(border=True):
    st.markdown(
        f'<div class="brand" style="margin-bottom: 5px;">'
        f'<span class="chart-title">'
        f'{chart_coin_label} &nbsp;·&nbsp; Real-Time Traps &amp; Execution Chart'
        f'<span style="font-size:0.7rem; font-weight:400; opacity:0.6; margin-left:8px;">({timeframe_choice})</span>'
        f'</span></div>'
        f'<div class="chart-subtitle">Live price, grid trap levels and executed orders for <strong>{chart_coin_label}</strong> — 10 stops above &amp; 10 below</div>',
        unsafe_allow_html=True
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# 11. TABLES
col_tables1, col_tables2 = st.columns(2)

with col_tables1:
    if broker_instance.open_positions:
        rows_html = ""
        for pos in list(broker_instance.open_positions.values()):
            pnl = pos.get_pnl(curr_price)
            pnl_style = "color: var(--green);" if pnl >= 0 else "color: var(--red);"
            badge_type = "green" if pos.type == "BUY" else "red"
            badge_html = render_badge(pos.type, badge_type)
            rows_html += f"<tr><td>{pos.position_id}</td><td>{badge_html}</td><td>${pos.entry_price:,.2f}</td><td>{fmt_size(pos.size)}</td><td style='{pnl_style} font-weight: bold;'>${pnl:+,.2f}</td></tr>"
        table_html = f"""
        <div class="table-wrap">
            <h4>Active Positions</h4>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Position ID</th>
                        <th>Type</th>
                        <th>Entry Price</th>
                        <th>Size</th>
                        <th>Floating PnL</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    else:
        table_html = """
        <div class="table-wrap">
            <h4>Active Positions</h4>
            <div class="empty-state">
                <div class="empty-state-icon">⧇</div>
                No active positions in the current cycle
            </div>
        </div>
        """
    st.markdown(textwrap.dedent(table_html), unsafe_allow_html=True)

    # Render other manual/external positions on the account
    other_pos = getattr(broker_instance, "get_all_account_positions", lambda: [])()
    if other_pos:
        rows_other_html = ""
        for p in other_pos:
            badge_type = "green" if p["type"] == "BUY" else "red"
            badge_html = render_badge(p["type"], badge_type)
            rows_other_html += f"<tr><td>{p['ticket']}</td><td>{p['symbol']}</td><td>{badge_html}</td><td>${p['price']:,.2f}</td><td>{fmt_size(p['volume'])}</td><td style='font-weight: bold; color: {'var(--green)' if p['profit'] >= 0 else 'var(--red)'};'>${p['profit']:+,.2f}</td><td>Magic: {p['magic']}</td></tr>"
        
        other_table_html = f"""
        <div class="table-wrap" style="margin-top: 15px; border-color: rgba(245, 158, 11, 0.25);">
            <h4 style="color: #f59e0b; display: flex; align-items: center; gap: 6px; margin: 0;">
                <span>🔌 Other Account Positions (Manual / External)</span>
            </h4>
            <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 8px;">
                These trades belong to other bots or manual orders and are ignored by this bot's profit targets.
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Ticket ID</th>
                        <th>Symbol</th>
                        <th>Type</th>
                        <th>Entry Price</th>
                        <th>Size</th>
                        <th>Profit</th>
                        <th>Identifier</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_other_html}
                </tbody>
            </table>
        </div>
        """
        st.markdown(textwrap.dedent(other_table_html), unsafe_allow_html=True)

with col_tables2:
    if broker_instance.pending_orders:
        rows_html = ""
        sorted_orders = sorted(list(broker_instance.pending_orders.values()), key=lambda x: x.trigger_price, reverse=True)
        for o in sorted_orders:
            badge_type = "green" if "BUY" in o.type else "red"
            badge_html = render_badge(o.type, badge_type)
            rows_html += f"<tr><td>{o.order_id}</td><td>{badge_html}</td><td>${o.trigger_price:,.2f}</td><td>{fmt_size(o.size)}</td></tr>"
        table_html = f"""
        <div class="table-wrap">
            <h4>Active Grid Traps (Pending Orders)</h4>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Order ID</th>
                        <th>Type</th>
                        <th>Trigger Price</th>
                        <th>Size</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    else:
        is_mt5 = (broker_instance.__class__.__name__ == "MT5Broker")
        if is_mt5 and not st.session_state.running:
            table_html = """
            <div class="table-wrap" style="border-color: rgba(245, 158, 11, 0.25);">
                <h4>Active Grid Traps (Pending Orders)</h4>
                <div class="empty-state">
                    <div class="empty-state-icon" style="color: #f59e0b; text-shadow: 0 0 10px rgba(245, 158, 11, 0.2);">🔌</div>
                    <div style="font-weight: 600; color: #f59e0b; margin-bottom: 4px;">Exness Account Linked</div>
                    <div style="font-size: 0.72rem; max-width: 260px; margin: 0 auto; color: var(--text-muted);">
                        Click <strong style="color: var(--text-color);">▶ START BOT</strong> to deploy the breakout grid traps on your Exness MT5 terminal!
                    </div>
                </div>
            </div>
            """
        else:
            table_html = """
            <div class="table-wrap">
                <h4>Active Grid Traps (Pending Orders)</h4>
                <div class="empty-state">
                    <div class="empty-state-icon">◇</div>
                    No pending traps deployed in the market
                </div>
            </div>
            """
    st.markdown(textwrap.dedent(table_html), unsafe_allow_html=True)

# 12. HISTORY LOGS SECTIONS — Single unified section with pair filter
st.markdown("---")

# Pair filter: "All Pairs" or a specific coin
_all_pair_labels = list(dict.fromkeys(["BTC/USD", "ETH/USD", "XAU/USD", "SOL/USD", "BNB/USD", "DOGE/USD"] + [_coin_label_map.get(s, s) for s in st.session_state.markets.keys()]))
_filter_options = ["🌐 All Pairs"] + _all_pair_labels
_hist_filter = st.selectbox(
    "📊 Account History — Filter by Pair",
    options=_filter_options,
    index=0,
    key="history_pair_filter"
)

st.markdown(f"### 🌐 Account History ({_hist_filter})")
tab_all_cycles, tab_all_trades = st.tabs(["🔄 Completed Cycles", "📜 Detailed Trades Log"])

# Determine which symbol maps to the selected filter label
_filter_sym = None
if _hist_filter != "🌐 All Pairs":
    for _s, _lbl in _coin_label_map.items():
        if _lbl == _hist_filter:
            _filter_sym = _s
            break


with tab_all_cycles:
    all_cycles = []
    for sym, m_data in st.session_state.markets.items():
        if _filter_sym and sym != _filter_sym:
            continue
        if m_data.get("bot") and m_data["bot"].cycle_history:
            coin_lbl = _coin_label_map.get(sym, sym)
            for c in m_data["bot"].cycle_history:
                c_copy = dict(c)
                c_copy["symbol_label"] = coin_lbl
                all_cycles.append(c_copy)
    all_cycles = sorted(all_cycles, key=lambda x: x["exit_time"], reverse=True)

    if all_cycles:
        rows_html = ""
        _all_c_pnl = 0.0
        _all_wins = 0
        _all_losses = 0
        for cycle in all_cycles:
            _all_c_pnl += cycle["pnl"]
            pnl_color = "var(--green)" if cycle["pnl"] >= 0 else "var(--red)"
            dt_str = datetime.fromtimestamp(cycle["exit_time"]).strftime("%m/%d %H:%M:%S")
            dur_s = cycle["exit_time"] - cycle["start_time"]
            dur_str = f"{int(dur_s//60)}m {int(dur_s%60)}s" if dur_s >= 60 else f"{dur_s:.1f}s"
            reason = cycle.get("exit_reason", "")
            if reason == "RUNNER_EXPANSION":
                reason_badge = '<span class="badge badge-green">🚀 RUNNER+</span>'
                _all_wins += 1
            elif reason == "TARGET_PROFIT":
                reason_badge = '<span class="badge badge-green">✓ TARGET</span>'
                _all_wins += 1
            elif reason == "STOP_LOSS":
                reason_badge = '<span class="badge badge-red">✗ STOP</span>'
                _all_losses += 1
            elif reason == "TRAILING_STOP":
                reason_badge = '<span class="badge badge-amber">⟳ TRAIL</span>'
                _all_wins += 1
            elif reason == "BREAKEVEN":
                reason_badge = '<span class="badge badge-blue">⊘ B/E</span>'
                _all_wins += 1
            elif reason == "TIMEOUT":
                reason_badge = '<span class="badge badge-amber">⏱ TIMEOUT</span>'
                _all_losses += 1
            else:
                reason_badge = f'<span class="badge badge-blue">{reason}</span>'
            rows_html += (
                f"<tr>"
                f"<td style='font-weight:600; color:var(--text-color);'>{cycle['symbol_label']}</td>"
                f"<td style='color:var(--text-muted);'>#{cycle['cycle_id']}</td>"
                f"<td>${cycle['deploy_price']:,.2f}</td>"
                f"<td>${cycle['exit_price']:,.2f}</td>"
                f"<td>{cycle['trades_count']}</td>"
                f"<td style='color:var(--text-muted);'>{dur_str}</td>"
                f"<td>{reason_badge}</td>"
                f"<td style='color:{pnl_color};font-weight:700;'>${cycle['pnl']:+,.2f}</td>"
                f"<td style='color:var(--text-dim);'>{dt_str}</td>"
                f"</tr>"
            )
        _all_c_total = len(all_cycles)
        _all_c_wr = _all_wins / _all_c_total * 100 if _all_c_total > 0 else 0
        _foot_pnl_color = "var(--green)" if _all_c_pnl >= 0 else "var(--red)"
        footer_html = (
            f"<tfoot><tr>"
            f"<td colspan='5'>📊 {_all_c_total} All-Pairs Cycles &nbsp;·&nbsp; {_all_wins}W / {_all_losses}L &nbsp;·&nbsp; Win Rate: {_all_c_wr:.1f}%</td>"
            f"<td></td><td></td>"
            f"<td style='color:{_foot_pnl_color};'>${_all_c_pnl:+,.2f} Total</td>"
            f"<td></td>"
            f"</tr></tfoot>"
        )
        cycles_html = f"""
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Pair</th>
                        <th>Cycle</th>
                        <th>Deploy Price</th>
                        <th>Exit Price</th>
                        <th>Fills</th>
                        <th>Duration</th>
                        <th>Exit Reason</th>
                        <th>Net PnL</th>
                        <th>Completed At</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
                {footer_html}
            </table>
        </div>
        """
    else:
        cycles_html = """
        <div class="table-wrap">
            <div class="empty-state"><div class="empty-state-icon">🌐</div>No completed breakout cycles across any market yet</div>
        </div>
        """
    st.markdown(textwrap.dedent(cycles_html), unsafe_allow_html=True)

with tab_all_trades:
    all_trades = []
    for sym, m_data in st.session_state.markets.items():
        if _filter_sym and sym != _filter_sym:
            continue
        if m_data.get("broker") and m_data["broker"].closed_trades:
            coin_lbl = _coin_label_map.get(sym, sym)
            for t in m_data["broker"].closed_trades:
                t_copy = dict(t)
                t_copy["symbol_label"] = coin_lbl
                all_trades.append(t_copy)
    all_trades = sorted(all_trades, key=lambda x: x["exit_time"], reverse=True)

    if all_trades:
        rows_html = ""
        for t in all_trades:
            pnl_style = "color: var(--green);" if t["pnl"] >= 0 else "color: var(--red);"
            dt_entry = datetime.fromtimestamp(t["entry_time"]).strftime("%m/%d %H:%M:%S")
            dt_exit = datetime.fromtimestamp(t["exit_time"]).strftime("%m/%d %H:%M:%S")
            badge_type = "green" if t["type"] == "BUY" else "red"
            badge_html = render_badge(t["type"], badge_type)
            comm_val = t.get("commission", 0.0)
            comm_str = f"-${abs(comm_val):,.4f}" if comm_val < 0 else f"${comm_val:,.4f}"
            
            rows_html += f"<tr><td style='font-weight:600;'>{t['symbol_label']}</td><td>{t['position_id']}</td><td>{badge_html}</td><td>${t['entry_price']:,.2f}</td><td>${t['exit_price']:,.2f}</td><td>{fmt_size(t['size'])}</td><td>{comm_str}</td><td style='{pnl_style} font-weight: bold;'>${t['pnl']:+,.2f}</td><td>{dt_entry}</td><td>{dt_exit}</td></tr>"
        trades_html = f"""
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Pair</th>
                        <th>Trade ID</th>
                        <th>Type</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>Size</th>
                        <th>Commission</th>
                        <th>Net PnL</th>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    else:
        trades_html = """
        <div class="table-wrap">
            <p style='font-size:0.8rem; color:#71717a; margin: 0;'>No detailed trades executed across any market yet</p>
        </div>
        """
    st.markdown(textwrap.dedent(trades_html), unsafe_allow_html=True)



# 13. RUNNER LOOP
any_running = any(m.get("running", False) for m in st.session_state.markets.values())
if any_running:
    time.sleep(1.0)
    st.rerun()
