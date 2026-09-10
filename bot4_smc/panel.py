"""
Bot #4 — Institutional SMC Liquidity Hunter Web Panel
======================================================
Port: 8504
Connects to MT5 Bridge Port 8004
Visualizes:
- Live Candlestick Chart with SMC Liquidity Pools (PDH, PDL, Asian Range, BSL/SSL)
- Fair Value Gap (FVG) Shaded Imbalance Zones
- Active Reversal Trades & Dynamic Breakeven/Trailing Stop Monitor
- Real-time Account Telemetry & Emergency Controls
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
    page_title="Profity AI — Bot #4 SMC Liquidity Hunter",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Ensure local imports work cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from smc_engine import get_engine
from analytics import calculate_performance_metrics

# Custom Dark Theme CSS with Emerald & Cyan accents
st.markdown("""
<style>
    .reportview-container { background-color: #0b0f17; }
    .main-header {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(90deg, #10b981, #06b6d4);
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
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge-amber { background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-cyan { background-color: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3); }
</style>
""", unsafe_allow_html=True)

engine = get_engine()

# Read-only telemetry: Autonomous execution runs strictly in background daemon
status = engine.get_telemetry()

# Sidebar: Controls & Configuration
with st.sidebar:
    st.markdown("### 🎯 Bot #4 SMC Controls")
    
    # Auto-trading toggle
    auto_trade = st.toggle("⚡ Auto-Trading Active", value=status.get("auto_trading", True))
    if auto_trade != engine.config.get("auto_trading", True):
        engine.config["auto_trading"] = auto_trade
        st.toast(f"Auto-trading {'ENABLED' if auto_trade else 'PAUSED'}")

    st.markdown("---")
    st.markdown("#### ⚙️ Strategy Risk Settings")
    
    risk_pct = st.slider("Risk Per Trade (%)", min_value=0.25, max_value=3.0, value=float(engine.config.get("risk_pct_per_trade", 1.0)), step=0.25)
    engine.config["risk_pct_per_trade"] = risk_pct

    max_daily_risk = st.slider("Max Daily Risk (%)", min_value=1.0, max_value=6.0, value=float(engine.config.get("max_daily_risk_pct", 3.0)), step=0.5)
    engine.config["max_daily_risk_pct"] = max_daily_risk

    strat_cfg = engine.config.get("strategy", {})
    min_wick = st.slider("Min Rejection Wick Ratio", min_value=0.25, max_value=0.60, value=float(strat_cfg.get("min_wick_ratio", 0.38)), step=0.01)
    strat_cfg["min_wick_ratio"] = min_wick

    fvg_min = st.number_input("Min FVG Size (Pips)", min_value=1.0, max_value=20.0, value=float(strat_cfg.get("fvg_min_pips", 3.5)), step=0.5)
    strat_cfg["fvg_min_pips"] = fvg_min

    tp1_rr = st.number_input("TP1 R:R Target", min_value=1.0, max_value=4.0, value=float(strat_cfg.get("tp1_rr", 1.5)), step=0.25)
    strat_cfg["tp1_rr"] = tp1_rr

    tp2_rr = st.number_input("TP2 Runner R:R", min_value=2.0, max_value=8.0, value=float(strat_cfg.get("tp2_rr", 3.5)), step=0.5)
    strat_cfg["tp2_rr"] = tp2_rr

    st.markdown("---")
    st.markdown("#### 🚨 Emergency Controls")
    if st.button("🛑 EMERGENCY CLOSE ALL", type="primary", use_container_width=True):
        res = engine.emergency_close_all()
        st.error("Emergency kill switch activated. All Bot #4 positions closed.")

    st.markdown("---")
    st.caption(f"MT5 Bridge: {engine.config.get('bridge_url')} | Magic: {engine.config.get('magic_number')}")


# ── Top Header & KPI Bar ─────────────────────────────────────────────────────
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.markdown('<p class="main-header">🎯 Profity AI — Bot #4: Institutional SMC Liquidity Hunter</p>', unsafe_allow_html=True)
    st.caption("Strategy: Linda Raschke's 'Turtle Soup' + Institutional SMC 2022 Fair Value Gap Reversal Engine")

with col_h2:
    is_conn = status.get("connected", False)
    badge_cls = "badge-green" if is_conn else "badge-red"
    label = f"BRIDGE ONLINE: #{status.get('login')}" if is_conn else "BRIDGE OFFLINE"
    st.markdown(f'<div style="text-align: right; padding-top: 10px;"><span class="status-badge {badge_cls}">{label}</span></div>', unsafe_allow_html=True)

# Metric Cards
m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)

balance = float(status.get("balance", 1000.0))
equity = float(status.get("equity", 1000.0))
daily_pnl = float(status.get("daily_pnl", 0.0))
metrics = status.get("metrics", {})
win_rate = metrics.get("win_rate", 0.0)
profit_factor = metrics.get("profit_factor", 0.0)
daily_trades = status.get("daily_trades_count", 0)

with m_col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Account Balance</div>
        <div class="metric-val">${balance:,.2f}</div>
        <div class="metric-sub" style="color: #94a3b8;">Equity: ${equity:,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with m_col2:
    pnl_color = "#34d399" if daily_pnl >= 0 else "#f87171"
    sign = "+" if daily_pnl > 0 else ""
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Today's PnL</div>
        <div class="metric-val" style="color: {pnl_color};">{sign}${daily_pnl:,.2f}</div>
        <div class="metric-sub" style="color: #94a3b8;">Trades Today: {daily_trades}</div>
    </div>
    """, unsafe_allow_html=True)

with m_col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Win Rate (SMC)</div>
        <div class="metric-val" style="color: #22d3ee;">{win_rate:.1f}%</div>
        <div class="metric-sub" style="color: #94a3b8;">Total Wins: {metrics.get('wins', 0)} / {metrics.get('total_trades', 0)}</div>
    </div>
    """, unsafe_allow_html=True)

with m_col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Profit Factor</div>
        <div class="metric-val" style="color: #a78bfa;">{profit_factor:.2f}</div>
        <div class="metric-sub" style="color: #94a3b8;">Avg R:R: 1:{metrics.get('avg_rr', 0.0):.1f}</div>
    </div>
    """, unsafe_allow_html=True)

with m_col5:
    pools = status.get("liquidity_pools", {})
    a_high = pools.get("asian_high", 0.0)
    a_low = pools.get("asian_low", 0.0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Asian Range</div>
        <div class="metric-val" style="font-size: 18px; color: #f59e0b;">{a_high:.1f} / {a_low:.1f}</div>
        <div class="metric-sub" style="color: #94a3b8;">Range: {pools.get('asian_range_pips', 0.0)} pips</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Main Candlestick Chart with SMC Liquidity & FVG Overlays ─────────────────
st.markdown("### 📊 Institutional Liquidity & Fair Value Gap (FVG) Radar")

symbol = status.get("symbol", "XAUUSD")
candles_df = engine.bridge.get_candles(symbol=symbol, timeframe="5m", limit=75)

if not candles_df.empty:
    fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

    # 1. Candlestick series
    fig.add_trace(go.Candlestick(
        x=candles_df["timestamp"],
        open=candles_df["open"],
        high=candles_df["high"],
        low=candles_df["low"],
        close=candles_df["close"],
        name="XAUUSD M5",
        increasing_line_color="#10b981",
        decreasing_line_color="#ef4444"
    ))

    # 2. Liquidity Pool Lines
    pdh = pools.get("pdh", 0.0)
    pdl = pools.get("pdl", 0.0)
    if pdh > 0:
        fig.add_hline(y=pdh, line_dash="dash", line_color="#ef4444", annotation_text=f"PDH (Buy-Side Liquidity) @ {pdh:.2f}", annotation_position="top right")
    if pdl > 0:
        fig.add_hline(y=pdl, line_dash="dash", line_color="#10b981", annotation_text=f"PDL (Sell-Side Liquidity) @ {pdl:.2f}", annotation_position="bottom right")

    if a_high > 0:
        fig.add_hline(y=a_high, line_dash="dot", line_color="#a855f7", annotation_text=f"Asian High @ {a_high:.2f}", annotation_position="top left")
    if a_low > 0:
        fig.add_hline(y=a_low, line_dash="dot", line_color="#a855f7", annotation_text=f"Asian Low @ {a_low:.2f}", annotation_position="bottom left")

    # 3. Fair Value Gaps (Shaded Rectangles)
    active_fvgs = status.get("active_fvgs", [])
    for fvg in active_fvgs[-4:]:
        fvg_color = "rgba(16, 185, 129, 0.20)" if fvg["type"] == "BULLISH_FVG" else "rgba(239, 68, 68, 0.20)"
        fvg_border = "#10b981" if fvg["type"] == "BULLISH_FVG" else "#ef4444"
        fig.add_hrect(
            y0=fvg["bottom"], y1=fvg["top"],
            fillcolor=fvg_color,
            line_color=fvg_border,
            line_width=1,
            annotation_text=f"{fvg['type']} ({fvg['size_pips']}p)",
            annotation_position="right"
        )

    # 4. Open Position Lines
    open_pos = status.get("open_positions", [])
    for pos in open_pos:
        entry_p = float(pos.get("open_price", pos.get("price_open", 0.0)))
        sl_p = float(pos.get("sl", 0.0))
        tp_p = float(pos.get("tp", 0.0))
        if entry_p > 0:
            fig.add_hline(y=entry_p, line_color="#38bdf8", line_width=2, annotation_text=f"OPEN ENTRY @ {entry_p:.2f}")
        if sl_p > 0:
            fig.add_hline(y=sl_p, line_color="#dc2626", line_dash="dot", line_width=1.5, annotation_text=f"SL @ {sl_p:.2f}")
        if tp_p > 0:
            fig.add_hline(y=tp_p, line_color="#22c55e", line_dash="dot", line_width=1.5, annotation_text=f"TP @ {tp_p:.2f}")

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0b0f17",
        plot_bgcolor="#0b0f17",
        xaxis_rangeslider_visible=False,
        height=480,
        margin=dict(l=20, r=60, t=30, b=20),
        legend=dict(orientation="h", y=1.05, x=0.0)
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Loading live market data feed...")

# ── Active Trades & Signal Radar ─────────────────────────────────────────────
col_pos, col_radar = st.columns([1.5, 1])

with col_pos:
    st.markdown("#### 💼 Active SMC Positions")
    open_pos = status.get("open_positions", [])
    if open_pos:
        for p in open_pos:
            ticket = p.get("ticket")
            p_type = p.get("type")
            vol = p.get("volume")
            open_p = p.get("open_price", p.get("price_open"))
            cur_p = p.get("current_price", p.get("price_current", open_p))
            profit = p.get("profit", 0.0)
            sl_val = p.get("sl", 0.0)
            tp_val = p.get("tp", 0.0)

            p_color = "#34d399" if profit >= 0 else "#f87171"
            p_sign = "+" if profit > 0 else ""

            card_html = f"""
            <div style="background: #151d2a; border-radius: 8px; padding: 12px 16px; border: 1px solid #223249; margin-bottom: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; color: #f8fafc;">#{ticket} — {p_type} {vol} Lots</span>
                    <span style="font-weight: 700; color: {p_color}; font-size: 16px;">{p_sign}${profit:.2f}</span>
                </div>
                <div style="font-size: 12px; color: #94a3b8; margin-top: 4px;">
                    Open: <b>{open_p:.2f}</b> | Cur: <b>{cur_p:.2f}</b> | SL: <b>{sl_val:.2f}</b> | TP: <b>{tp_val:.2f}</b>
                </div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)
            if st.button(f"Close #{ticket}", key=f"close_{ticket}"):
                engine.bridge.close_position(ticket)
                st.rerun()
    else:
        st.markdown('<div style="background: #111827; border-radius: 8px; padding: 18px; text-align: center; color: #64748b;">No active positions. Scanning institutional liquidity pools...</div>', unsafe_allow_html=True)

with col_radar:
    st.markdown("#### 🎯 Active Liquidity & Signal Radar")
    swept = status.get("swept_level")
    if swept:
        st.markdown(f"""
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 8px; padding: 12px;">
            <div style="font-weight: 700; color: #34d399;">🎯 ACTIVE LIQUIDITY SWEEP</div>
            <div style="font-size: 12px; color: #cbd5e1; margin-top: 4px;">
                Direction: <b>{swept.get('direction')}</b><br>
                Target Level: <b>{swept.get('level_name')} @ {swept.get('level_price')}</b><br>
                Sweep Extreme: <b>{swept.get('sweep_extreme')}</b><br>
                Absorption Wick Ratio: <b>{swept.get('wick_ratio') * 100:.0f}%</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown('<div style="background: #111827; border-radius: 8px; padding: 14px; color: #64748b; font-size: 12px;">Waiting for price to sweep key liquidity pool (PDH/PDL or Asian High/Low) with absorption wick...</div>', unsafe_allow_html=True)

    # Active FVG Box
    fvgs = status.get("active_fvgs", [])
    if fvgs:
        latest_fvg = fvgs[-1]
        st.markdown(f"""
        <div style="background: #151d2a; border-radius: 8px; padding: 12px; border: 1px solid #223249; margin-top: 8px;">
            <div style="font-size: 11px; color: #94a3b8; font-weight: 700;">LATEST FAIR VALUE GAP (FVG)</div>
            <div style="font-size: 12px; color: #f8fafc; margin-top: 2px;">
                Type: <b>{latest_fvg.get('type')}</b> ({latest_fvg.get('size_pips')} pips)<br>
                Zone: <b>{latest_fvg.get('bottom'):.2f} - {latest_fvg.get('top'):.2f}</b><br>
                Consequent Encroachment (50%): <b>{latest_fvg.get('midpoint'):.2f}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Auto Refresh ─────────────────────────────────────────────────────────────
time.sleep(3)
st.rerun()
