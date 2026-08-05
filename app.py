import logging
import warnings
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)
from typing import Optional
import streamlit as st
# Trigger hot reload 3 - Safe session state initializations applied
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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

# Import core bot logic with module auto-reload support for Streamlit
import importlib
import core.data
import core.engine
importlib.reload(core.data)
importlib.reload(core.engine)

from core.mt5_broker import MT5Broker, SimulatedBroker, MT5_AVAILABLE, get_symbol_magic_number, TradeDisabledError
from core.engine import BreakoutGridBot, get_pip_size, AutoReadingEngine
from core.license import LicenseManager, LicenseTier
from core.signals import send_telegram_alert, dispatch_trade_exit_signal
from core.data import get_live_price, get_historical_klines, interpolate_ticks, get_fear_and_greed_index, get_24h_market_stats, get_crypto_news, calculate_technical_indicators, get_order_book_depth, get_economic_calendar

# 1. PAGE CONFIGURATION
st.set_page_config(
    page_title="Profity AI",
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
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=DM+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
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
    font-family: 'Outfit', 'DM Sans', -apple-system, sans-serif !important;
}}

.block-container {{
    padding: 1.5rem 2rem 2rem !important;
    max-width: 1440px !important;
}}

/* Grid layout gap */
[data-testid="stHorizontalBlock"] {{
    gap: 1.25rem !important;
}}

/* Glassmorphic Metric Cards styling */
.metric-card {{
    background: var(--card);
    background-image: radial-gradient(at 100% 0%, rgba(59, 130, 246, 0.05) 0px, transparent 50%);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.15rem 1.3rem;
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 94px;
    backdrop-filter: blur(12px);
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}}
.metric-card:hover {{
    transform: translateY(-2px);
    border-color: rgba(59,130,246,0.45);
    box-shadow: 0 8px 30px rgba(59,130,246,0.12);
}}
.metric-label {{
    font-size: 0.76rem;
    color: var(--text-muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-family: 'Outfit', sans-serif;
}}
.metric-value {{
    font-size: 1.65rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.02em;
    margin-top: 0.2rem;
    font-family: 'JetBrains Mono', monospace;
}}
.metric-delta {{
    font-size: 0.72rem;
    font-weight: 600;
    margin-top: 0.35rem;
    padding: 2px 8px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    width: fit-content;
}}
.delta-up {{ color: #22c55e; background: rgba(34, 197, 94, 0.14); border: 1px solid rgba(34, 197, 94, 0.25); }}
.delta-down {{ color: #ef4444; background: rgba(239, 68, 68, 0.14); border: 1px solid rgba(239, 68, 68, 0.25); }}
.delta-warn {{ color: #f59e0b; background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.25); }}

/* Chart Card Wrap */
.chart-wrap {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    box-shadow: var(--shadow);
    margin-bottom: 1rem;
}}
.chart-title {{
    font-size: 0.92rem;
    font-weight: 700;
    color: var(--text);
    font-family: 'Outfit', sans-serif;
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
    border-top: 3px solid var(--accent);
    border-radius: var(--radius);
    padding: 1.25rem;
    box-shadow: var(--shadow);
    margin-bottom: 1rem;
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
}}
.control-card:hover {{
    box-shadow: 0 6px 30px rgba(59,130,246,0.1);
}}
.control-title {{
    font-size: 0.88rem;
    font-weight: 800;
    color: var(--text);
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border-subtle);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: 'Outfit', sans-serif;
}}

/* Button Enhancements */
div.stButton > button {{
    font-family: 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: 0.03em !important;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
}}
div.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35) !important;
    border: none !important;
}}
div.stButton > button[kind="primary"]:hover {{
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(37, 99, 235, 0.5) !important;
}}
div.stButton > button[kind="secondary"] {{
    border: 1px solid var(--border) !important;
    background: var(--card) !important;
}}
div.stButton > button[kind="secondary"]:hover {{
    border-color: var(--accent) !important;
    color: var(--accent) !important;
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
    padding: 0.65rem 0.85rem;
    color: var(--text-muted);
    font-weight: 700;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
    font-family: 'Outfit', sans-serif;
}}
.data-table td {{
    padding: 0.65rem 0.85rem;
    color: var(--text);
    border-bottom: 1px solid var(--border-subtle);
    font-family: 'JetBrains Mono', monospace;
}}
.data-table tr:last-child td {{
    border-bottom: none;
}}
.data-table tbody tr:hover td {{
    background: rgba(59,130,246,0.05);
}}

/* Badge styles */
.badge {{
    display: inline-block;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 0.7rem;
    font-weight: 700;
    font-family: 'Outfit', sans-serif;
}}
.badge-green {{ color: #22c55e; background: rgba(34, 197, 94, 0.14); border: 1px solid rgba(34, 197, 94, 0.2); }}
.badge-red {{ color: #ef4444; background: rgba(239, 68, 68, 0.14); border: 1px solid rgba(239, 68, 68, 0.2); }}
.badge-amber {{ color: #f59e0b; background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.2); }}
.badge-blue {{ color: #3b82f6; background: rgba(59, 130, 246, 0.14); border: 1px solid rgba(59, 130, 246, 0.2); }}

/* Empty state placeholder */
.empty-state {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2.2rem 1rem;
    border: 1px dashed var(--border);
    background: var(--bg-subtle);
    border-radius: var(--radius);
    text-align: center;
    color: var(--text-muted);
    font-size: 0.78rem;
    margin-top: 0.5rem;
}}
.empty-state-icon {{
    font-size: 1.5rem;
    margin-bottom: 0.4rem;
    color: var(--text-dim);
    opacity: 0.85;
}}

/* Top Brand Row */
.brand-container {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.25rem;
    padding-bottom: 0.85rem;
    border-bottom: 1px solid var(--border);
}}
.brand-logo {{
    font-weight: 800;
    font-size: 1.45rem;
    letter-spacing: -0.03em;
    color: var(--text);
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-family: 'Outfit', sans-serif;
}}
.brand-logo span {{ 
    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}}
.brand-meta {{
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 0.75rem;
    color: var(--text-muted);
}}
.brand-badge {{
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    font-family: 'Outfit', sans-serif;
}}

/* Pulse animation for RUNNING status dot */
@keyframes pulse-dot {{
    0%   {{ box-shadow: 0 0 0 0 rgba(34,197,94,0.7); }}
    70%  {{ box-shadow: 0 0 0 8px rgba(34,197,94,0); }}
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

# --- MARKET INTELLIGENCE CACHED FETCHERS ---
@st.cache_data(ttl=60)
def fetch_cached_fg_index():
    return get_fear_and_greed_index()

@st.cache_data(ttl=30)
def fetch_cached_24h_stats(symbol: str):
    return get_24h_market_stats(symbol)

@st.cache_data(ttl=120)
def fetch_cached_news(symbol: str):
    return get_crypto_news(symbol)

@st.cache_data(ttl=15)
def fetch_cached_order_book(symbol: str):
    return get_order_book_depth(symbol)

@st.cache_data(ttl=300)
def fetch_cached_calendar():
    return get_economic_calendar()

@st.cache_data(ttl=15)
def fetch_cached_klines(symbol: str):
    return get_historical_klines(symbol, interval="1m", limit=100)

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
    "BTCUSDT": {"gap": 0.22, "offset": 0.33, "multiplier": 1.25, "order_size": 0.01, "target_profit": 10.0, "stop_loss": 0.0},
    "ETHUSDT": {"gap": 0.22, "offset": 0.33, "multiplier": 1.25, "order_size": 0.10, "target_profit": 10.0, "stop_loss": 0.0},
    "SOLUSDT": {"gap": 0.08, "offset": 0.12, "multiplier": 1.25, "order_size": 1.50, "target_profit": 10.0, "stop_loss": 0.0},
    "BNBUSDT": {"gap": 0.12, "offset": 0.18, "multiplier": 1.25, "order_size": 0.08, "target_profit": 10.0, "stop_loss": 0.0},
    "DOGEUSDT": {"gap": 0.08, "offset": 0.12, "multiplier": 1.25, "order_size": 1500.0, "target_profit": 10.0, "stop_loss": 0.0},
    "PAXGUSDT": {"gap": 0.10, "offset": 0.15, "multiplier": 1.25, "order_size": 0.01, "target_profit": 10.0, "stop_loss": 0.0},
}

def get_coin_golden_settings(symbol: str) -> dict:
    return GOLDEN_SETTINGS.get(symbol.upper(), {"gap": 0.22, "offset": 0.33, "multiplier": 1.25, "order_size": 0.01, "target_profit": 10.0, "stop_loss": 0.0})

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
        active["strat_spacing_mode"] = st.session_state.get("strat_spacing_mode", "Percentage (%)")
        active["strat_is_percent"] = (active["strat_spacing_mode"] == "Percentage (%)")
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
        "strat_spacing_mode": m_state.get("strat_spacing_mode", "Percentage (%)"),
        "strat_is_percent": m_state.get("strat_is_percent", True),
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
        "bot_last_deploy_time": getattr(bot, "last_deploy_time", 0.0),
        "bot_current_cycle_id": bot.current_cycle_id,
        "bot_cycle_start_time": bot.cycle_start_time,
        "bot_cycle_history": bot.cycle_history,
        "bot_max_floating_pnl": getattr(bot, "max_floating_pnl", -float("inf")),
        "bot_breakeven_activated": getattr(bot, "breakeven_activated", False),
        "bot_in_runner_mode": getattr(bot, "in_runner_mode", False),
        "cancel_opposite_on_trigger": getattr(bot, "cancel_opposite_on_trigger", True)
    }
    return serialized

def deserialize_market_state(ser, symbol):
    from core.mt5_broker import MT5Broker, SimulatedBroker, MT5_AVAILABLE
    from core.engine import BreakoutGridBot, Position, Order, get_pip_size
    
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
    for pos_id, pos_data in ser.get("broker_open_positions", {}).items():
        if isinstance(pos_data, dict):
            pos = Position(pos_data["type"], pos_data["entry_price"], pos_data["size"], pos_data["entry_time"])
            pos.position_id = pos_data.get("position_id", pos_id)
        else:
            pos = pos_data
        broker.open_positions[pos_id] = pos
        if broker_class != "SimulatedBroker":
            try:
                # Populate ticket mapping back (MT5Broker only)
                clean_id = str(pos_id).replace("live_", "")
                if clean_id.isdigit():
                    ticket_num = int(clean_id)
                    broker.ticket_to_position_id[ticket_num] = pos_id
            except Exception:
                pass
                
    # Recreate broker pending orders
    broker.pending_orders = {}
    for order_id, o_data in ser.get("broker_pending_orders", {}).items():
        if isinstance(o_data, dict):
            o = Order(o_data["type"], o_data["trigger_price"], o_data["size"], o_data["timestamp"])
            o.order_id = o_data.get("order_id", order_id)
        else:
            o = o_data
        broker.pending_orders[order_id] = o
        if broker_class != "SimulatedBroker":
            try:
                clean_id = str(order_id).replace("live_", "")
                if clean_id.isdigit():
                    ticket_num = int(clean_id)
                    broker.ticket_to_order_id[ticket_num] = order_id
            except Exception:
                pass
                
    # Recreate Bot using safe fallbacks
    gs = get_coin_golden_settings(symbol)
    saved_spacing_mode = ser.get("strat_spacing_mode")
    if not saved_spacing_mode:
        saved_spacing_mode = "Percentage (%)" if ser.get("strat_is_percent", True) else "USD Points ($)"

    bot = BreakoutGridBot(
        broker,
        grid_levels=10,
        grid_gap=ser.get("strat_gap", gs["gap"]),
        trap_offset=ser.get("strat_offset", gs["offset"]),
        order_size=ser.get("strat_order_size", gs["order_size"]),
        order_size_multiplier=ser.get("strat_size_multiplier", gs["multiplier"]),
        target_profit=ser.get("strat_target_profit", gs["target_profit"]),
        auto_restart=True,
        is_percent=(saved_spacing_mode == "Percentage (%)"),
        spacing_mode=saved_spacing_mode,
        stop_loss=ser.get("strat_sl", gs["stop_loss"]),
        max_cycle_duration=float('inf'),
        cancel_opposite_on_trigger=ser.get("cancel_opposite_on_trigger", False),
        use_trailing_stop=ser.get("strat_trailing", False),
        trailing_stop_distance=ser.get("strat_trailing_dist", 1.5),
        use_breakeven=ser.get("strat_breakeven", False),
        breakeven_trigger=ser.get("strat_breakeven_trigger", 0.5),
        use_smart_trailing=ser.get("strat_smart_trailing", True),
        profit_lock_pct=ser.get("strat_profit_lock_pct", 0.80)
    )
    
    bot.deployed = ser.get("bot_deployed", False)
    bot.deploy_price = ser.get("bot_deploy_price", 0.0)
    bot.last_deploy_time = ser.get("bot_last_deploy_time", 0.0)
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
        "strat_spacing_mode": saved_spacing_mode,
        "strat_is_percent": (saved_spacing_mode == "Percentage (%)"),
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
if "live_symbol" not in st.session_state:
    st.session_state.live_symbol = "BTCUSDT"
if "running" not in st.session_state:
    st.session_state.running = False
if "markets" not in st.session_state:
    st.session_state.markets = {}

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
        cancel_opposite_on_trigger=False,
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
    _mode_def = active_market.get("strat_spacing_mode")
    if not _mode_def:
        _mode_def = "Percentage (%)" if active_market.get("strat_is_percent", True) else "USD Points ($)"
    st.session_state.strat_spacing_mode = _mode_def
    st.session_state.strat_is_percent = (_mode_def == "Percentage (%)")
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

_spacing_mode_key = f"strat_spacing_mode_select_{_sym_key}"
if _spacing_mode_key in st.session_state:
    st.session_state.strat_spacing_mode = st.session_state[_spacing_mode_key]
    st.session_state.strat_is_percent = (st.session_state.strat_spacing_mode == "Percentage (%)")

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

curr_sp_mode = st.session_state.get("strat_spacing_mode", "Percentage (%)")
if curr_sp_mode == "Percentage (%)":
    if f"strat_gap_input_pct_{_sym_key}" in st.session_state:
        st.session_state.strat_gap = st.session_state[f"strat_gap_input_pct_{_sym_key}"]
    if f"strat_offset_input_pct_{_sym_key}" in st.session_state:
        st.session_state.strat_offset = st.session_state[f"strat_offset_input_pct_{_sym_key}"]
elif curr_sp_mode == "Pips":
    if f"strat_gap_input_pip_{_sym_key}" in st.session_state:
        st.session_state.strat_gap = st.session_state[f"strat_gap_input_pip_{_sym_key}"]
    if f"strat_offset_input_pip_{_sym_key}" in st.session_state:
        st.session_state.strat_offset = st.session_state[f"strat_offset_input_pip_{_sym_key}"]
else:  # USD Points ($)
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
    getattr(bot, "spacing_mode", "Percentage (%)") != st.session_state.strat_spacing_mode or
    bot.order_size != st.session_state.strat_order_size or
    bot.order_size_multiplier != st.session_state.strat_size_multiplier
)

# Apply settings to the bot instance
bot.grid_levels = int(st.session_state.get("strat_grid_levels", 5))
bot.grid_gap = st.session_state.strat_gap
bot.trap_offset = st.session_state.strat_offset
bot.auto_restart = True
bot.spacing_mode = st.session_state.strat_spacing_mode
bot.max_cycle_duration = float('inf')
bot.cancel_opposite_on_trigger = st.session_state.get(f"toggle_oco_{st.session_state.live_symbol}", getattr(bot, "cancel_opposite_on_trigger", False))
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
_auto_markets_count = sum(1 for m in st.session_state.markets.values() if m.get("running", False) and m.get("bot") and getattr(m.get("bot"), "use_auto_reading", False))

_broker_type_hdr = "Simulated Sandbox" if isinstance(st.session_state.broker, SimulatedBroker) else "MT5 Live"
_broker_color = "#3b82f6" if _broker_type_hdr == "Simulated Sandbox" else "#f59e0b"
_running_dot = '<span class="pulse-dot"></span>' if _active_markets_count > 0 else '<span class="idle-dot"></span>'
_auto_badge_html = f'&nbsp;&nbsp;<span style="font-size:0.72rem; background: rgba(34, 197, 94, 0.18); border: 1px solid rgba(34, 197, 94, 0.4); color: #22c55e; padding: 2px 8px; border-radius: 6px; font-weight: 700;">🤖 {_auto_markets_count} AUTO</span>' if _auto_markets_count > 0 else ''

_hdr_html = (
    f'<div class="brand-container">'
    f'<div class="brand-logo">◆ PROFITY <span>AI</span></div>'
    f'<div class="brand-meta">'
    f'{_running_dot}'
    f'<span style="font-weight:600;color:{"var(--green)" if _active_markets_count > 0 else "var(--text-dim)"}">{_active_markets_count} RUNNING</span>'
    f'{_auto_badge_html}'
    f'&nbsp;&nbsp;·&nbsp;&nbsp;'
    f'<span class="brand-badge" style="background:{_broker_color}18;color:{_broker_color};border:1px solid {_broker_color}33;">{_broker_type_hdr}</span>'
    f'&nbsp;&nbsp;·&nbsp;&nbsp;'
    f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;color:var(--text-muted);">{_now_str}</span>'
    f'</div>'
    f'</div>'
)
st.markdown(_hdr_html, unsafe_allow_html=True)

# 7. MAIN 2-COLUMN WORKSTATION LAYOUT
col_left, col_right = st.columns([1.0, 1.35], gap="large")

with col_left:
    _sym_wk = st.session_state.get("live_symbol", "BTCUSDT")
    st.markdown('<div class="control-title">🎮 Execution & Market Controls</div>', unsafe_allow_html=True)
    
    # 🔑 COMMERCIAL LICENSE & SAAS SUBSCRIPTION PORTAL
    with st.expander("🔑 COMMERCIAL LICENSE & SAAS PORTAL", expanded=False):
        curr_key = st.session_state.get("saas_license_key", "")
        lic_mgr = LicenseManager(curr_key, getattr(st.session_state.get("broker"), "login", ""))
        lic_info = lic_mgr.validate()
        
        l_tier = lic_info["tier"]
        tier_badge = "🏆 PROP FIRM EDITION" if l_tier == LicenseTier.PROP_FIRM else ("🚀 PRO TRADER" if l_tier == LicenseTier.PRO else "🆓 FREE DEMO SANDBOX")
        tier_color = "#f59e0b" if l_tier == LicenseTier.PROP_FIRM else ("#22c55e" if l_tier == LicenseTier.PRO else "#a1a1aa")
        
        st.markdown(f"""
        <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 0.72rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">Active Subscription Tier</div>
                <div style="font-size: 1.05rem; font-weight: 800; color: {tier_color};">{tier_badge}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 0.72rem; color: var(--text-muted);">Status</div>
                <div style="font-size: 0.85rem; font-weight: 700; color: {'#22c55e' if lic_info['valid'] else '#ef4444'};">{lic_info['message']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        input_key = st.text_input("Enter SaaS License Key", value=curr_key, type="password", key=f"saas_key_input_{_sym_wk}")
        if input_key != curr_key:
            st.session_state.saas_license_key = input_key
            st.toast("Updated license key!")
            st.rerun()
            
        with st.expander("🛠️ Key Generator (SaaS Admin Only)", expanded=False):
            gen_col1, gen_col2 = st.columns(2)
            with gen_col1:
                gen_tier = st.selectbox("Tier", ["PROP", "PRO", "FREE"], key=f"gen_tier_{_sym_wk}")
            with gen_col2:
                gen_days = st.number_input("Validity (Days)", min_value=1, max_value=365, value=30, key=f"gen_days_{_sym_wk}")
            if st.button("🔑 GENERATE KEY", use_container_width=True, key=f"gen_key_btn_{_sym_wk}"):
                new_k = lic_mgr.generate_key(gen_tier, str(getattr(st.session_state.get("broker"), "login", "")), int(gen_days))
                st.code(new_k, language="text")
                st.toast("Generated new license key!")
    
    # --- SECTION A: MARKET SELECTORS (3 COLUMNS) ---
    sel_col1, sel_col2, sel_col3 = st.columns([4, 4, 4])
    
    with sel_col1:
        base_market_map = {
            "BTCUSDT": "BTCUSDT (Bitcoin)",
            "ETHUSDT": "ETHUSDT (Ethereum)",
            "SOLUSDT": "SOLUSDT (Solana)",
            "BNBUSDT": "BNBUSDT (Binance Coin)",
            "DOGEUSDT": "DOGEUSDT (Dogecoin)",
            "PAXGUSDT": "XAUUSD (Gold)"
        }
        
        market_options = {}
        market_reverse_map = {}
        for sym_code, base_lbl in base_market_map.items():
            m_state = st.session_state.get("markets", {}).get(sym_code, {})
            is_run = m_state.get("running", False)
            is_auto = m_state.get("bot") and getattr(m_state.get("bot"), "use_auto_reading", False)
            
            tags = []
            if is_run:
                tags.append("▶ RUNNING")
            if is_auto:
                tags.append("🤖 AUTO")
            
            tag_str = f"  [{' · '.join(tags)}]" if tags else ""
            display_label = f"{base_lbl}{tag_str}"
            
            market_options[display_label] = sym_code
            market_reverse_map[sym_code] = display_label
        
        current_sym = st.session_state.get("live_symbol", "BTCUSDT")
        current_disp_label = market_reverse_map.get(current_sym, "BTCUSDT (Bitcoin)")
        opt_keys = list(market_options.keys())
        default_idx = opt_keys.index(current_disp_label) if current_disp_label in opt_keys else 0
                
        selected_label = st.selectbox(
            "Market / Symbol",
            opt_keys,
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
    _sym_wk = st.session_state.live_symbol
    _active_label = _sym_short.get(st.session_state.live_symbol, st.session_state.live_symbol)

    _curr_m_state = st.session_state.markets.get(st.session_state.live_symbol, {})
    _curr_bot = _curr_m_state.get("bot")
    _is_auto_active = getattr(_curr_bot, "use_auto_reading", False) and st.session_state.get("strat_use_auto_reading", False)
    _is_manual_running = st.session_state.get("running", False) and not _is_auto_active

    # --- SECTION B: CONSOLIDATED MASTER CONTROL DESK (3 ROWS x 3 COLUMNS) ---
    st.markdown('<div class="control-title" style="margin-top: 10px;">🎛️ MASTER CONTROL DESK</div>', unsafe_allow_html=True)
    if _is_auto_active:
        st.markdown('<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:6px 12px;font-size:0.74rem;color:#22c55e;margin-bottom:6px;">🤖 <strong>AUTO TRADING IS ON</strong> — Manual controls are locked. Click AUTO TRADING button to switch to Manual Mode.</div>', unsafe_allow_html=True)
    elif _is_manual_running:
        st.markdown('<div style="background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.3);border-radius:8px;padding:6px 12px;font-size:0.74rem;color:#3b82f6;margin-bottom:6px;">▶ <strong>MANUAL BOT RUNNING</strong> — Auto Trading is locked. Pause the bot first to switch to Auto Mode.</div>', unsafe_allow_html=True)

    # ROW 1: PRIMARY EXECUTION & TRAP DEPLOYMENT
    cmd_r1_c1, cmd_r1_c2, cmd_r1_c3 = st.columns(3)
    
    with cmd_r1_c1:
        if not st.session_state.get("running", False):
            _start_lbl = "🔒 AUTO ACTIVE" if _is_auto_active else "▶ START BOT"
            if st.button(_start_lbl, type="primary", disabled=_is_auto_active, help="Start manual bot (disabled when Auto Trading is ON)", use_container_width=True, key=f"mcd_start_bot_{_sym_wk}"):
                # Switching to Manual: ensure Auto is OFF first
                if _curr_bot:
                    _curr_bot.use_auto_reading = False
                st.session_state.strat_use_auto_reading = False
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
                    curr_price = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
                    if not curr_price or curr_price == 0:
                        curr_price = get_default_price(st.session_state.live_symbol)

                    try:
                        st.session_state.broker.close_all_positions(curr_price, time.time())
                        st.session_state.broker.cancel_all_orders()
                    except Exception as e:
                        print(f"Startup cleanup notice: {e}")

                    try:
                        st.session_state.bot.deploy_traps(curr_price, time.time())
                        st.toast(f"🚀 Started {_active_label} & deployed grid traps at ${curr_price:,.2f}")
                    except Exception as dep_err:
                        print(f"Startup deploy_traps error: {dep_err}")
                        st.toast(f"⚠️ Bot started for {_active_label}, deploying grid on first tick...")

                    st.session_state.running = True
                    if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
                        st.session_state.markets[st.session_state.live_symbol]["running"] = True
                
                sync_active_market_primitives()
                save_bot_state()
                st.rerun()
        else:
            _pause_lbl = "🔒 AUTO ACTIVE" if _is_auto_active else "⏸ PAUSE BOT"
            if st.button(_pause_lbl, type="secondary", disabled=_is_auto_active, help="Pause manual bot (disabled when Auto Trading is ON)", use_container_width=True, key=f"mcd_pause_bot_{_sym_wk}"):
                st.session_state.running = False
                if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
                    st.session_state.markets[st.session_state.live_symbol]["running"] = False
                sync_active_market_primitives()
                save_bot_state()
                st.rerun()

    with cmd_r1_c2:
        _dep_btn_lbl = "🔒 AUTO-MANAGED" if _is_auto_active else "🎯 DEPLOY TRAPS"
        if st.button(_dep_btn_lbl, type="secondary", disabled=_is_auto_active, help="Deploy grid traps manually (disabled when Auto Trading is ON)", use_container_width=True, key=f"mcd_deploy_traps_{_sym_wk}"):
            curr_m = st.session_state.markets.get(st.session_state.live_symbol)
            if curr_m:
                bt = curr_m["bot"]
                curr_p = (
                    (curr_m["price_history"][-1][1] if curr_m.get("price_history") else None)
                    or curr_m.get("last_price")
                    or get_default_price(st.session_state.live_symbol)
                )
                bt.deploy_traps(curr_p, time.time())
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"🎯 Deployed grid traps for {_active_label} at ${curr_p:,.2f}")
                st.rerun()

    with cmd_r1_c3:
        _rec_btn_lbl = "🔒 AUTO-MANAGED" if _is_auto_active else "🔄 RECENTER TRAPS"
        if st.button(_rec_btn_lbl, type="secondary", disabled=_is_auto_active, help="Recenter grid traps manually (disabled when Auto Trading is ON)", use_container_width=True, key=f"mcd_recenter_traps_{_sym_wk}"):
            curr_m = st.session_state.markets.get(st.session_state.live_symbol)
            if curr_m:
                bt = curr_m["bot"]
                curr_p = (
                    (curr_m["price_history"][-1][1] if curr_m.get("price_history") else None)
                    or curr_m.get("last_price")
                    or get_default_price(st.session_state.live_symbol)
                )
                bt.deploy_traps(curr_p, time.time())
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"🔄 Recentered grid traps around ${curr_p:,.2f}")
                st.rerun()

    # ROW 2: GRID MAINTENANCE & PRESETS
    cmd_r2_c1, cmd_r2_c2, cmd_r2_c3 = st.columns(3)

    with cmd_r2_c1:
        if st.button("🔧 REPAIR GRID", type="secondary", help=f"Clean duplicates & restore missing trap levels for {_active_label}", use_container_width=True, key=f"mcd_repair_grid_{_sym_wk}"):
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

    with cmd_r2_c2:
        if st.button("🧹 CLEAN UP", type="secondary", help=f"Remove duplicate & orphan pending orders for {_active_label}", use_container_width=True, key=f"mcd_cleanup_grid_{_sym_wk}"):
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

    _curr_m_state = st.session_state.markets.get(st.session_state.live_symbol, {})
    _curr_bot = _curr_m_state.get("bot")
    _is_auto_active = getattr(_curr_bot, "use_auto_reading", False) and st.session_state.get("strat_use_auto_reading", False)
    _is_manual_running = st.session_state.get("running", False) and not _is_auto_active
    
    # Auto button is locked if manual bot is actively running
    _auto_btn_disabled = _is_manual_running
    if _is_auto_active:
        _mcd_auto_btn_lbl = "🟢 AUTO TRADING: ON (CLICK TO STOP)"
    elif _is_manual_running:
        _mcd_auto_btn_lbl = "🔒 MANUAL BOT RUNNING"
    else:
        _mcd_auto_btn_lbl = "🔴 AUTO TRADING: OFF (CLICK TO START)"
    
    with cmd_r2_c3:
        if st.button(_mcd_auto_btn_lbl, type="primary" if _is_auto_active else "secondary", disabled=_auto_btn_disabled, help="Toggle Auto Trading Mode ON/OFF. Disabled when Manual Bot is running — pause it first.", use_container_width=True, key=f"mcd_defaults_{_sym_wk}"):
            _cur_sym = st.session_state.live_symbol
            _cur_price = float(st.session_state.get("last_price", 1000.0))
            
            if _is_auto_active:
                # TOGGLE OFF AUTO TRADING MODE
                st.session_state.strat_use_auto_reading = False
                if _curr_bot:
                    _curr_bot.use_auto_reading = False
                _curr_m_state["running"] = False
                st.session_state.running = False
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"🔴 Auto Trading Mode STOPPED (OFF) for {_active_label}!")
                st.rerun()
            else:
                # TOGGLE ON AUTO TRADING MODE
                # Use TOTAL equity across ALL market brokers so every symbol
                # gets the same capital tier — ETH and Gold on $1,000 both → Golden (5 levels)
                _acc_bal = sum(
                    float(getattr(m.get("broker"), "balance", 0.0))
                    for m in st.session_state.markets.values()
                    if m.get("broker")
                ) or float(getattr(st.session_state.broker, "balance", 1000.0))
                _klines_df = get_historical_klines(_cur_sym, interval="1m", limit=100)
                _tech = calculate_technical_indicators(_klines_df)
                _ob = get_order_book_depth(_cur_sym)
                _news = get_economic_calendar()

                from core.engine import AutoReadingEngine
                _are = AutoReadingEngine()
                _eval_res = _are.evaluate_market_and_account(
                    symbol=_cur_sym,
                    current_price=_cur_price,
                    account_equity=_acc_bal,
                    tech_indicators=_tech,
                    orderbook_depth=_ob,
                    macro_news=_news
                )
                
                st.session_state.strat_use_auto_reading = True
                st.session_state.strat_offset = _eval_res["buy_offset_pct"]
                st.session_state.strat_gap = _eval_res["dynamic_gap_pct"]
                st.session_state.strat_is_percent = True
                st.session_state.strat_order_size = _eval_res["recommended_size"]
                st.session_state.strat_size_multiplier = _eval_res["recommended_multiplier"]
                st.session_state.strat_sl = _eval_res["recommended_stop_loss"]

                if _curr_bot:
                    _curr_bot.use_auto_reading = True
                    try:
                        _curr_bot.deploy_traps(_cur_price, time.time())
                    except Exception as dep_err:
                        print(f"Auto Trading deploy notice: {dep_err}")

                _curr_m_state["running"] = True
                st.session_state.running = True
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"🟢 Activated Auto Trading Mode (STARTED) for {_active_label}!")
                st.rerun()

    # ROW 3: SAFETY, EMERGENCY CLOSE & ENVIRONMENT RESET ACTIONS
    cmd_r3_c1, cmd_r3_c2, cmd_r3_c3 = st.columns(3)

    with cmd_r3_c1:
        if st.button(f"🚨 CLOSE {_active_label}", type="secondary", help=f"Emergency close trades & traps for {_active_label} only", use_container_width=True, key=f"mcd_close_pair_{_sym_wk}"):
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

    with cmd_r3_c2:
        if st.button("⚡ PANIC ALL", type="secondary", help="Global emergency stop across all market pairs", use_container_width=True, key=f"mcd_panic_all_{_sym_wk}"):
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

    with cmd_r3_c3:
        if st.button("🔄 RESET", type="secondary", help="Reset simulated sandbox state", use_container_width=True, key=f"mcd_reset_sandbox_{_sym_wk}"):
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

    _strat_sym_label = {"BTCUSDT":"BTC","ETHUSDT":"ETH","SOLUSDT":"SOL","BNBUSDT":"BNB","DOGEUSDT":"DOGE","PAXGUSDT":"XAU"}.get(st.session_state.live_symbol, st.session_state.live_symbol)
    
    st_header_col1, st_header_col2 = st.columns([1.2, 1.8])
    with st_header_col1:
        st.markdown(f'<div class="control-title">🎯 Strategy Tuning &nbsp;<span style="font-size:0.7rem;font-weight:400;opacity:0.55;border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:1px 7px;">for {_strat_sym_label}</span></div>', unsafe_allow_html=True)
    with st_header_col2:
        btn_c1, btn_c2 = st.columns(2)
        _is_auto_on = st.session_state.get("strat_use_auto_reading", True)
        _auto_tune_lbl = f"🟢 AUTO-TRADING (ACTIVE ON)" if _is_auto_on else f"⚡ AUTO-TUNE (AUTO)"
        with btn_c1:
            if st.button(_auto_tune_lbl, type="primary" if _is_auto_on else "secondary", help=f"Dynamically calculate and apply Auto-Reading preset for {_strat_sym_label}", use_container_width=True, key=f"strat_auto_btn_{_sym_wk}"):
                _cur_sym = st.session_state.live_symbol
                _cur_price = float(st.session_state.get("last_price", 1000.0))
                _acc_bal = float(getattr(st.session_state.broker, "balance", 1000.0))
                _klines_df = get_historical_klines(_cur_sym, interval="1m", limit=100)
                _tech = calculate_technical_indicators(_klines_df)
                _ob = get_order_book_depth(_cur_sym)
                _news = get_economic_calendar()

                from core.engine import AutoReadingEngine
                _are = AutoReadingEngine()
                _eval_res = _are.evaluate_market_and_account(
                    symbol=_cur_sym,
                    current_price=_cur_price,
                    account_equity=_acc_bal,
                    tech_indicators=_tech,
                    orderbook_depth=_ob,
                    macro_news=_news
                )
                
                st.session_state.strat_offset = _eval_res["buy_offset_pct"]
                st.session_state.strat_gap = _eval_res["dynamic_gap_pct"]
                st.session_state.strat_is_percent = True
                st.session_state.strat_order_size = _eval_res["recommended_size"]
                st.session_state.strat_size_multiplier = _eval_res["recommended_multiplier"]
                st.session_state.strat_sl = _eval_res["recommended_stop_loss"]
                st.session_state.strat_use_auto_reading = True
                if hasattr(st.session_state, "bot") and st.session_state.bot:
                    st.session_state.bot.use_auto_reading = True

                _sym_wk_reset = st.session_state.live_symbol
                _strat_widget_keys = [
                    f"strat_is_percent_select_{_sym_wk_reset}",
                    f"strat_offset_input_pct_{_sym_wk_reset}", f"strat_offset_input_usd_{_sym_wk_reset}",
                    f"strat_gap_input_pct_{_sym_wk_reset}",    f"strat_gap_input_usd_{_sym_wk_reset}",
                    f"strat_target_profit_input_{_sym_wk_reset}", f"strat_sl_input_{_sym_wk_reset}",
                    f"strat_order_size_input_{_sym_wk_reset}", f"strat_size_multiplier_input_{_sym_wk_reset}",
                    f"strat_use_auto_reading_input_{_sym_wk_reset}"
                ]
                for _k in _strat_widget_keys:
                    st.session_state.pop(_k, None)
                    
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"⚡ {_strat_sym_label}: Applied Autonomous Auto-Reading preset!")
                st.rerun()

        with btn_c2:
            if st.button(f"⭐ GOLDEN (MANUAL)", type="secondary", help=f"Reset strategy parameters for {_strat_sym_label} to Golden Settings defaults for manual tuning", use_container_width=True, key=f"strat_defaults_btn_{_sym_wk}"):
                gs = get_coin_golden_settings(st.session_state.live_symbol)
                st.session_state.strat_offset = gs["offset"]
                st.session_state.strat_gap = gs["gap"]
                st.session_state.strat_is_percent = True
                st.session_state.strat_order_size = gs["order_size"]
                st.session_state.strat_size_multiplier = gs["multiplier"]
                st.session_state.strat_target_profit = gs["target_profit"]
                st.session_state.strat_sl = gs["stop_loss"]
                st.session_state.strat_use_auto_reading = False
                if hasattr(st.session_state, "bot") and st.session_state.bot:
                    st.session_state.bot.use_auto_reading = False
                
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
                    f"strat_use_auto_reading_input_{_sym_wk_reset}"
                ]
                for _k in _strat_widget_keys:
                    st.session_state.pop(_k, None)
                    
                sync_active_market_primitives()
                save_bot_state()
                st.toast(f"Reset strategy settings for {_strat_sym_label} to Golden Defaults (Manual Mode).")
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

    if st.session_state.get("strat_use_auto_reading", True):
        # Calculate real-time auto-reading metrics for UI display
        _cur_sym = st.session_state.live_symbol
        _cur_price = float(st.session_state.get("last_price", 1000.0))
        _acc_bal = float(getattr(st.session_state.broker, "balance", 1000.0))
        
        _klines_df = get_historical_klines(_cur_sym, interval="1m", limit=100)
        _tech = calculate_technical_indicators(_klines_df)
        _ob = get_order_book_depth(_cur_sym)
        _news = get_economic_calendar()

        from core.engine import AutoReadingEngine
        _are = AutoReadingEngine()
        _eval_res = _are.evaluate_market_and_account(
            symbol=_cur_sym,
            current_price=_cur_price,
            account_equity=_acc_bal,
            tech_indicators=_tech,
            orderbook_depth=_ob,
            macro_news=_news
        )
        
        _bias_val = _eval_res["ema_trend_bias"]
        _bias_lbl = "STRONG BULL 🚀" if _bias_val > 0.4 else ("BULLISH 📈" if _bias_val > 0.1 else ("STRONG BEAR 📉" if _bias_val < -0.4 else ("BEARISH 📉" if _bias_val < -0.1 else "NEUTRAL ⚖️")))
        _bias_color = "#22c55e" if _bias_val > 0.1 else ("#ef4444" if _bias_val < -0.1 else "#f59e0b")
        
        _ob_delta = _eval_res["ob_delta"] * 100.0
        _ob_src = _ob.get("source", "Live Depth")
        _news_lbl = "⚠️ ACTIVE (2.5x Expansion)" if _eval_res["news_risk_mult"] > 1.0 else "🛡️ CLEAR (1.0x Normal)"
        _news_color = "#ef4444" if _eval_res["news_risk_mult"] > 1.0 else "#22c55e"

        _bo_score = _tech.get("breakout_score", 50)
        _squeeze = "SQUEEZE ACTIVE ⚡" if _tech.get("is_bb_squeeze", False) else "NORMAL VOL"
        _supp = _ob.get("support_wall", 0.0)
        _resis = _ob.get("resistance_wall", 0.0)
        _vwap_dev = _eval_res.get("vwap_dev_pct", 0.0)
        _vwap_lbl = f"ABOVE VWAP ({_vwap_dev:+.2f}%) 🟢" if _vwap_dev >= 0.0 else f"BELOW VWAP ({_vwap_dev:+.2f}%) 🔴"
        _vwap_color = "#22c55e" if _vwap_dev >= 0.0 else "#ef4444"

        _diag_html = (
            f'<div style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.25); border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; font-size: 0.8rem;">'
            f'<div style="color: #60a5fa; font-weight: 700; margin-bottom: 8px; font-size: 0.88rem; display: flex; align-items: center; justify-content: space-between;">'
            f'<span>🤖 AUTO-READING LIVE MARKET REGIME & ACCOUNT DIAGNOSTICS &nbsp;&nbsp;<span style="font-size:0.72rem; background: rgba(34, 197, 94, 0.2); border: 1px solid rgba(34, 197, 94, 0.45); color: #22c55e; padding: 2px 8px; border-radius: 6px; font-weight: 700;">🟢 AUTO-TRADING ACTIVE</span></span>'
            f'<span style="font-size:0.75rem; background: rgba(59, 130, 246, 0.2); border: 1px solid rgba(59, 130, 246, 0.4); padding: 3px 10px; border-radius: 6px; font-weight: 600;">Account Safety Tier: {_eval_res["capital_tier"]} (Max {_eval_res["recommended_levels"]} Levels @ {_eval_res["recommended_multiplier"]}x)</span>'
            f'</div>'
            f'<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px 14px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); color: var(--text);">'
            f'<div><strong>EMA 20/50/200 Bias:</strong> <span style="color: {_bias_color}; font-weight: 700;">{_bias_val:+.2f} ({_bias_lbl})</span></div>'
            f'<div><strong>VWAP Anchor:</strong> <span style="color: {_vwap_color}; font-weight: 700;">{_vwap_lbl}</span></div>'
            f'<div><strong>Orderbook Imbalance:</strong> <span style="font-weight: 700;">{_ob_delta:+.1f}%</span> <span style="font-size:0.7rem; opacity:0.6;">({_ob_src})</span></div>'
            f'<div><strong>News Risk Shield:</strong> <span style="color: {_news_color}; font-weight: 700;">{_news_lbl}</span></div>'
            f'</div>'
            f'<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px 14px; color: var(--text);">'
            f'<div><strong>Auto Rec. Offsets:</strong> <span style="color: #22c55e; font-weight: 700;">Buy {_eval_res["buy_offset_pct"]}%</span> / <span style="color: #ef4444; font-weight: 700;">Sell {_eval_res["sell_offset_pct"]}%</span></div>'
            f'<div><strong>Auto Dynamic Gap:</strong> <span style="font-weight: 700;">{_eval_res["dynamic_gap_pct"]}%</span></div>'
            f'<div><strong>Auto Scaled Base Size:</strong> <span style="font-weight: 700;">{_eval_res["recommended_size"]} Lots</span></div>'
            f'<div><strong>Protection Shield:</strong> <span style="font-size:0.75rem; color:#22c55e; font-weight:700;">2-Fill Breakeven Lock 🛡️</span></div>'
            f'</div>'
            f'</div>'
        )
        st.markdown(_diag_html, unsafe_allow_html=True)

    _sym_wk = st.session_state.live_symbol  # widget key namespace for this coin
    _auto_hlp = "🔒 Managed automatically by Auto-Trading Engine" if _is_auto_active else "Manual strategy parameter"
    
    strat_col1, strat_col2, strat_col3 = st.columns(3)
    with strat_col1:
        # Spacing Mode selectbox with 3 distinct modes: Percentage (%), USD Points ($), and Pips
        sp_options = ["Percentage (%)", "USD Points ($)", "Pips"]
        curr_sp_mode = st.session_state.get("strat_spacing_mode", "Percentage (%)")
        sp_idx = sp_options.index(curr_sp_mode) if curr_sp_mode in sp_options else 0

        spacing_mode = st.selectbox(
            "Spacing Mode",
            sp_options,
            index=sp_idx,
            key=f"strat_spacing_mode_select_{_sym_wk}"
        )
        st.session_state.strat_spacing_mode = spacing_mode
        st.session_state.strat_is_percent = (spacing_mode == "Percentage (%)")
        
        # Determine labels, bounds, and step sizes based on spacing mode
        if spacing_mode == "Percentage (%)":
            offset_label = "Trap Offset (%)"
            offset_min, offset_max, offset_step = 0.01, 5.0, 0.01
            gap_label = "Grid Gap (%)"
            gap_min, gap_max, gap_step = 0.01, 5.0, 0.01
            default_offset = st.session_state.strat_offset if st.session_state.strat_offset <= 5.0 else 0.15
            default_gap = st.session_state.strat_gap if st.session_state.strat_gap <= 5.0 else 0.10
            key_suffix = "pct"
        elif spacing_mode == "Pips":
            offset_label = "Trap Offset (Pips)"
            offset_min, offset_max, offset_step = 0.5, 50000.0, 1.0
            gap_label = "Grid Gap (Pips)"
            gap_min, gap_max, gap_step = 0.5, 50000.0, 1.0
            pip_sz = get_pip_size(_sym_wk, float(st.session_state.last_price))
            if st.session_state.strat_offset < 1.0 and pip_sz > 0:
                default_offset = max(1.0, round((st.session_state.last_price * (st.session_state.strat_offset / 100.0)) / pip_sz, 1))
                default_gap = max(1.0, round((st.session_state.last_price * (st.session_state.strat_gap / 100.0)) / pip_sz, 1))
            else:
                default_offset = st.session_state.strat_offset
                default_gap = st.session_state.strat_gap
            key_suffix = "pip"
        else:  # USD Points ($)
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
            key_suffix = "usd"

        trap_offset_val = st.number_input(
            offset_label,
            min_value=offset_min,
            max_value=offset_max,
            value=default_offset,
            step=offset_step,
            format="%.2f" if key_suffix == "pct" or default_offset % 1 != 0 else "%.1f",
            disabled=_is_auto_active,
            help=_auto_hlp,
            key=f"strat_offset_input_{key_suffix}_{_sym_wk}"
        )
        st.session_state.strat_offset = trap_offset_val
        
        grid_gap_val = st.number_input(
            gap_label,
            min_value=gap_min,
            max_value=gap_max,
            value=default_gap,
            step=gap_step,
            format="%.2f" if key_suffix == "pct" or default_gap % 1 != 0 else "%.1f",
            disabled=_is_auto_active,
            help=_auto_hlp,
            key=f"strat_gap_input_{key_suffix}_{_sym_wk}"
        )
        st.session_state.strat_gap = grid_gap_val

        grid_levels_val = st.number_input(
            "Grid Levels per Side",
            min_value=1,
            max_value=30,
            value=int(st.session_state.get("strat_grid_levels", 10)),
            step=1,
            disabled=_is_auto_active,
            help="Number of pending stop orders placed per side (e.g. 10 = 10 BUY_STOP + 10 SELL_STOP = 20 total orders). Managed by Auto-Trading when active.",
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
            disabled=_is_auto_active,
            help=_auto_hlp,
            key=f"strat_target_profit_input_{_sym_wk}"
        )
        st.session_state.strat_target_profit = target_profit_val

        sl_val = st.number_input(
            "Stop Loss (USD)",
            min_value=5.0,
            max_value=100000.0,
            value=float(st.session_state.get("strat_sl", 150.0)),
            step=10.0,
            disabled=_is_auto_active,
            help=_auto_hlp,
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

        auto_reading_val = st.toggle(
            "🤖 Enable Auto-Reading Autonomous Mode",
            value=st.session_state.get("strat_use_auto_reading", True),
            help="Automates trap setting using live EMA 20/50/200 trend bias, multi-exchange orderbook volume delta (Gate/OKX/Bybit/Binance), ATR volatility, news events, and account capital scaling ($100 to $10,000+).",
            key=f"strat_use_auto_reading_input_{_sym_wk}"
        )
        st.session_state.strat_use_auto_reading = auto_reading_val
        if hasattr(st.session_state, "bot") and st.session_state.bot:
            st.session_state.bot.use_auto_reading = auto_reading_val
        
    with strat_col3:
        order_size_val = st.number_input(
            "Base Order Size (Quantity)",
            min_value=0.00001,
            max_value=1000000.0,
            value=float(st.session_state.strat_order_size),
            step=0.0001 if st.session_state.strat_order_size < 0.1 else (0.01 if st.session_state.strat_order_size < 10.0 else 1.0),
            format="%.5f" if st.session_state.strat_order_size < 1.0 else ("%.2f" if st.session_state.strat_order_size < 100.0 else "%.1f"),
            disabled=_is_auto_active,
            help=_auto_hlp,
            key=f"strat_order_size_input_{_sym_wk}"
        )
        st.session_state.strat_order_size = order_size_val

        size_mult_val = st.number_input(
            "Size Multiplier (Martingale)",
            min_value=1.0,
            max_value=5.0,
            value=float(st.session_state.strat_size_multiplier),
            step=0.1,
            format="%.2f" if st.session_state.strat_size_multiplier % 0.1 != 0 else "%.1f",
            disabled=_is_auto_active,
            help=_auto_hlp,
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

    # 🎛️ MASTER CONTROL & MANUAL OVERRIDE HUB
    with st.expander("🎛️ MASTER CONTROL & SYSTEM MODULE SWITCHES (ON / OFF)", expanded=True):
        st.markdown(
            f'<div style="font-size:0.78rem; color:var(--text-muted); margin-bottom:10px;">'
            f'100% full manual toggle access over every individual system module for <strong>{_strat_sym_label}</strong>.'
            f'</div>',
            unsafe_allow_html=True
        )
        ctrl_col1, ctrl_col2 = st.columns(2)
        
        with ctrl_col1:
            auto_restart_toggle = st.toggle(
                "🤖 Auto-Restart Strategy",
                value=getattr(st.session_state.bot, "auto_restart", True),
                key=f"toggle_auto_restart_{_sym_wk}"
            )
            st.session_state.bot.auto_restart = auto_restart_toggle
            
            grid_repair_toggle = st.toggle(
                "🧹 Dynamic Grid Repair Engine",
                value=getattr(st.session_state.bot, "use_grid_repair", True),
                key=f"toggle_grid_repair_{_sym_wk}"
            )
            st.session_state.bot.use_grid_repair = grid_repair_toggle

            oco_toggle = st.toggle(
                "⚖️ OCO Opposite Cancel Mode",
                value=getattr(st.session_state.bot, "cancel_opposite_on_trigger", False),
                key=f"toggle_oco_{_sym_wk}"
            )
            st.session_state.bot.cancel_opposite_on_trigger = oco_toggle

        with ctrl_col2:
            news_shield_toggle = st.toggle(
                "📰 High-Impact News Shield",
                value=getattr(st.session_state.bot, "use_news_shield", False),
                help="Automatically pauses grid deployments when high-impact macro news is released.",
                key=f"toggle_news_shield_{_sym_wk}"
            )
            st.session_state.bot.use_news_shield = news_shield_toggle

            bb_filter_toggle = st.toggle(
                "⚡ Bollinger Squeeze Filter",
                value=getattr(st.session_state.bot, "use_bb_filter", False),
                key=f"toggle_bb_filter_{_sym_wk}"
            )
            st.session_state.bot.use_bb_filter = bb_filter_toggle

            _default_weekend = ("PAXG" in _sym_wk.upper() or "XAU" in _sym_wk.upper())
            weekend_toggle = st.toggle(
                "🗓️ Friday Weekend Protection",
                value=getattr(st.session_state.bot, "use_weekend_shutdown", _default_weekend),
                help="Cancels pending grid traps on Friday evening before market close (Gold XAUUSD & Forex) to eliminate weekend gap risk. Position profiting closes; loss positions hold safely under Stop Loss cap.",
                key=f"toggle_weekend_shutdown_{_sym_wk}"
            )
            st.session_state.bot.use_weekend_shutdown = weekend_toggle

            circuit_breaker_val = st.number_input(
                "🚨 Daily Max Loss Limit ($)",
                min_value=0.0,
                max_value=10000.0,
                value=float(getattr(st.session_state.bot, "max_daily_drawdown", 0.0)),
                step=10.0,
                help="0.0 disabled. Sets daily drawdown limit; if loss breaches this limit, trap deployment pauses.",
                key=f"input_daily_dd_{_sym_wk}"
            )
            st.session_state.bot.max_daily_drawdown = circuit_breaker_val



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
    _pnl = sum(p.get_pnl(_price_for_pnl) for p in _brk.open_positions.values()) if (_brk and hasattr(_brk, "open_positions") and _open_pos > 0) else 0.0
    _realized = getattr(_brk, "realized_pnl", 0.0) if _brk else 0.0
    _cur_live = st.session_state.get("live_symbol", "BTCUSDT")
    _is_active = (_s == _cur_live)
    _label = _sym_short.get(_s, _s)
    _is_auto_on = getattr(_m.get("bot"), "use_auto_reading", False)
    _is_running = _m.get("running", False)

    _pnl_txt = f"+${_pnl:.2f}" if _pnl >= 0 else f"-${abs(_pnl):.2f}"
    _border = "2px solid #f59e0b" if _is_active else "1px solid rgba(255,255,255,0.08)"
    _bg = "rgba(245,158,11,0.08)" if _is_active else "rgba(255,255,255,0.03)"

    if _is_running:
        _dot = "🟢"
        if _is_auto_on:
            _status_txt = " 🤖 AUTO ON"
        else:
            _status_txt = " ▶ RUNNING"
    elif _open_pos > 0:
        _dot = "🟡"
        _status_txt = " ⏸ PAUSED"
    else:
        _dot = "⚫"
        _status_txt = " IDLE"

    _status_chips.append(
        f'<div style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;'
        f'border-radius:8px;border:{_border};background:{_bg};margin:2px 4px 2px 0;'
        f'font-size:0.72rem;font-weight:500;white-space:nowrap;">'
        f'{_dot} <strong>{_label}</strong>'
        f'{_status_txt}'
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
    # Multi-tab concurrency safety: seamless session takeover on browser refresh
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    session_id = ctx.session_id if ctx else "default"
    
    now_t = time.time()
    GLOBAL_RUNNERS["primary_session"] = session_id
    GLOBAL_RUNNERS["last_heartbeat"] = now_t

    # Compute TOTAL account equity across ALL market brokers once
    # This is passed to all bots so ETH and Gold on the same account
    # get the SAME capital tier and grid level count (consistent Auto-Reading)
    _total_equity = sum(
        float(getattr(m.get("broker"), "balance", 0.0))
        for m in st.session_state.markets.values()
        if m.get("broker")
    ) or float(getattr(st.session_state.broker, "balance", 1000.0))

    # Process ticks for all running markets
    for sym, m_state in list(st.session_state.markets.items()):
        if not m_state.get("running", False):
            continue

        # Share total equity with bot so Auto-Reading uses same tier for all symbols
        _mbot = m_state.get("bot")
        if _mbot:
            _mbot.shared_account_equity = _total_equity

            
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
            _cur_live_sym = st.session_state.get("live_symbol", "BTCUSDT")
            if sym == _cur_live_sym:
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
                    "BREAKEVEN": "🛡️", "EARLY_RANGE_EXIT": "🛡️", "TIMEOUT": "⏱️"
                }.get(_reason, "📋")
                _label = {
                    "TARGET_PROFIT": "Target Profit hit", "RUNNER_EXPANSION": "Runner Profit!",
                    "STOP_LOSS": "Stop Loss hit", "TRAILING_STOP": "Trailing Stop hit",
                    "BREAKEVEN": "Breakeven exit", "EARLY_RANGE_EXIT": "Smart Early Range Exit", "TIMEOUT": "Cycle timeout"
                }.get(_reason, _reason)
                st.toast(f"{_icon} {sym} Cycle {cycle_hit['cycle_id']}: {_label}! PnL: ${cycle_hit['pnl']:+.2f}")
            if sym == _cur_live_sym:
                st.session_state.error_message = None
            m_state["consecutive_errors"] = 0
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
            if sym == st.session_state.get("live_symbol", "BTCUSDT"):
                st.session_state.running = False
                st.session_state.error_message = _tde_msg
            import pathlib
            _log_path = pathlib.Path(__file__).parent / "last_error.txt"
            with open(_log_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(f"TradeDisabledError for {sym}: {tde}")
        except Exception as e:
            import traceback
            err_cnt = m_state.get("consecutive_errors", 0) + 1
            m_state["consecutive_errors"] = err_cnt
            err_str = f"Tick processing notice ({err_cnt}/10) for {sym}: {e}"
            print(err_str)
            # Only pause after 10 consecutive ticks fail fatally to protect against transient network glitches
            if err_cnt >= 10:
                m_state["running"] = False
                if sym == st.session_state.get("live_symbol", "BTCUSDT"):
                    st.session_state.running = False
                    st.session_state.error_message = f"Tick processing paused for {sym} after 10 failures: {e}"
                import pathlib
                _log_path = pathlib.Path(__file__).parent / "last_error.txt"
                with open(_log_path, "w", encoding="utf-8", errors="replace") as f:
                    f.write(f"{err_str}\n{traceback.format_exc()}")
                
    save_bot_state()

# For symbols that are NOT running, we keep the active symbol price fresh on page load/interaction
if not st.session_state.get("running", False):
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

# MT5 Algo Trading Status Alert Banner
if getattr(broker_instance, "autotrading_disabled", False):
    st.error(
        "⚠️ **MT5 ALGO TRADING IS TURNED OFF IN METATRADER 5!**  \n"
        "Orders cannot be placed until you enable automated trading in MT5.  \n"
        "👉 **Action Required**: Click the green **'Algo Trading'** button at the top toolbar of your MT5 desktop application (or press **Ctrl + E**) to turn it ON."
    )

# Friday Weekend Market Shutdown Alert Banner
if getattr(bot_instance, "weekend_shutdown_triggered", False):
    st.warning(
        f"🗓️ **WEEKEND MARKET PROTECTION ACTIVE ({chart_coin_label})**  \n"
        f"Grid trap deployments and orders are safely paused over the weekend to protect against market closure gaps and spread spikes.  \n"
        f"🌅 **Auto-Resume**: Grid execution will automatically restart on Monday when markets reopen!"
    )

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

# RIGHT COLUMN: LIVE CHARTING, DATA TABLES & MARKET INTELLIGENCE DESK
with col_right:
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
            close="last",
            count="count"
        ).reset_index()
        ohlc["datetime"] = pd.to_datetime(ohlc["interval_id"], unit="s")
        ohlc_df = ohlc

    # Create 2-row subplot (Row 1: Price & Traps, Row 2: Volume Histogram)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.78, 0.22]
    )

    if not ohlc_df.empty:
        # 1. Bollinger Bands Volatility Cloud Calculation
        closes = ohlc_df["close"].values
        if len(closes) >= 5:
            period = min(20, len(closes))
            sma = ohlc_df["close"].rolling(window=period, min_periods=1).mean()
            std = ohlc_df["close"].rolling(window=period, min_periods=1).std().fillna(0.0)
            upper_b = sma + (2.0 * std)
            lower_b = sma - (2.0 * std)

            # Lower Band Line
            fig.add_trace(go.Scatter(
                x=ohlc_df["datetime"], y=lower_b,
                mode="lines",
                line=dict(color="rgba(59, 130, 246, 0.25)", width=1),
                name="BB Lower",
                showlegend=False
            ), row=1, col=1)

            # Upper Band Line with Shaded Volatility Cloud
            fig.add_trace(go.Scatter(
                x=ohlc_df["datetime"], y=upper_b,
                mode="lines",
                line=dict(color="rgba(59, 130, 246, 0.25)", width=1),
                fill="tonexty",
                fillcolor="rgba(59, 130, 246, 0.06)",
                name="BB Upper (Squeeze Cloud)",
                showlegend=False
            ), row=1, col=1)

            # SMA 20 Midline
            fig.add_trace(go.Scatter(
                x=ohlc_df["datetime"], y=sma,
                mode="lines",
                line=dict(color="rgba(59, 130, 246, 0.4)", width=1, dash="dot"),
                name="SMA 20",
                showlegend=False
            ), row=1, col=1)

        # 2. Main Price Candlesticks
        fig.add_trace(go.Candlestick(
            x=ohlc_df["datetime"],
            open=ohlc_df["open"],
            high=ohlc_df["high"],
            low=ohlc_df["low"],
            close=ohlc_df["close"],
            name=f"{display_symbol} Price",
            increasing_line_color="#22c55e",
            decreasing_line_color="#ef4444",
            increasing_fillcolor="rgba(34, 197, 94, 0.25)",
            decreasing_fillcolor="rgba(239, 68, 68, 0.25)"
        ), row=1, col=1)

        # 3. Volume Subplot Histogram
        vol_colors = ["rgba(34, 197, 94, 0.6)" if c >= o else "rgba(239, 68, 68, 0.6)" for c, o in zip(ohlc_df["close"], ohlc_df["open"])]
        fig.add_trace(go.Bar(
            x=ohlc_df["datetime"],
            y=ohlc_df["count"],
            marker_color=vol_colors,
            name="Volume (Ticks)",
            showlegend=False
        ), row=2, col=1)

    # Current price indicator line
    fig.add_hline(
        y=curr_price,
        line_dash="dot",
        line_color="#f59e0b",
        line_width=1.5,
        annotation_text=f"Live Spot: ${curr_price:.2f}",
        annotation_position="bottom right",
        annotation_font=dict(size=9, color="#f59e0b", weight="bold"),
        row=1, col=1
    )

    # Target Profit & Stop Loss Floor Lines
    if hasattr(bot_instance, "target_profit") and bot_instance.deploy_price > 0:
        tp_val = bot_instance.target_profit
        sl_val = getattr(bot_instance, "stop_loss", 0.0)
    
    # Trap levels lines
    if broker_instance.pending_orders:
        # Place buy/sell stops in chart
        for o in list(broker_instance.pending_orders.values()):
            if o.type == "BUY_STOP":
                line_color = "rgba(34, 197, 94, 0.55)" if IS_DARK else "rgba(22, 163, 74, 0.6)"
                fig.add_hline(
                    y=o.trigger_price,
                    line_dash="dash",
                    line_color=line_color,
                    annotation_text=f"BUY STOP ({fmt_size(o.size)}): ${o.trigger_price:.2f}",
                    annotation_position="top left",
                    annotation_font=dict(size=8, color=line_color),
                    row=1, col=1
                )
            elif o.type == "SELL_STOP":
                line_color = "rgba(239, 68, 68, 0.55)" if IS_DARK else "rgba(220, 38, 38, 0.6)"
                fig.add_hline(
                    y=o.trigger_price,
                    line_dash="dash",
                    line_color=line_color,
                    annotation_text=f"SELL STOP ({fmt_size(o.size)}): ${o.trigger_price:.2f}",
                    annotation_position="bottom left",
                    annotation_font=dict(size=8, color=line_color),
                    row=1, col=1
                )
    else:
        # Render proposed preview traps on chart before deployment to MT5
        preview_mode = st.session_state.get("strat_spacing_mode", "Percentage (%)")
        if preview_mode == "Pips":
            pip_sz = get_pip_size(st.session_state.live_symbol, curr_price)
            offset_val = st.session_state.strat_offset * pip_sz
            gap_val = st.session_state.strat_gap * pip_sz
        elif preview_mode == "Percentage (%)":
            offset_val = curr_price * (st.session_state.strat_offset / 100.0)
            gap_val = curr_price * (st.session_state.strat_gap / 100.0)
        else:  # USD Points ($)
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
        
            line_color = "rgba(59, 130, 246, 0.2)" if IS_DARK else "rgba(37, 99, 235, 0.2)"
            fig.add_hline(
                y=trigger_price,
                line_dash="dot",
                line_color=line_color,
                annotation_text=f"Proposed BUY STOP #{i+1}: ${trigger_price:.2f}",
                annotation_position="top left",
                annotation_font=dict(size=7, color=line_color),
                row=1, col=1
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
        
            line_color = "rgba(245, 158, 11, 0.2)" if IS_DARK else "rgba(217, 119, 6, 0.2)"
            fig.add_hline(
                y=trigger_price,
                line_dash="dot",
                line_color=line_color,
                annotation_text=f"Proposed SELL STOP #{i+1}: ${trigger_price:.2f}",
                annotation_position="bottom left",
                annotation_font=dict(size=7, color=line_color),
                row=1, col=1
            )

    # Plot open positions
    for pos_id, pos in list(broker_instance.open_positions.items()):
        pos_color = "#22c55e" if pos.type == "BUY" else "#ef4444"
        fig.add_hline(
            y=pos.entry_price,
            line_color=pos_color,
            line_width=1.8,
            annotation_text=f"Open {pos.type} {fmt_size(pos.size)}: ${pos.entry_price:.2f}",
            annotation_position="top right",
            annotation_font=dict(size=9, color=pos_color, weight="bold"),
            row=1, col=1
        )

    fig.update_layout(PLOT_LAYOUT)
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=520,
        title=None,
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)" if IS_DARK else "rgba(0,0,0,0.05)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)" if IS_DARK else "rgba(0,0,0,0.05)", row=1, col=1)
    fig.update_yaxes(showgrid=False, row=2, col=1)

    with st.container(border=True):
        st.markdown(
            f'<div class="brand" style="margin-bottom: 5px;">'
            f'<span class="chart-title">'
            f'{chart_coin_label} &nbsp;·&nbsp; Real-Time Traps &amp; Execution Chart'
            f'<span style="font-size:0.7rem; font-weight:400; opacity:0.6; margin-left:8px;">({timeframe_choice})</span>'
            f'</span></div>'
            f'<div class="chart-subtitle">Live price, Bollinger Bands volatility cloud, volume histogram, grid trap levels and executed orders for <strong>{chart_coin_label}</strong> — 10 stops above &amp; 10 below</div>',
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

    # 11.5 MARKET INTELLIGENCE & MANUAL DECISION CENTER
    st.markdown("---")
    _fg_data = fetch_cached_fg_index()
    _mkt_stats = fetch_cached_24h_stats(_active_sym)
    _news_list = fetch_cached_news(_active_sym)

    _df_klines_live = fetch_cached_klines(_active_sym)
    _tech_ind = calculate_technical_indicators(_df_klines_live)

    with st.expander("🧠 MARKET INTELLIGENCE & MANUAL DECISION CENTER", expanded=True):
        st.markdown(
            f'<div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">'
            f'Real-time market sentiment, 24h volume analytics, technical indicator matrix, breaking news feed, and dynamic grid spacing suggestions for manual trading decisions.'
            f'</div>',
            unsafe_allow_html=True
        )
    
        # ROW 1: 4 Intelligence Cards
        ic1, ic2, ic3, ic4 = st.columns(4)
    
        with ic1:
            _fg_val = _fg_data.get("value", 50)
            _fg_cls = _fg_data.get("classification", "Neutral")
            _fg_color = "#22c55e" if _fg_val >= 60 else ("#ef4444" if _fg_val <= 40 else "#f59e0b")
            st.markdown(f"""
            <div class="metric-card" style="border-left: 3px solid {_fg_color};">
                <div class="metric-label">😱 Fear &amp; Greed Index</div>
                <div class="metric-value" style="color: {_fg_color};">{_fg_val} <span style="font-size:0.85rem; font-weight:600;">/ 100</span></div>
                <div class="metric-delta delta-warn" style="background:{_fg_color}22; color:{_fg_color}; font-weight:700;">{_fg_cls.upper()}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with ic2:
            _vol_usd = _mkt_stats.get("volume_usd", 0.0)
            _vol_str = f"${_vol_usd / 1e9:.2f}B" if _vol_usd >= 1e9 else (f"${_vol_usd / 1e6:.1f}M" if _vol_usd >= 1e6 else f"${_vol_usd:,.0f}")
            _chg_24 = _mkt_stats.get("price_change_pct", 0.0)
            _chg_color = "var(--green)" if _chg_24 >= 0 else "var(--red)"
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">📊 24h Trading Volume ({chart_coin_label})</div>
                <div class="metric-value">{_vol_str}</div>
                <div class="metric-delta" style="color:{_chg_color};">24h Change: {_chg_24:+.2f}%</div>
            </div>
            """, unsafe_allow_html=True)
        
        with ic3:
            _score = _tech_ind.get("breakout_score", 50)
            _score_color = "#22c55e" if _score >= 70 else ("#3b82f6" if _score >= 45 else "#f59e0b")
            _squeeze_tag = "⚡ HIGH SQUEEZE" if _tech_ind.get("is_bb_squeeze") else "EXPANDING"
            st.markdown(f"""
            <div class="metric-card" style="border-left: 3px solid {_score_color};">
                <div class="metric-label">🎯 Breakout Potential Score</div>
                <div class="metric-value" style="color:{_score_color};">{_score}%</div>
                <div class="metric-delta" style="background:{_score_color}22; color:{_score_color}; font-weight:700;">{_squeeze_tag}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with ic4:
            _rec_gap = _tech_ind.get("recommended_gap_pct", 0.22)
            _rec_off = _tech_ind.get("recommended_offset_pct", 0.33)
            st.markdown(f"""
            <div class="metric-card" style="border-left: 3px solid var(--accent);">
                <div class="metric-label">📐 Volatility-Optimal Spacing</div>
                <div class="metric-value" style="font-size:1.2rem;">Gap: {_rec_gap:.2f}% | Off: {_rec_off:.2f}%</div>
                <div class="metric-delta delta-up">Derived from live ATR ({_tech_ind.get('atr_pct', 0.0):.2f}%)</div>
            </div>
            """, unsafe_allow_html=True)

        _order_book = fetch_cached_order_book(_active_sym)
        _econ_cal = fetch_cached_calendar()

        # Interactive Sub-Tabs inside Intelligence Center
        intel_tab1, intel_tab2, intel_tab3, intel_tab4, intel_tab5 = st.tabs([
            "📰 Breaking News & Macro Events",
            "📐 Technical Matrix & Spacing Calculator",
            "📊 24h Price Range & Volume Metrics",
            "🧱 Order Book Microstructure Depth",
            "📅 Economic Calendar Shield"
        ])
    
        with intel_tab1:
            st.markdown(f"#### 📰 Market Headlines for {chart_coin_label}")
            if _news_list:
                for item in _news_list:
                    sent = item.get("sentiment", "NEUTRAL")
                    badge_style = {
                        "BULLISH": "badge-green",
                        "BEARISH": "badge-red",
                        "VOLATILITY_ALERT": "badge-amber",
                        "NEUTRAL": "badge-blue"
                    }.get(sent, "badge-blue")
                
                    sent_icon = {
                        "BULLISH": "🚀 BULLISH",
                        "BEARISH": "📉 BEARISH",
                        "VOLATILITY_ALERT": "⚠️ VOLATILITY ALERT",
                        "NEUTRAL": "📰 NEUTRAL"
                    }.get(sent, sent)
                
                    pub_time = datetime.fromtimestamp(item.get("published_at", time.time())).strftime("%H:%M:%S")
                
                    st.markdown(f"""
                    <div style="background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <span class="badge {badge_style}" style="font-size:0.68rem;">{sent_icon}</span>
                            <span style="font-size: 0.7rem; color: var(--text-muted);">{item.get('source')} &bull; {pub_time}</span>
                        </div>
                        <div style="font-weight: 700; font-size: 0.85rem; color: var(--text); margin-bottom: 4px;">
                            <a href="{item.get('url')}" target="_blank" style="color: var(--text); text-decoration: none;">{item.get('title')}</a>
                        </div>
                        <div style="font-size: 0.76rem; color: var(--text-muted);">{item.get('summary')}</div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No breaking news headlines loaded at this moment.")
            
        with intel_tab2:
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.markdown("##### 🔬 Live Technical Indicators")
                _rsi_val = _tech_ind.get("rsi", 50.0)
                _rsi_state = "Overbought 🔴" if _rsi_val > 70 else ("Oversold 🟢" if _rsi_val < 30 else "Neutral 🟡")
                st.markdown(f"""
                <div class="table-wrap">
                    <table class="data-table">
                        <tr><td><strong>RSI (14-Period)</strong></td><td>{_rsi_val}</td><td>{_rsi_state}</td></tr>
                        <tr><td><strong>ATR (14-Period)</strong></td><td>${_tech_ind.get('atr', 0.0):,.2f}</td><td>{_tech_ind.get('atr_pct', 0.0):.2f}% of price</td></tr>
                        <tr><td><strong>Bollinger Band Width</strong></td><td>{_tech_ind.get('bb_width_pct', 0.0):.2f}%</td><td>{'Squeeze (<1.5%) ⚡' if _tech_ind.get('is_bb_squeeze') else 'Normal Bandwidth'}</td></tr>
                        <tr><td><strong>Volume Spike Multiplier</strong></td><td>{_tech_ind.get('volume_spike_mult', 1.0):.2f}x</td><td>vs 20-period volume SMA</td></tr>
                    </table>
                </div>
                """, unsafe_allow_html=True)
            
            with col_t2:
                st.markdown("##### ⚡ Auto-Apply Volatility Spacing")
                st.markdown(
                    f"Based on current market ATR (**{_tech_ind.get('atr_pct', 0.0):.2f}%**), "
                    f"the recommended grid configuration for **{chart_coin_label}** is:"
                )
                st.markdown(f"- **Grid Gap**: `{_rec_gap:.2f}%`")
                st.markdown(f"- **Trap Offset**: `{_rec_off:.2f}%`")
            
                if st.button(f"🎯 APPLY RECOMMENDED SPACING TO {chart_coin_label}", type="primary", use_container_width=True):
                    st.session_state.strat_gap = _rec_gap
                    st.session_state.strat_offset = _rec_off
                    st.session_state.strat_is_percent = True
                
                    # Clear namespaced widget keys so selectboxes update
                    _sym_reset = st.session_state.live_symbol
                    st.session_state.pop(f"strat_gap_input_pct_{_sym_reset}", None)
                    st.session_state.pop(f"strat_offset_input_pct_{_sym_reset}", None)
                    st.session_state.pop(f"strat_is_percent_select_{_sym_reset}", None)
                
                    sync_active_market_primitives()
                    save_bot_state()
                    st.toast(f"Updated spacing for {chart_coin_label}: Gap={_rec_gap:.2f}%, Offset={_rec_off:.2f}%")
                    st.rerun()

        with intel_tab3:
            st.markdown(f"##### 📊 24-Hour Range & Exchange Volume Metrics for {chart_coin_label}")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            with m_col1:
                st.metric("24h High", f"${_mkt_stats.get('high_24h', 0.0):,.2f}")
            with m_col2:
                st.metric("24h Low", f"${_mkt_stats.get('low_24h', 0.0):,.2f}")
            with m_col3:
                st.metric("24h Volume (Coin)", f"{_mkt_stats.get('volume_coin', 0.0):,.2f}")
            with m_col4:
                st.metric("Data Source API", _mkt_stats.get("source", "Exchange API"))

        with intel_tab4:
            st.markdown(f"##### 🧱 Order Book Microstructure Depth & Pressure Wall ({chart_coin_label})")
            ob_col1, ob_col2 = st.columns(2)
            with ob_col1:
                buy_p = _order_book.get("buy_pressure_pct", 50.0)
                sell_p = _order_book.get("sell_pressure_pct", 50.0)
                st.markdown(f"""
                <div style="background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px;">
                    <div style="font-weight: 700; font-size: 0.85rem; margin-bottom: 8px;">Order Wall Pressure Ratio</div>
                    <div style="display: flex; height: 18px; border-radius: 6px; overflow: hidden; margin-bottom: 8px;">
                        <div style="width: {buy_p}%; background: var(--green); text-align: center; color: white; font-size: 0.68rem; font-weight: bold; line-height: 18px;">{buy_p:.1f}% BUY</div>
                        <div style="width: {sell_p}%; background: var(--red); text-align: center; color: white; font-size: 0.68rem; font-weight: bold; line-height: 18px;">{sell_p:.1f}% SELL</div>
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-muted);">
                        Institutional order book volume: <strong>{_order_book.get('bids_volume', 0.0):,.2f} Bids</strong> vs <strong>{_order_book.get('asks_volume', 0.0):,.2f} Asks</strong>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            with ob_col2:
                st.markdown(f"""
                <div style="background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px;">
                    <div style="font-weight: 700; font-size: 0.85rem; margin-bottom: 8px;">Key Order Book Wall Prices</div>
                    <div style="font-size: 0.78rem; display: flex; flex-direction: column; gap: 6px;">
                        <div>🛡️ <strong>Support Wall:</strong> ${_order_book.get('support_wall', 0.0):,.2f}</div>
                        <div>🛑 <strong>Resistance Wall:</strong> ${_order_book.get('resistance_wall', 0.0):,.2f}</div>
                        <div style="color: var(--text-dim); font-size: 0.7rem;">Source: {_order_book.get('source', 'Exchange Depth')}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with intel_tab5:
            st.markdown("##### 📅 Upcoming High-Impact Macro Economic Releases")
            for ev in _econ_cal:
                impact_badge = "badge-red" if ev["impact"] == "HIGH" else "badge-amber"
                t_diff = (ev["timestamp"] - time.time()) / 60.0
                time_txt = f"In {int(t_diff)} mins" if t_diff > 0 else "Released recently"
                st.markdown(f"""
                <div style="background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span class="badge {impact_badge}" style="margin-right: 6px;">{ev['impact']} IMPACT</span>
                        <strong style="font-size: 0.82rem;">{ev['title']}</strong>
                        <span style="font-size: 0.72rem; color: var(--text-muted); margin-left: 8px;">({ev['country']})</span>
                    </div>
                    <div style="font-size: 0.76rem; font-weight: 700; color: var(--accent);">
                        ⏳ {time_txt} &bull; Forecast: {ev['forecast']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

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
