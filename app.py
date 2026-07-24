import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
from datetime import datetime
import textwrap
import pickle
import os

# Import core bot logic
from core.engine import SimulatedBroker, BreakoutGridBot
from core.mt5_broker import MT5Broker, MT5_AVAILABLE
from core.data import get_live_price, get_historical_klines, interpolate_ticks, generate_simulated_ticks

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

/* Form Control Cards */
.control-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.2rem;
    box-shadow: var(--shadow);
    margin-bottom: 1rem;
}}
.control-title {{
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 1rem;
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
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

/* Badge styles */
.badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 0.7rem;
    font-weight: 500;
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
.brand-logo span {{
    color: var(--accent);
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
button[data-baseweb="tab"]:hover {{
    color: var(--text) !important;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: var(--text) !important;
    background: var(--card) !important;
    border-color: var(--border) !important;
    box-shadow: var(--shadow) !important;
}}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {{
    display: none !important;
}}
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
STATE_FILE = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-ide", "bot_state.pkl")
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

DEFAULT_PRICES = {
    "BTCUSDT": 60000.0,
    "ETHUSDT": 3300.0,
    "SOLUSDT": 150.0,
    "BNBUSDT": 580.0,
    "DOGEUSDT": 0.12,
    "PAXGUSDT": 2300.0
}

def get_default_price(symbol: str) -> float:
    return DEFAULT_PRICES.get(symbol.upper(), 100.0)

def get_default_order_size(symbol: str) -> float:
    defaults = {
        "BTCUSDT": 0.008,
        "ETHUSDT": 0.15,
        "SOLUSDT": 3.0,
        "BNBUSDT": 0.8,
        "DOGEUSDT": 3000.0,
        "PAXGUSDT": 0.12
    }
    return defaults.get(symbol, 0.1)

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

def save_bot_state():
    try:
        if "markets" in st.session_state:
            sync_active_market_primitives()
            
            # Re-bind custom classes to the currently imported versions to prevent Streamlit pickle errors on hot-reload
            from core.engine import SimulatedBroker, BreakoutGridBot
            from core.mt5_broker import MT5Broker
            for symbol, m_state in list(st.session_state.markets.items()):
                broker_obj = m_state.get("broker")
                if broker_obj:
                    if broker_obj.__class__.__name__ == "SimulatedBroker" and broker_obj.__class__ != SimulatedBroker:
                        broker_obj.__class__ = SimulatedBroker
                    elif broker_obj.__class__.__name__ == "MT5Broker" and broker_obj.__class__ != MT5Broker:
                        broker_obj.__class__ = MT5Broker
                
                bot_obj = m_state.get("bot")
                if bot_obj:
                    if bot_obj.__class__.__name__ == "BreakoutGridBot" and bot_obj.__class__ != BreakoutGridBot:
                        bot_obj.__class__ = BreakoutGridBot
            
            state = {
                "markets": st.session_state.markets,
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
                class CustomUnpickler(pickle.Unpickler):
                    def find_class(self, module, name):
                        if module == "core.engine":
                            import core.engine
                            return getattr(core.engine, name)
                        elif module == "core.mt5_broker":
                            import core.mt5_broker
                            return getattr(core.mt5_broker, name)
                        return super().find_class(module, name)
                state = CustomUnpickler(f).load()
            
            if "markets" in state:
                st.session_state.markets = state["markets"]
                st.session_state.live_symbol = state["live_symbol"]
                st.session_state.mt5_pwd = state.get("mt5_pwd", "")
                # Ensure zero fees on all loaded brokers and provide default strategy values if missing
                for symbol, m_state in st.session_state.markets.items():
                    if "broker" in m_state and m_state["broker"]:
                        m_state["broker"].commission_pct = 0.0
                        m_state["broker"].slippage_pct = 0.0
                    if "strat_offset" not in m_state:
                        m_state["strat_offset"] = 0.15
                    if "strat_gap" not in m_state:
                        m_state["strat_gap"] = 0.10
                    if "strat_is_percent" not in m_state:
                        m_state["strat_is_percent"] = True
                    if "strat_order_size" not in m_state:
                        m_state["strat_order_size"] = get_default_order_size(symbol)
                    if "strat_size_multiplier" not in m_state:
                        m_state["strat_size_multiplier"] = 1.0
                    if "strat_target_profit" not in m_state:
                        m_state["strat_target_profit"] = 10.0
                    if "strat_sl" not in m_state:
                        m_state["strat_sl"] = float('inf')
                    if "strat_trailing" not in m_state:
                        m_state["strat_trailing"] = False
                    if "strat_trailing_dist" not in m_state:
                        m_state["strat_trailing_dist"] = 1.5
                return True
            else:
                # Migrate old format
                live_sym = state.get("live_symbol", "BTCUSDT")
                st.session_state.live_symbol = live_sym
                
                broker = state["broker"]
                bot = state["bot"]
                broker.commission_pct = 0.0
                broker.slippage_pct = 0.0
                bot.stop_loss = float('inf')
                bot.max_cycle_duration = float('inf')
                
                st.session_state.markets = {
                    live_sym: {
                        "broker": broker,
                        "bot": bot,
                        "price_history": state["price_history"],
                        "last_price": state["last_price"],
                        "running": state.get("running", False),
                        "strat_offset": 0.15,
                        "strat_gap": 0.10,
                        "strat_is_percent": True,
                        "strat_order_size": get_default_order_size(live_sym),
                        "strat_size_multiplier": 1.0,
                        "strat_target_profit": 10.0,
                        "strat_sl": float('inf'),
                        "strat_trailing": False,
                        "strat_trailing_dist": 1.5
                    }
                }
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
            magic_number=998877
        )
    else:
        broker = SimulatedBroker(initial_balance=10000.0, commission_pct=0.0, slippage_pct=0.0)
    
    price_history = []
    price = None
    
    is_simulated = st.session_state.get("price_source_select", "Live Market API") == "Simulated Market (Demo)"
    
    if is_simulated:
        price = get_default_price(st.session_state.live_symbol)
        ticks = generate_simulated_ticks(price, num_ticks=120)
        now = time.time()
        time_diff = now - ticks[-1][0]
        price_history = [(t + time_diff, p) for t, p in ticks]
        price = price_history[-1][1]
    else:
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
        
    bot = BreakoutGridBot(
        broker,
        grid_levels=10,
        grid_gap=0.10,
        trap_offset=0.15,
        order_size=get_default_order_size(st.session_state.live_symbol),
        order_size_multiplier=1.0,
        target_profit=10.0,
        auto_restart=True,
        is_percent=True,
        stop_loss=float('inf'),
        max_cycle_duration=float('inf'),
        cancel_opposite_on_trigger=False
    )
    
    # Only deploy traps initially if it is SimulatedBroker; live broker requires explicit bot start
    if broker.__class__.__name__ == "SimulatedBroker":
        bot.deploy_traps(price, time.time())
    else:
        bot.deployed = False
    
    st.session_state.markets[st.session_state.live_symbol] = {
        "broker": broker,
        "bot": bot,
        "price_history": price_history,
        "last_price": price,
        "running": False,
        "strat_offset": 0.15,
        "strat_gap": 0.10,
        "strat_is_percent": True,
        "strat_order_size": get_default_order_size(st.session_state.live_symbol),
        "strat_size_multiplier": 1.0,
        "strat_target_profit": 10.0,
        "strat_sl": float('inf'),
        "strat_trailing": False,
        "strat_trailing_dist": 1.5
    }

# Sync references to current active market
active_market = st.session_state.markets[st.session_state.live_symbol]
st.session_state.broker = active_market["broker"]
st.session_state.bot = active_market["bot"]
st.session_state.price_history = active_market["price_history"]
st.session_state.last_price = active_market["last_price"]
st.session_state.running = active_market["running"]

# Synchronize active orders and positions with MT5 on every script execution to keep UI tables populated even when bot is paused
try:
    st.session_state.broker.sync()
except Exception as e:
    print(f"Failed to synchronize broker state: {e}")

# Initialize or sync current symbol to avoid resetting strategy parameter states on every rerun
if "current_symbol" not in st.session_state or st.session_state.current_symbol != st.session_state.live_symbol:
    st.session_state.current_symbol = st.session_state.live_symbol
    st.session_state.strat_offset = active_market.get("strat_offset", 0.15)
    st.session_state.strat_gap = active_market.get("strat_gap", 0.10)
    st.session_state.strat_is_percent = active_market.get("strat_is_percent", True)
    st.session_state.strat_order_size = active_market.get("strat_order_size", get_default_order_size(st.session_state.live_symbol))
    st.session_state.strat_size_multiplier = active_market.get("strat_size_multiplier", 1.0)
    st.session_state.strat_target_profit = active_market.get("strat_target_profit", 10.0)
    st.session_state.strat_sl = active_market.get("strat_sl", float('inf'))
    st.session_state.strat_trailing = active_market.get("strat_trailing", False)
    st.session_state.strat_trailing_dist = active_market.get("strat_trailing_dist", 1.5)

# --- SYNC WIDGET INPUTS TO STATE VARIABLES ON RERUN BEFORE RENDERING ---
if "strat_is_percent_select" in st.session_state:
    st.session_state.strat_is_percent = (st.session_state.strat_is_percent_select == "Percentage (%)")

if "strat_size_multiplier_input" in st.session_state:
    st.session_state.strat_size_multiplier = st.session_state.strat_size_multiplier_input
if "strat_order_size_input" in st.session_state:
    st.session_state.strat_order_size = st.session_state.strat_order_size_input
if "strat_target_profit_input" in st.session_state:
    st.session_state.strat_target_profit = st.session_state.strat_target_profit_input
if "strat_trailing_input" in st.session_state:
    st.session_state.strat_trailing = st.session_state.strat_trailing_input
if "strat_trailing_dist_input" in st.session_state:
    st.session_state.strat_trailing_dist = st.session_state.strat_trailing_dist_input

if st.session_state.get("strat_is_percent", True):
    if "strat_gap_input_pct" in st.session_state:
        st.session_state.strat_gap = st.session_state.strat_gap_input_pct
    if "strat_offset_input_pct" in st.session_state:
        st.session_state.strat_offset = st.session_state.strat_offset_input_pct
else:
    if "strat_gap_input_usd" in st.session_state:
        st.session_state.strat_gap = st.session_state.strat_gap_input_usd
    if "strat_offset_input_usd" in st.session_state:
        st.session_state.strat_offset = st.session_state.strat_offset_input_usd
# -----------------------------------------------------------------------

# Detect if parameters affecting grid layout or sizing have changed
bot = st.session_state.bot
broker = st.session_state.broker

settings_changed = (
    bot.grid_gap != st.session_state.strat_gap or
    bot.trap_offset != st.session_state.strat_offset or
    bot.order_size != st.session_state.strat_order_size or
    bot.order_size_multiplier != st.session_state.strat_size_multiplier or
    bot.is_percent != st.session_state.strat_is_percent
)

# Apply settings to the bot instance
bot.grid_levels = 10
bot.grid_gap = st.session_state.strat_gap
bot.trap_offset = st.session_state.strat_offset
bot.order_size = st.session_state.strat_order_size
bot.order_size_multiplier = st.session_state.strat_size_multiplier
bot.target_profit = st.session_state.strat_target_profit
bot.auto_restart = True
bot.is_percent = st.session_state.strat_is_percent
bot.stop_loss = st.session_state.strat_sl
bot.max_cycle_duration = float('inf')
bot.cancel_opposite_on_trigger = False
bot.use_trailing_stop = st.session_state.strat_trailing
bot.trailing_stop_distance = st.session_state.strat_trailing_dist
bot.use_bb_filter = False

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
    if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
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
                magic_number=998877
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
        broker = SimulatedBroker(initial_balance=10000.0, commission_pct=0.0, slippage_pct=0.0)
        st.session_state.markets[sym]["broker"] = broker
        st.session_state.markets[sym]["bot"].broker = broker
        
    # Sync active references
    active_market = st.session_state.markets[st.session_state.live_symbol]
    st.session_state.broker = active_market["broker"]
    st.session_state.bot = active_market["bot"]
    
    # Deploy simulated traps
    st.session_state.bot.deploy_traps(st.session_state.last_price, time.time())
    st.session_state.mt5_startup_error = None
    save_bot_state()

# Initialize history if empty
if not st.session_state.price_history:
    reset_realtime_sandbox()

# 6. HEADER RENDERING
st.markdown(f"""
<div class="brand-container">
    <div class="brand-logo">
        ◆ MATY <span>BREAKOUT GRID BOT</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 7. EXECUTION CONTROLS & STRATEGY TUNING
col_controls, col_strategy = st.columns([5, 7])

with col_controls:
    st.markdown('<div class="control-card"><div class="control-title">Execution Controls</div>', unsafe_allow_html=True)
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([4, 5, 3])
    
    with ctrl_col1:
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
            "Cryptocurrency / Market",
            list(market_options.keys()),
            index=default_idx,
            key="symbol_select_dropdown"
        )
        symbol = market_options[selected_label]
        
        if symbol != st.session_state.live_symbol:
            # 1. Clean up the old symbol's pending orders so they are not left orphaned/active on the broker
            old_sym = st.session_state.live_symbol
            if old_sym in st.session_state.markets:
                old_broker = st.session_state.markets[old_sym]["broker"]
                old_bot = st.session_state.markets[old_sym]["bot"]
                if old_bot.deployed:
                    try:
                        old_broker.cancel_all_orders()
                        old_bot.deployed = False
                    except Exception as e:
                        print(f"Failed to cancel old traps for {old_sym}: {e}")

            # 2. Automatically pause execution when switching symbols to avoid background/unprompted active trading
            st.session_state.running = False

            sync_active_market_primitives()
            st.session_state.live_symbol = symbol
            
            # Fetch fresh historical price data for the newly selected symbol to prevent huge gaps in the chart
            is_simulated = st.session_state.get("price_source_select", "Live Market API") == "Simulated Market (Demo)"
            default_p = get_default_price(symbol)
            new_price_history = []
            new_price = None
            
            if is_simulated:
                start_p = st.session_state.markets[symbol]["last_price"] if (symbol in st.session_state.markets and st.session_state.markets[symbol].get("last_price")) else default_p
                ticks = generate_simulated_ticks(start_p, num_ticks=120)
                now = time.time()
                time_diff = now - ticks[-1][0]
                new_price_history = [(t + time_diff, p) for t, p in ticks]
                new_price = new_price_history[-1][1]
            else:
                try:
                    df_hist = get_historical_klines(symbol, interval="1m", limit=30)
                    if df_hist is not None and not df_hist.empty:
                        df_ticks = interpolate_ticks(df_hist)
                        new_price_history = list(zip(df_ticks["timestamp"], df_ticks["price"]))
                        new_price = new_price_history[-1][1]
                except Exception as e:
                    print(f"Error fetching klines on symbol switch: {e}")
                
                if new_price is None:
                    new_price = get_live_price(symbol)
                    if new_price is None:
                        new_price = st.session_state.markets[symbol]["last_price"] if (symbol in st.session_state.markets and st.session_state.markets[symbol].get("last_price")) else default_p
                    new_price_history = [(time.time(), new_price)]
            
            if symbol in st.session_state.markets:
                st.session_state.markets[symbol]["price_history"] = new_price_history
                st.session_state.markets[symbol]["last_price"] = new_price
                
                # Redeploy traps at new price if there are no open positions (with defensive try-except)
                curr_broker = st.session_state.markets[symbol]["broker"]
                curr_bot = st.session_state.markets[symbol]["bot"]
                if len(curr_broker.open_positions) == 0:
                    try:
                        curr_bot.deploy_traps(new_price, time.time())
                        st.session_state.error_message = None
                    except Exception as e:
                        st.session_state.error_message = f"Failed to deploy traps for {symbol}: {e}"
            
            save_bot_state()  # Persist symbol change to disk immediately
            st.rerun()
            
        timeframe = st.selectbox(
            "Chart Timeframe",
            ["5 Seconds", "1 Minute"],
            key="timeframe_select"
        )
        
        price_source = st.selectbox(
            "Price Source",
            ["Live Market API", "Simulated Market (Demo)"],
            key="price_source_select"
        )

    with ctrl_col2:
        st.write("") # vertical spacing align
        run_col1, run_col2 = st.columns(2)
        with run_col1:
            if not st.session_state.running:
                if st.button("▶ START BOT", type="primary", use_container_width=True):
                    # Close any leftover positions and cancel any leftover pending orders before starting fresh
                    try:
                        curr_price = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
                        st.session_state.broker.close_all_positions(curr_price, time.time())
                        st.session_state.broker.cancel_all_orders()
                    except Exception as e:
                        print(f"Startup cleanup failed: {e}")
                    
                    st.session_state.bot.deployed = False
                    st.session_state.running = True
                    save_bot_state()
                    st.rerun()
            else:
                if st.button("⏸ PAUSE BOT", type="secondary", use_container_width=True):
                    st.session_state.running = False
                    save_bot_state()
                    st.rerun()
        with run_col2:
            if st.button("🚨 PANIC CLOSE", type="secondary", use_container_width=True):
                curr_price = st.session_state.price_history[-1][1]
                closed = st.session_state.broker.close_all_positions(curr_price, time.time())
                st.session_state.broker.cancel_all_orders()
                st.session_state.bot.deployed = False
                st.session_state.running = False
                save_bot_state()
                st.warning(f"Panic close executed! Closed {len(closed)} open trades.")
                st.rerun()

    with ctrl_col3:
        st.write("") # vertical spacing align
        theme_col, reset_col = st.columns(2)
        with theme_col:
            theme_btn_text = "☀️ LIGHT" if IS_DARK else "🌙 DARK"
            st.button(theme_btn_text, on_click=toggle_theme, use_container_width=True)
        with reset_col:
            if st.button("🔄 RESET", use_container_width=True):
                reset_realtime_sandbox()
                st.success("Environment reset complete.")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Exness MT5 connection UI
    broker_type = "Simulated Sandbox" if st.session_state.broker.__class__.__name__ == "SimulatedBroker" else "Exness MT5 Live"
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
            st.warning("MetaTrader 5 Python package is not available on this machine. Run: `pip install MetaTrader5` in your terminal to enable it.")
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
    st.markdown('<div class="control-card"><div class="control-title">Strategy Tuning</div>', unsafe_allow_html=True)
    strat_col1, strat_col2, strat_col3 = st.columns(3)
    with strat_col1:
        # Spacing Mode selectbox
        spacing_mode = st.selectbox(
            "Spacing Mode",
            ["Percentage (%)", "USD Points / Pips"],
            index=0 if st.session_state.get("strat_is_percent", True) else 1,
            key="strat_is_percent_select"
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
            offset_min, offset_max, offset_step = 0.1, 5000.0, 1.0
            gap_label = "Grid Gap (USD)"
            gap_min, gap_max, gap_step = 0.1, 5000.0, 1.0
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
            key=f"strat_offset_input_{'pct' if st.session_state.strat_is_percent else 'usd'}"
        )
        st.session_state.strat_offset = trap_offset_val
        
        grid_gap_val = st.number_input(
            gap_label,
            min_value=gap_min,
            max_value=gap_max,
            value=default_gap,
            step=gap_step,
            format="%.2f" if st.session_state.strat_is_percent or default_gap % 1 != 0 else "%.1f",
            key=f"strat_gap_input_{'pct' if st.session_state.strat_is_percent else 'usd'}"
        )
        st.session_state.strat_gap = grid_gap_val
        
    with strat_col2:
        target_profit_val = st.number_input(
            "Target Profit (USD)",
            min_value=1.0,
            max_value=10000.0,
            value=st.session_state.strat_target_profit,
            step=1.0,
            key="strat_target_profit_input"
        )
        st.session_state.strat_target_profit = target_profit_val

        trailing_stop_val = st.toggle(
            "Enable Trailing Stop",
            value=st.session_state.strat_trailing,
            key="strat_trailing_input"
        )
        st.session_state.strat_trailing = trailing_stop_val
        
        trailing_dist_val = st.number_input(
            "Trailing Distance (USD)",
            min_value=0.1,
            max_value=1000.0,
            value=st.session_state.strat_trailing_dist,
            step=0.5,
            disabled=not trailing_stop_val,
            key="strat_trailing_dist_input"
        )
        st.session_state.strat_trailing_dist = trailing_dist_val
        
    with strat_col3:
        order_size_val = st.number_input(
            "Base Order Size (Quantity)",
            min_value=0.00001,
            max_value=1000000.0,
            value=st.session_state.strat_order_size,
            step=0.0001 if st.session_state.strat_order_size < 0.1 else 0.01,
            format="%.5f" if st.session_state.strat_order_size < 0.01 else "%.3f" if st.session_state.strat_order_size < 1.0 else "%.1f",
            key="strat_order_size_input"
        )
        st.session_state.strat_order_size = order_size_val

        size_mult_val = st.number_input(
            "Size Multiplier (Martingale)",
            min_value=0.5,
            max_value=5.0,
            value=st.session_state.strat_size_multiplier,
            step=0.1,
            format="%.2f" if st.session_state.strat_size_multiplier % 0.1 != 0 else "%.1f",
            key="strat_size_multiplier_input"
        )
        st.session_state.strat_size_multiplier = size_mult_val
        
        # Calculate progression directly from configured base order size
        progression = [f"{st.session_state.strat_order_size * (st.session_state.strat_size_multiplier ** i):.5f}" for i in range(5)]
        clean_prog = [p.rstrip('0').rstrip('.') for p in progression]
        st.caption(f"📐 Sizing progression: {' ➔ '.join(clean_prog)} ...")
        
    st.markdown('</div>', unsafe_allow_html=True)

# 8. ENGINE TICK PROCESSING
# Run calculation tick if running
if st.session_state.running:
    # 1. Fetch latest price
    if st.session_state.get("price_source_select", "Live Market API") == "Simulated Market (Demo)":
        last_p = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
        vol = 0.0008 if st.session_state.live_symbol == "PAXGUSDT" else 0.0005
        change = np.random.normal(0, vol)
        latest_price = round(last_p * (1 + change), 2)
        st.session_state.error_message = None
    else:
        latest_price = get_live_price(st.session_state.live_symbol)
        if latest_price is None:
            # Fall back to last recorded price if API times out
            st.session_state.error_message = "Binance API connection timeout. Retrying..."
            latest_price = st.session_state.price_history[-1][1]
        else:
            st.session_state.error_message = None
    
    # Record price tick
    now = time.time()
    previous_price = st.session_state.price_history[-1][1]
    st.session_state.price_history.append((now, latest_price))
    
    # Keep history to last 3000 points for charting performance
    if len(st.session_state.price_history) > 3000:
        st.session_state.price_history.pop(0)
        
    # 2. Update engine
    try:
        cycle_hit = st.session_state.bot.process_tick(previous_price, latest_price, now)
        if cycle_hit:
            st.toast(f"🎉 Cycle {cycle_hit['cycle_id']} exit hit target profit! PnL: ${cycle_hit['pnl']:.2f}")
        st.session_state.error_message = None
    except Exception as e:
        st.session_state.error_message = f"Tick processing failed: {e}"
        # Auto-pause the bot immediately to prevent infinite redeployment loops and order flooding
        st.session_state.running = False
        if "markets" in st.session_state and st.session_state.live_symbol in st.session_state.markets:
            st.session_state.markets[st.session_state.live_symbol]["running"] = False
    save_bot_state()
else:
    # If bot is not running, periodically fetch the live price on page load to keep it fresh
    now = time.time()
    if not st.session_state.price_history or (now - st.session_state.price_history[-1][0] > 5.0):
        if st.session_state.get("price_source_select", "Live Market API") == "Simulated Market (Demo)":
            # Just keep the last price, no need to query live API
            latest_price = st.session_state.price_history[-1][1]
        else:
            latest_price = get_live_price(st.session_state.live_symbol)
            if latest_price is not None:
                # Update the last point in history to show the real current price
                st.session_state.price_history[-1] = (now, latest_price)
                st.session_state.last_price = latest_price
                st.session_state.error_message = None
                save_bot_state()

# Get current state pointers
curr_price = st.session_state.price_history[-1][1]
broker_instance = st.session_state.broker
bot_instance = st.session_state.bot
display_symbol = "XAUUSD" if symbol == "PAXGUSDT" else symbol

# 9. KPI METRIC CARDS
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
    metric_card("Floating PnL", f"${float_pnl:,.2f}", delta=f"{float_pnl:+.2f}" if float_pnl != 0 else None, delta_type=pnl_type)
with kpi5:
    real_pnl = broker_instance.realized_pnl
    pnl_type = "up" if real_pnl > 0 else ("down" if real_pnl < 0 else "warn")
    metric_card("Realized PnL", f"${real_pnl:,.2f}", delta=f"{real_pnl:+.2f}" if real_pnl != 0 else None, delta_type=pnl_type)

# Alerts if any
if st.session_state.error_message:
    st.warning(st.session_state.error_message)

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
if bot_instance.deployed:
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
fig.update_layout(xaxis_rangeslider_visible=False)
fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)" if IS_DARK else "rgba(0,0,0,0.05)")
fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)" if IS_DARK else "rgba(0,0,0,0.05)")

with st.container(border=True):
    st.markdown(f'<div class="brand" style="margin-bottom: 5px;"><span class="chart-title">Real-Time Market Traps & Execution Chart ({timeframe_choice})</span></div><div class="chart-subtitle">Real-time prices, trap levels, and executed orders (10 Stops above, 10 Stops below)</div>', unsafe_allow_html=True)
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
            rows_html += f"<tr><td>{pos.position_id}</td><td>{badge_html}</td><td>${pos.entry_price:,.2f}</td><td>{pos.size:.4f}</td><td style='{pnl_style} font-weight: bold;'>${pnl:+,.2f}</td></tr>"
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
            rows_other_html += f"<tr><td>{p['ticket']}</td><td>{p['symbol']}</td><td>{badge_html}</td><td>${p['price']:,.2f}</td><td>{p['volume']:.4f}</td><td style='font-weight: bold; color: {'var(--green)' if p['profit'] >= 0 else 'var(--red)'};'>${p['profit']:+,.2f}</td><td>Magic: {p['magic']}</td></tr>"
        
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
            rows_html += f"<tr><td>{o.order_id}</td><td>{badge_html}</td><td>${o.trigger_price:,.2f}</td><td>{o.size:.4f}</td></tr>"
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

# 12. HISTORY LOGS TABS
tab_cycles, tab_trades, tab_backtest = st.tabs(["🔄 Completed Cycles", "📜 Detailed Trades Log", "🧪 Backtesting"])

with tab_cycles:
    if bot_instance.cycle_history:
        rows_html = ""
        for cycle in reversed(bot_instance.cycle_history):
            pnl_style = "color: var(--green);" if cycle["pnl"] >= 0 else "color: var(--red);"
            dt_str = datetime.fromtimestamp(cycle["exit_time"]).strftime("%H:%M:%S")
            duration = cycle["exit_time"] - cycle["start_time"]
            
            rows_html += f"<tr><td>Cycle #{cycle['cycle_id']}</td><td>${cycle['deploy_price']:,.2f}</td><td>${cycle['exit_price']:,.2f}</td><td>{cycle['trades_count']} trades</td><td>{duration:.1f}s</td><td style='{pnl_style} font-weight: bold;'>${cycle['pnl']:+,.2f}</td><td>{dt_str}</td></tr>"
        cycles_html = f"""
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Cycle ID</th>
                        <th>Deploy Price</th>
                        <th>Exit Price</th>
                        <th>Execution Stats</th>
                        <th>Duration</th>
                        <th>Total Net PnL</th>
                        <th>Completed At</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
    else:
        cycles_html = """
        <div class="table-wrap">
            <p style='font-size:0.8rem; color:#71717a; margin: 0;'>No completed breakout cycles yet</p>
        </div>
        """
    st.markdown(textwrap.dedent(cycles_html), unsafe_allow_html=True)

with tab_trades:
    if broker_instance.closed_trades:
        rows_html = ""
        for t in reversed(broker_instance.closed_trades):
            pnl_style = "color: var(--green);" if t["pnl"] >= 0 else "color: var(--red);"
            dt_entry = datetime.fromtimestamp(t["entry_time"]).strftime("%H:%M:%S")
            dt_exit = datetime.fromtimestamp(t["exit_time"]).strftime("%H:%M:%S")
            badge_type = "green" if t["type"] == "BUY" else "red"
            badge_html = render_badge(t["type"], badge_type)
            
            rows_html += f"<tr><td>{t['position_id']}</td><td>{badge_html}</td><td>${t['entry_price']:,.2f}</td><td>${t['exit_price']:,.2f}</td><td>{t['size']:.4f}</td><td>${t['commission']:,.4f}</td><td style='{pnl_style} font-weight: bold;'>${t['pnl']:+,.2f}</td><td>{dt_entry}</td><td>{dt_exit}</td></tr>"
        trades_html = f"""
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
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
            <p style='font-size:0.8rem; color:#71717a; margin: 0;'>No detailed trades executed yet</p>
        </div>
        """
    st.markdown(textwrap.dedent(trades_html), unsafe_allow_html=True)

with tab_backtest:
    st.markdown('<div class="control-card"><div class="control-title">Historical Backtest Suite</div>', unsafe_allow_html=True)
    
    bt_col1, bt_col2 = st.columns([1, 1])
    with bt_col1:
        candles_limit = st.slider("Historical Candles Count (1-minute intervals)", min_value=100, max_value=1000, value=500, step=50)
    with bt_col2:
        bt_balance = st.number_input("Initial Balance ($)", min_value=100.0, max_value=1000000.0, value=10000.0, step=100.0)
        
    if st.button("🚀 RUN HISTORICAL BACKTEST", type="primary", use_container_width=True):
        with st.spinner("Fetching historical data and running backtest..."):
            symbol_to_fetch = st.session_state.live_symbol
            df_klines = get_historical_klines(symbol_to_fetch, interval="1m", limit=candles_limit)
            if df_klines is None or df_klines.empty:
                st.error("Failed to fetch historical data for backtesting. Please check your network connection.")
            else:
                df_ticks = interpolate_ticks(df_klines)
                
                # Setup backtest broker & bot with zero fees
                bt_broker = SimulatedBroker(initial_balance=bt_balance, commission_pct=0.0, slippage_pct=0.0)
                start_price = df_ticks.iloc[0]["price"]
                bt_order_size = 500.0 / start_price
                
                bt_bot = BreakoutGridBot(
                    bt_broker,
                    grid_levels=10,
                    grid_gap=st.session_state.strat_gap,
                    trap_offset=st.session_state.strat_offset,
                    order_size=bt_order_size,
                    order_size_multiplier=st.session_state.strat_size_multiplier,
                    target_profit=st.session_state.strat_target_profit,
                    auto_restart=True,
                    is_percent=st.session_state.strat_is_percent,
                    stop_loss=st.session_state.strat_sl,
                    max_cycle_duration=float('inf'),
                    cancel_opposite_on_trigger=False,
                    use_trailing_stop=st.session_state.strat_trailing,
                    trailing_stop_distance=st.session_state.strat_trailing_dist
                )
                
                equity_history = []
                price_history = []
                timestamps = []
                
                bt_bot.deploy_traps(start_price, df_ticks.iloc[0]["timestamp"])
                
                ticks_list = list(zip(df_ticks["timestamp"], df_ticks["price"]))
                for i in range(1, len(ticks_list)):
                    prev_t, prev_p = ticks_list[i-1]
                    curr_t, curr_p = ticks_list[i]
                    
                    bt_bot.process_tick(prev_p, curr_p, curr_t)
                    
                    if i % 10 == 0 or i == len(ticks_list) - 1:
                        eq = bt_broker.get_equity(curr_p)
                        equity_history.append(eq)
                        price_history.append(curr_p)
                        timestamps.append(datetime.fromtimestamp(curr_t))
                
                end_price = ticks_list[-1][1]
                end_time = ticks_list[-1][0]
                bt_broker.close_all_positions(end_price, end_time)
                final_equity = bt_broker.balance
                net_profit = final_equity - bt_balance
                profit_pct = (net_profit / bt_balance) * 100.0
                
                st.session_state.bt_results = {
                    "net_profit": net_profit,
                    "profit_pct": profit_pct,
                    "final_equity": final_equity,
                    "start_balance": bt_balance,
                    "completed_cycles": len(bt_bot.cycle_history),
                    "total_trades": len(bt_broker.closed_trades),
                    "equity_history": equity_history,
                    "price_history": price_history,
                    "timestamps": timestamps,
                    "closed_trades": bt_broker.closed_trades,
                    "cycle_history": bt_bot.cycle_history,
                    "symbol": symbol_to_fetch
                }
                st.toast("🎉 Backtest completed successfully!")
                
    if "bt_results" in st.session_state:
        res = st.session_state.bt_results
        display_sym = "XAUUSD" if res["symbol"] == "PAXGUSDT" else res["symbol"]
        
        st.markdown("### Backtest Results Summary")
        
        bt_metric1, bt_metric2, bt_metric3, bt_metric4 = st.columns(4)
        with bt_metric1:
            pnl_type = "up" if res["net_profit"] >= 0 else "down"
            metric_card("Total Net Profit", f"${res['net_profit']:.2f}", delta=f"{res['profit_pct']:+.2f}%", delta_type=pnl_type)
        with bt_metric2:
            metric_card("Final Account Equity", f"${res['final_equity']:.2f}")
        with bt_metric3:
            metric_card("Completed Cycles", f"{res['completed_cycles']}")
        with bt_metric4:
            metric_card("Total Closed Trades", f"{res['total_trades']}")
            
        st.markdown("#### Performance Charts")
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            fig_equity = go.Figure()
            fig_equity.add_trace(go.Scatter(
                x=res["timestamps"],
                y=res["equity_history"],
                mode="lines",
                name="Equity ($)",
                line=dict(color="#22c55e", width=2)
            ))
            fig_equity.update_layout(PLOT_LAYOUT)
            fig_equity.update_layout(
                yaxis=dict(title="Account Equity ($)", side="left"),
                xaxis=dict(title="Time")
            )
            st.markdown('<div class="brand" style="margin-bottom: 5px;"><span class="chart-title">Account Equity Growth Curve</span></div>', unsafe_allow_html=True)
            st.plotly_chart(fig_equity, use_container_width=True, config={"displayModeBar": False})
            
        with chart_col2:
            fig_price = go.Figure()
            fig_price.add_trace(go.Scatter(
                x=res["timestamps"],
                y=res["price_history"],
                mode="lines",
                name="Price ($)",
                line=dict(color="#3b82f6", width=2)
            ))
            fig_price.update_layout(PLOT_LAYOUT)
            fig_price.update_layout(
                yaxis=dict(title=f"{display_sym} Price ($)", side="left"),
                xaxis=dict(title="Time")
            )
            st.markdown(f'<div class="brand" style="margin-bottom: 5px;"><span class="chart-title">{display_sym} Historical Price Path</span></div>', unsafe_allow_html=True)
            st.plotly_chart(fig_price, use_container_width=True, config={"displayModeBar": False})
            
        st.markdown("#### Backtest Completed Cycles")
        if res["cycle_history"]:
            rows_html = ""
            for cycle in reversed(res["cycle_history"]):
                pnl_style = "color: var(--green);" if cycle["pnl"] >= 0 else "color: var(--red);"
                dt_str = datetime.fromtimestamp(cycle["exit_time"]).strftime("%Y-%m-%d %H:%M:%S")
                duration = cycle["exit_time"] - cycle["start_time"]
                
                rows_html += f"<tr><td>Cycle #{cycle['cycle_id']}</td><td>${cycle['deploy_price']:,.2f}</td><td>${cycle['exit_price']:,.2f}</td><td>{cycle['trades_count']} trades</td><td>{duration:.1f}s</td><td style='{pnl_style} font-weight: bold;'>${cycle['pnl']:+,.2f}</td><td>{dt_str}</td></tr>"
            cycles_html = f"""
            <div class="table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Cycle ID</th>
                            <th>Deploy Price</th>
                            <th>Exit Price</th>
                            <th>Execution Stats</th>
                            <th>Duration</th>
                            <th>Total Net PnL</th>
                            <th>Completed At</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
            """
        else:
            cycles_html = """
            <div class="table-wrap">
                <p style='font-size:0.8rem; color:#71717a; margin: 0;'>No completed breakout cycles during the backtest period.</p>
            </div>
            """
        st.markdown(textwrap.dedent(cycles_html), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# 13. RUNNER LOOP
if st.session_state.running:
    time.sleep(1.0)
    st.rerun()
