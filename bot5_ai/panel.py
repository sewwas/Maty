"""
Bot #5 — Institutional AI/ML Neural Trader Web Panel
======================================================
Port: 8505
Connects to MT5 Bridge Port 8005
Visualizes:
- Live Market Regime Radar (Trending, Ranging, Volatile Breakout, Low Volatility)
- Multi-Model Ensemble Confluence Signal & Confidence Gauge
- Real-time Candlestick Chart with EMA Ribbons & Dynamic Volatility Envelopes
- Active Trades, Trailing Stop Monitor, & Instant Manual Overrides
- Real-time Account Telemetry & Risk Management Controls
"""

import os
import sys
import time
import datetime
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Set page configuration
st.set_page_config(
    page_title="Profity AI — Bot #5 AI/ML Neural Trader",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Ensure local imports work cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from ai_engine import get_engine
from analytics import calculate_performance_metrics

# Custom Dark Theme CSS with Fuchsia, Rose, and Cyan accents
st.markdown("""
<style>
    .reportview-container { background-color: #0b0f17; }
    .main-header {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(90deg, #ec4899, #8b5cf6, #06b6d4);
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
    .metric-title { font-size: 11px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; }
    .metric-val { font-size: 22px; font-weight: 700; color: #f8fafc; margin-top: 4px; }
    .metric-sub { font-size: 12px; margin-top: 2px; }
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-green { background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-pink { background-color: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3); }
    .badge-purple { background-color: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }
    .badge-cyan { background-color: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3); }
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
</style>
""", unsafe_allow_html=True)

engine = get_engine()
telemetry = engine.get_telemetry()
account = telemetry.get("account", {})
tick = telemetry.get("tick", {})
regime = telemetry.get("regime", {})
signal = telemetry.get("signal", {})
positions = telemetry.get("positions", [])
perf = telemetry.get("performance", {})
floating_pnl = telemetry.get("floating_pnl", 0.0)

# ── Sidebar Controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🤖 Bot #5 AI Controls")

    # Auto-trading toggle
    auto_trade = st.toggle("⚡ Auto-Trading Active", value=telemetry.get("auto_trading", True))
    if auto_trade != engine.config.get("auto_trading", True):
        engine.config["auto_trading"] = auto_trade
        st.toast(f"Bot #5 Auto-trading {'ENABLED' if auto_trade else 'PAUSED'}")

    st.markdown("---")
    st.markdown("#### ⚙️ Strategy Risk Settings")

    risk_pct = st.slider("Risk Per Trade (%)", min_value=0.25, max_value=3.0, value=float(engine.config.get("risk_pct_per_trade", 1.0)), step=0.25)
    engine.config["risk_pct_per_trade"] = risk_pct

    conf_thresh = st.slider("Model Confidence Threshold", min_value=0.50, max_value=0.85, value=float(engine.config.get("confidence_threshold", 0.60)), step=0.05)
    engine.config["confidence_threshold"] = conf_thresh

    trailing_active = st.toggle("Dynamic ATR Trailing Stop", value=engine.config.get("strategy", {}).get("trailing_stop_active", True))
    engine.config["strategy"]["trailing_stop_active"] = trailing_active

    st.markdown("---")
    st.markdown("#### 🕹️ Manual AI Execution")
    manual_lot = st.number_input("Lot Size", min_value=0.01, max_value=2.0, value=0.02, step=0.01)
    col_b, col_s = st.columns(2)
    with col_b:
        if st.button("BUY NOW", use_container_width=True):
            curr_p = float(tick.get("price", 2900.0))
            atr = float(signal.get("atr", 1.5))
            res = engine.bridge.open_trade("XAUUSD", "BUY", manual_lot, stop_loss=curr_p - (atr * 1.5), take_profit=curr_p + (atr * 3.0), comment="Bot5_Manual_BUY")
            st.toast("BUY Order Dispatched!" if res.get("success") else "Order Failed!")
    with col_s:
        if st.button("SELL NOW", use_container_width=True):
            curr_p = float(tick.get("price", 2900.0))
            atr = float(signal.get("atr", 1.5))
            res = engine.bridge.open_trade("XAUUSD", "SELL", manual_lot, stop_loss=curr_p + (atr * 1.5), take_profit=curr_p - (atr * 3.0), comment="Bot5_Manual_SELL")
            st.toast("SELL Order Dispatched!" if res.get("success") else "Order Failed!")

    st.markdown("---")
    if positions:
        if st.button("🚨 CLOSE ALL POSITIONS", type="primary", use_container_width=True):
            closed = engine.bridge.close_all_positions()
            st.toast(f"Closed {closed} positions!")

# ── Main Header & KPI Cards ───────────────────────────────────────────────────
col_title, col_status = st.columns([3, 1])
with col_title:
    st.markdown('<div class="main-header">Profity AI — Bot #5 AI/ML Neural Trader</div>', unsafe_allow_html=True)
    st.caption("Deep Ensemble Confluence & Market Regime Intelligence &bull; XAUUSD &bull; Magic: 998875")

with col_status:
    conn = account.get("connected", False)
    status_class = "badge-green" if conn else "badge-red"
    status_text = f"MT5 CONNECTED #{account.get('login', '?')}" if conn else "OFFLINE / SIMULATING"
    st.markdown(f'<div style="text-align: right; margin-top: 8px;"><span class="status-badge {status_class}">{status_text}</span></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Top KPI Metric Row
k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Live Equity</div>
        <div class="metric-val">${account.get('equity', 1000.0):,.2f}</div>
        <div class="metric-sub" style="color: #64748b;">Balance: ${account.get('balance', 1000.0):,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with k2:
    pnl_color = "#34d399" if floating_pnl >= 0 else "#f87171"
    pnl_sign = "+" if floating_pnl > 0 else ""
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Floating P&L</div>
        <div class="metric-val" style="color: {pnl_color};">{pnl_sign}${floating_pnl:,.2f}</div>
        <div class="metric-sub" style="color: #64748b;">{len(positions)} Open Positions</div>
    </div>
    """, unsafe_allow_html=True)

with k3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Live Gold Price</div>
        <div class="metric-val" style="color: #f472b6;">${tick.get('price', 2900.0):,.2f}</div>
        <div class="metric-sub" style="color: #64748b;">Ask: {tick.get('ask', 0.0):.2f} | Bid: {tick.get('bid', 0.0):.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with k4:
    win_rate = perf.get("win_rate", 0.0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">30D Win Rate</div>
        <div class="metric-val" style="color: #38bdf8;">{win_rate:.1f}%</div>
        <div class="metric-sub" style="color: #64748b;">{perf.get('wins', 0)} Wins / {perf.get('total_trades', 0)} Trades</div>
    </div>
    """, unsafe_allow_html=True)

with k5:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Profit Factor</div>
        <div class="metric-val" style="color: #c084fc;">{perf.get('profit_factor', 1.0):.2f}</div>
        <div class="metric-sub" style="color: #64748b;">Sharpe: {perf.get('sharpe_ratio', 0.0):.2f}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── AI Model Intelligence Radar & Signal Matrix ──────────────────────────────
col_regime, col_signal, col_factors = st.columns([1.2, 1.2, 1.6])

with col_regime:
    reg_name = regime.get("name", "RANGING")
    reg_conf = regime.get("confidence", 0.70) * 100.0
    reg_color = regime.get("color", "#38bdf8")
    st.markdown(f"""
    <div class="metric-card" style="border-left: 4px solid {reg_color};">
        <div class="metric-title">Market Regime Radar</div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
            <span style="font-size: 18px; font-weight: 800; color: {reg_color};">{reg_name}</span>
            <span class="status-badge" style="background: {reg_color}22; color: {reg_color}; border: 1px solid {reg_color}44;">{reg_conf:.0f}% CONF</span>
        </div>
        <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">{regime.get('description', '')}</div>
    </div>
    """, unsafe_allow_html=True)

with col_signal:
    sig_dir = signal.get("direction", "NEUTRAL")
    sig_conf = signal.get("confidence", 0.0) * 100.0
    sig_color = "#34d399" if sig_dir == "BUY" else ("#f87171" if sig_dir == "SELL" else "#94a3b8")
    thresh_val = float(engine.config.get("confidence_threshold", 0.60)) * 100.0

    st.markdown(f"""
    <div class="metric-card" style="border-left: 4px solid {sig_color};">
        <div class="metric-title">Ensemble Signal Output</div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
            <span style="font-size: 18px; font-weight: 800; color: {sig_color};">{sig_dir}</span>
            <span class="status-badge" style="background: {sig_color}22; color: {sig_color}; border: 1px solid {sig_color}44;">{sig_conf:.0f}% CONF</span>
        </div>
        <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">
            Execution Threshold: {thresh_val:.0f}% &bull; {signal.get('timestamp', '')}
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_factors:
    factors = signal.get("factors", {})
    st.markdown("""
    <div class="metric-card">
        <div class="metric-title">AI Decision Factors & Confluence</div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;">
    """, unsafe_allow_html=True)
    for k, v in factors.items():
        st.markdown(f'<span class="status-badge badge-cyan" style="font-size: 11px;">{k.upper()}: {v}</span>', unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Live Candlestick & Technical Ribbon Chart ─────────────────────────────────
st.markdown("### 📊 Live Gold Chart & Technical Ribbons")
df = engine._cached_candles
if df is not None and not df.empty:
    chart_df = df.tail(80)

    fig = go.Figure()
    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=chart_df.index,
        open=chart_df["open"],
        high=chart_df["high"],
        low=chart_df["low"],
        close=chart_df["close"],
        name="XAUUSD",
        increasing_line_color="#10b981",
        decreasing_line_color="#ef4444"
    ))

    # EMAs
    if "ema20" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["ema20"], line=dict(color="#f472b6", width=1.5), name="EMA 20"))
    if "ema50" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["ema50"], line=dict(color="#38bdf8", width=1.5), name="EMA 50"))
    if "ema200" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["ema200"], line=dict(color="#a855f7", width=2), name="EMA 200"))

    # Bollinger Bands
    if "bb_upper" in chart_df.columns and "bb_lower" in chart_df.columns:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["bb_upper"], line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"), name="BB Upper"))
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df["bb_lower"], line=dict(color="rgba(255,255,255,0.2)", width=1, dash="dot"), name="BB Lower"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#131b26",
        plot_bgcolor="#0b0f17",
        height=420,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Gathering live market candles...")

# ── Active Positions Table ────────────────────────────────────────────────────
st.markdown("### ⚡ Active AI Positions")
if positions:
    pos_data = []
    for p in positions:
        ticket = p.get("ticket")
        side = "BUY" if p.get("type") == 0 else "SELL"
        pnl = float(p.get("profit", 0.0))
        open_p = float(p.get("open_price", p.get("price_open", 0.0)))
        pos_data.append({
            "Ticket": ticket,
            "Symbol": p.get("symbol", "XAUUSD"),
            "Side": side,
            "Lots": p.get("volume", 0.01),
            "Open Price": f"${open_p:.2f}",
            "Stop Loss": f"${float(p.get('sl', 0.0)):.2f}",
            "Take Profit": f"${float(p.get('tp', 0.0)):.2f}",
            "Floating P&L": f"${pnl:+.2f}"
        })
    pos_df = pd.DataFrame(pos_data)
    st.dataframe(pos_df, use_container_width=True)
else:
    st.caption("No open positions. Bot #5 AI is monitoring for high-confluence setups.")

# Auto refresh every 5 seconds
time.sleep(5)
st.rerun()
