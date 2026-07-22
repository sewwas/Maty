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
STATE_FILE = "bot_state.pkl"

def save_bot_state():
    try:
        if "broker" in st.session_state and "bot" in st.session_state:
            state = {
                "broker": st.session_state.broker,
                "bot": st.session_state.bot,
                "price_history": st.session_state.price_history,
                "last_price": st.session_state.last_price,
                "live_symbol": st.session_state.live_symbol,
                "running": st.session_state.running
            }
            with open(STATE_FILE, "wb") as f:
                pickle.dump(state, f)
    except Exception as e:
        print(f"Error saving bot state: {e}")

def load_bot_state() -> bool:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                state = pickle.load(f)
            st.session_state.broker = state["broker"]
            st.session_state.bot = state["bot"]
            st.session_state.price_history = state["price_history"]
            st.session_state.last_price = state["last_price"]
            st.session_state.live_symbol = state["live_symbol"]
            st.session_state.running = state.get("running", False)
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
# Attempt to load state first
state_loaded = load_bot_state()

if "error_message" not in st.session_state:
    st.session_state.error_message = None

if not state_loaded:
    if "broker" not in st.session_state:
        st.session_state.broker = SimulatedBroker(initial_balance=10000.0, commission_pct=0.0005, slippage_pct=0.0002)

    if "price_history" not in st.session_state:
        st.session_state.price_history = []  # list of tuples (timestamp, price)

    if "running" not in st.session_state:
        st.session_state.running = False

    if "live_symbol" not in st.session_state:
        st.session_state.live_symbol = "BTCUSDT"

    if "last_price" not in st.session_state:
        st.session_state.last_price = 60000.0

    if "bot" not in st.session_state:
        st.session_state.bot = BreakoutGridBot(
            st.session_state.broker,
            grid_levels=10,
            grid_gap=0.10,
            trap_offset=0.15,
            order_size=0.0083, # default placeholder for BTCUSDT at 60k to target $500
            target_profit=10.0,
            auto_restart=True,
            is_percent=True,
            stop_loss=100.0,
            max_cycle_duration=3600.0,
            cancel_opposite_on_trigger=False
        )

# Force the hardcoded settings to be applied to the bot instance
# Calculate dynamic order size to target a position value of ~$500 USD per level
current_price = st.session_state.price_history[-1][1] if st.session_state.price_history else st.session_state.last_price
dynamic_order_size = 500.0 / current_price

st.session_state.bot.grid_levels = 10
st.session_state.bot.grid_gap = 0.10
st.session_state.bot.trap_offset = 0.15
st.session_state.bot.order_size = dynamic_order_size
st.session_state.bot.target_profit = 10.0
st.session_state.bot.auto_restart = True
st.session_state.bot.is_percent = True
st.session_state.bot.stop_loss = 100.0
st.session_state.bot.max_cycle_duration = 3600.0
st.session_state.bot.cancel_opposite_on_trigger = False
st.session_state.bot.use_trailing_stop = False
st.session_state.bot.use_bb_filter = False

# Helper to reset real-time dashboard data
def reset_realtime_sandbox():
    clear_bot_state()
    st.session_state.broker.reset()
    st.session_state.bot.deployed = False
    st.session_state.bot.current_cycle_id = 1
    st.session_state.bot.cycle_history.clear()
    
    # Initialize price history with single price point
    symbol = st.session_state.live_symbol
    price = get_live_price(symbol)
    if price is None:
        price = st.session_state.last_price
    else:
        st.session_state.last_price = price
        
    st.session_state.price_history = [(time.time(), price)]
    
    # Scale order size dynamically based on price before deploying traps
    st.session_state.bot.order_size = 500.0 / price
    st.session_state.bot.deploy_traps(price, time.time())
    st.session_state.error_message = None
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

# 7. EXECUTION CONTROLS CENTER CARD
st.markdown('<div class="control-card"><div class="control-title">Execution Controls</div>', unsafe_allow_html=True)
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([4, 5, 3])

with ctrl_col1:
    symbol = st.selectbox(
        "Cryptocurrency",
        ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"],
        key="symbol_select"
    )
    if symbol != st.session_state.live_symbol:
        st.session_state.live_symbol = symbol
        reset_realtime_sandbox()

with ctrl_col2:
    st.write("") # vertical spacing align
    run_col1, run_col2 = st.columns(2)
    with run_col1:
        if not st.session_state.running:
            if st.button("▶ START BOT", type="primary", use_container_width=True):
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

# 8. ENGINE TICK PROCESSING
# Run calculation tick if running
if st.session_state.running:
    # 1. Fetch latest price from live market (Binance API)
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
    
    # Keep history to last 150 points for charting performance
    if len(st.session_state.price_history) > 150:
        st.session_state.price_history.pop(0)
        
    # 2. Update engine
    cycle_hit = st.session_state.bot.process_tick(previous_price, latest_price, now)
    if cycle_hit:
        st.toast(f"🎉 Cycle {cycle_hit['cycle_id']} exit hit target profit! PnL: ${cycle_hit['pnl']:.2f}")
    save_bot_state()
else:
    # If bot is not running, periodically fetch the live price on page load to keep it fresh
    now = time.time()
    if not st.session_state.price_history or (now - st.session_state.price_history[-1][0] > 5.0):
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
# Convert ticks to 5-second candlesticks
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
        name=f"{symbol} Price",
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
    for o in broker_instance.pending_orders.values():
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
for pos_id, pos in broker_instance.open_positions.items():
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
    st.markdown('<div class="brand" style="margin-bottom: 5px;"><span class="chart-title">Real-Time Market Traps & Execution Chart</span></div><div class="chart-subtitle">Real-time prices, trap levels, and executed orders (10 Stops above, 10 Stops below)</div>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# 11. TABLES
col_tables1, col_tables2 = st.columns(2)

with col_tables1:
    if broker_instance.open_positions:
        rows_html = ""
        for pos in broker_instance.open_positions.values():
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

with col_tables2:
    if broker_instance.pending_orders:
        rows_html = ""
        sorted_orders = sorted(broker_instance.pending_orders.values(), key=lambda x: x.trigger_price, reverse=True)
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
tab_cycles, tab_trades = st.tabs(["🔄 Completed Cycles", "📜 Detailed Trades Log"])

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

# 13. RUNNER LOOP
if st.session_state.running:
    time.sleep(1.0)
    st.rerun()
