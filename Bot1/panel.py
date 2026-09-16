"""
Bot #1 — Sunrise Ogle Master Command Panel (Port 8501)
=====================================================
Connects to Wine MT5 REST Bridge on Port 8001 (Exness Real Account)
Visualizes:
- 🌅 Real-time 4-Phase State Machine (SCANNING -> ARMED -> WINDOW_OPEN -> IN_POSITION)
- 📊 Live 5-Minute Candlestick Chart with Multi-EMA (14/24/100) & Breakout Trigger Lines
- ⚡ Live Account Telemetry (Exness Cent 1:2000 Leverage)
- 🛡️ Trailing Stop Ratchet & Active Position Management
- 🎮 Instant Manual Overrides, Emergency Close, and Strategy Tuning
"""

import os
import sys
import time
import datetime
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Streamlit page config
st.set_page_config(
    page_title="Profity AI — Bot #1 Sunrise Ogle System",
    page_icon="🌅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Ensure local imports work cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from sunrise_engine import get_engine

# Custom Dark Theme CSS with Sunrise Golden, Amber, and Emerald accents
st.markdown("""
<style>
    .reportview-container { background-color: #0b0f17; }
    .main-header {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(90deg, #f59e0b, #fbbf24, #10b981);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
    }
    .metric-card {
        background: #131b26;
        border-radius: 10px;
        padding: 14px 18px;
        border: 1px solid #1f2d3d;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.4);
    }
    .phase-card {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.08), rgba(16, 185, 129, 0.06));
        border: 1px solid rgba(245, 158, 11, 0.3);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 16px;
    }
    .metric-title { font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; }
    .metric-val { font-size: 22px; font-weight: 700; color: #f8fafc; margin-top: 4px; }
    .status-badge {
        display: inline-block;
        padding: 5px 14px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }
    .badge-cyan { background-color: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3); }
    .badge-amber { background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
    .badge-purple { background-color: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }
    .badge-green { background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
</style>
""", unsafe_allow_html=True)

# Initialize Engine singleton
engine = get_engine()
telemetry = engine.get_telemetry()
acc = telemetry.get("account", {})
ind = telemetry.get("indicators", {})
positions = telemetry.get("open_positions", [])
phase = telemetry.get("phase", "SCANNING")
armed_dir = telemetry.get("armed_direction")
curr_price = telemetry.get("price", 0.0)
curr_ask = telemetry.get("ask", 0.0)
curr_bid = telemetry.get("bid", 0.0)
symbol = telemetry.get("symbol", "XAUUSD")

# ── Sidebar Controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🌅 Bot #1 Sunrise Controls")
    
    # Auto-trading toggle
    auto_trade = st.toggle("⚡ Master Auto-Pilot", value=engine.config.get("auto_trading", True))
    if auto_trade != engine.config.get("auto_trading", True):
        engine.config["auto_trading"] = auto_trade
        engine.save_config({"auto_trading": auto_trade})
        st.toast(f"Auto-trading {'ENABLED' if auto_trade else 'PAUSED'}")

    # Trading Direction
    mode_options = ["BOTH", "LONG_ONLY", "SHORT_ONLY"]
    curr_mode = engine.config.get("trading_mode", "BOTH")
    idx = mode_options.index(curr_mode) if curr_mode in mode_options else 0
    sel_mode = st.selectbox("Trading Direction", mode_options, index=idx)
    if sel_mode != curr_mode:
        engine.config["trading_mode"] = sel_mode
        engine.save_config({"trading_mode": sel_mode})
        st.toast(f"Trading Direction: {sel_mode}")

    # Lot size
    lot_size = st.number_input("Order Lot Size", min_value=0.01, max_value=1.0, value=float(engine.config.get("lot_size", 0.01)), step=0.01)
    if lot_size != engine.config.get("lot_size"):
        engine.config["lot_size"] = lot_size
        engine.save_config({"lot_size": lot_size})

    st.markdown("---")
    st.markdown("#### ⚙️ Strategy Fine-Tuning")
    strat_cfg = engine.config.get("strategy", {})
    pullback_max = st.slider("Pullback Candles Depth", min_value=1, max_value=5, value=int(strat_cfg.get("long_pullback_max_candles", 3)))
    win_periods = st.slider("Breakout Window Bars", min_value=2, max_value=10, value=int(strat_cfg.get("long_entry_window_periods", 5)))
    sl_atr = st.slider("Stop Loss ATR Multiplier", min_value=1.5, max_value=8.0, value=float(strat_cfg.get("long_atr_sl_multiplier", 4.5)), step=0.5)
    tp_atr = st.slider("Take Profit ATR Multiplier", min_value=2.0, max_value=15.0, value=float(strat_cfg.get("long_atr_tp_multiplier", 6.5)), step=0.5)

    if (pullback_max != strat_cfg.get("long_pullback_max_candles") or
        win_periods != strat_cfg.get("long_entry_window_periods") or
        sl_atr != strat_cfg.get("long_atr_sl_multiplier") or
        tp_atr != strat_cfg.get("long_atr_tp_multiplier")):
        strat_cfg["long_pullback_max_candles"] = pullback_max
        strat_cfg["long_entry_window_periods"] = win_periods
        strat_cfg["long_atr_sl_multiplier"] = sl_atr
        strat_cfg["long_atr_tp_multiplier"] = tp_atr
        engine.save_config({"strategy": strat_cfg})
        st.toast("Updated Strategy Parameters!")

    st.markdown("---")
    if st.button("🚨 Emergency Close All", use_container_width=True):
        engine.close_all_trades()
        st.toast("Closed all positions and reset to SCANNING!")

# ── Main Header ───────────────────────────────────────────────────────────────
col_title, col_status = st.columns([3, 1])
with col_title:
    st.markdown('<div class="main-header">🌅 Sunrise Ogle Trading System — Bot #1</div>', unsafe_allow_html=True)
    st.caption(f"MT5 Bridge Port 8001 | Exness Real ({acc.get('login', 'Connected')}) | Asset: {symbol} (5M)")

with col_status:
    if phase == "SCANNING":
        badge_html = '<span class="status-badge badge-cyan">🔍 1. SCANNING CROSSOVER</span>'
    elif phase == "ARMED":
        badge_html = f'<span class="status-badge badge-amber">⚠️ 2. ARMED ({armed_dir})</span>'
    elif phase == "WINDOW_OPEN":
        badge_html = f'<span class="status-badge badge-purple">🚪 3. BREAKOUT WINDOW OPEN</span>'
    else:
        badge_html = '<span class="status-badge badge-green">🚀 4. IN POSITION (TRAILING)</span>'
    st.markdown(f"<div style='text-align: right; padding-top: 10px;'>{badge_html}</div>", unsafe_allow_html=True)

# ── Metric HUD ────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Live {symbol} Price</div>
        <div class="metric-val">{curr_price:.2f}</div>
        <div style="font-size: 12px; color: #94a3b8;">Bid: {curr_bid:.2f} | Ask: {curr_ask:.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    ema_f = ind.get("ema_fast", 0.0)
    ema_s = ind.get("ema_slow", 0.0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Multi-EMA Hierarchy</div>
        <div class="metric-val">{ema_f:.1f} <span style="font-size: 14px; color: #94a3b8;">/ {ema_s:.1f}</span></div>
        <div style="font-size: 12px; color: #38bdf8;">EMA14 vs EMA24 | 100Filter: {ind.get('ema_filter', 0.0):.1f}</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">ATR Volatility & RSI</div>
        <div class="metric-val">{ind.get('atr', 0.0):.2f} <span style="font-size: 14px; color: #94a3b8;">ATR</span></div>
        <div style="font-size: 12px; color: #a78bfa;">RSI (14): {ind.get('rsi', 0.0):.1f}</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    bal = float(acc.get("balance", 0.0))
    eq = float(acc.get("equity", 0.0))
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Exness Account Balance</div>
        <div class="metric-val">${bal:.2f} <span style="font-size: 12px; color: #10b981;">USC</span></div>
        <div style="font-size: 12px; color: #10b981;">Equity: ${eq:.2f} | Leverage: 1:{acc.get('leverage', 2000)}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

# ── 4-Phase State Machine HUD ──────────────────────────────────────────────────
p_level = telemetry.get("breakout_level")
p_count = telemetry.get("pullback_candle_count", 0)

st.markdown(f"""
<div class="phase-card">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <span style="font-size: 13px; font-weight: 700; color: #fbbf24; text-transform: uppercase;">
                ⚡ 4-Phase Volatility Expansion State Machine
            </span>
            <div style="font-size: 14px; color: #f8fafc; margin-top: 4px;">
                Current Phase: <b>{phase}</b> &nbsp;|&nbsp; 
                Armed Direction: <b>{armed_dir or 'None'}</b> &nbsp;|&nbsp; 
                Pullback Candles: <b>{p_count}</b> &nbsp;|&nbsp; 
                Breakout Trigger: <b>{f'{p_level:.2f}' if p_level else 'Awaiting Window'}</b>
            </div>
        </div>
        <div style="font-size: 12px; color: #94a3b8;">
            Trades Today: <b>{telemetry.get('trades_today', 0)}</b> &nbsp;|&nbsp; 
            Auto-Pilot: <b>{'ON' if telemetry.get('auto_trading') else 'OFF'}</b>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Interactive Candlestick Chart ─────────────────────────────────────────────
candles_df = telemetry.get("candles")
if candles_df is not None and not candles_df.empty:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=candles_df["timestamp"],
            open=candles_df["open"],
            high=candles_df["high"],
            low=candles_df["low"],
            close=candles_df["close"],
            name="XAUUSD 5M",
            increasing_line_color="#10b981",
            decreasing_line_color="#ef4444"
        ),
        row=1, col=1
    )

    # Multi-EMA lines
    if "ema_fast" in candles_df.columns:
        fig.add_trace(go.Scatter(x=candles_df["timestamp"], y=candles_df["ema_fast"], line=dict(color="#06b6d4", width=1.5), name="Fast EMA (14)"), row=1, col=1)
    if "ema_slow" in candles_df.columns:
        fig.add_trace(go.Scatter(x=candles_df["timestamp"], y=candles_df["ema_slow"], line=dict(color="#a855f7", width=1.5), name="Slow EMA (24)"), row=1, col=1)
    if "ema_filter" in candles_df.columns:
        fig.add_trace(go.Scatter(x=candles_df["timestamp"], y=candles_df["ema_filter"], line=dict(color="#f59e0b", width=1.5, dash="dot"), name="Trend Filter (100)"), row=1, col=1)

    # Breakout level trigger line
    if p_level is not None and p_level > 0:
        fig.add_hline(y=p_level, line_dash="dash", line_color="#fbbf24", annotation_text=f"Breakout Level ({p_level:.2f})", annotation_position="top right", row=1, col=1)

    # RSI
    if "rsi" in candles_df.columns:
        fig.add_trace(go.Scatter(x=candles_df["timestamp"], y=candles_df["rsi"], line=dict(color="#38bdf8", width=1.5), name="RSI (14)"), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(239, 68, 68, 0.4)", row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="rgba(16, 185, 129, 0.4)", row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=520,
        margin=dict(l=10, r=10, t=20, b=20),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#0d131d",
        plot_bgcolor="#0d131d",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Active Positions Table ─────────────────────────────────────────────────────
st.markdown("### 📋 Active Open Positions")
if len(positions) > 0:
    rows = []
    for p in positions:
        ticket = p.get("ticket")
        p_type = p.get("type", "BUY")
        open_price = float(p.get("open_price", p.get("price_open", 0.0)))
        profit = float(p.get("profit", 0.0))
        sl = float(p.get("sl", 0.0))
        tp = float(p.get("tp", 0.0))
        lots = float(p.get("volume", 0.01))
        rows.append({
            "Ticket": ticket,
            "Symbol": p.get("symbol", symbol),
            "Type": p_type,
            "Lots": lots,
            "Open Price": f"{open_price:.2f}",
            "Stop Loss": f"{sl:.2f}" if sl > 0 else "None",
            "Take Profit": f"{tp:.2f}" if tp > 0 else "None",
            "Profit (USC)": f"${profit:+.2f}"
        })
    df_pos = pd.DataFrame(rows)
    st.dataframe(df_pos, use_container_width=True, hide_index=True)

    # Individual close buttons
    c_btn_cols = st.columns(len(positions))
    for i, p in enumerate(positions):
        with c_btn_cols[i]:
            if st.button(f"Close #{p.get('ticket')}", key=f"close_{p.get('ticket')}"):
                engine.bridge.close_position(p.get("ticket"))
                st.toast(f"Closed Ticket #{p.get('ticket')}")
else:
    st.info("No active positions currently open. Bot 1 is actively monitoring M5 market structure.")

# Refresh every 3 seconds
time.sleep(3)
st.rerun()
