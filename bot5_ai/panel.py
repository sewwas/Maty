"""
Bot #5 — Institutional AI/ML Neural Trader Web Panel
======================================================
Port: 8505
Connects to MT5 Bridge Port 8005
Visualizes:
- ⚙️ Dynamic Strategy Risk Governor (Autonomous Volatility & Regime Modulator)
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
    .risk-hud-card {
        background: linear-gradient(135deg, rgba(236, 72, 153, 0.08), rgba(139, 92, 246, 0.06));
        border: 1px solid rgba(236, 72, 153, 0.25);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 20px;
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
dyn_risk = telemetry.get("dynamic_risk", {})

# ── Sidebar Controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🤖 Bot #5 AI Controls")

    # Auto-trading toggle
    auto_trade = st.toggle("⚡ Auto-Trading Active", value=telemetry.get("auto_trading", True))
    if auto_trade != engine.config.get("auto_trading", True):
        engine.config["auto_trading"] = auto_trade
        engine.save_config({"auto_trading": auto_trade})
        st.toast(f"Bot #5 Auto-trading {'ENABLED' if auto_trade else 'PAUSED'}")

    st.markdown("---")
    st.markdown("#### ⚙️ Strategy Risk Settings")

    # Master Dynamic Risk Toggle
    is_dynamic = st.toggle("🧠 Dynamic AI Auto-Pilot", value=engine.config.get("dynamic_risk_enabled", True), help="When ON, AI continuously modulates Risk %, Stop Loss, Take Profit, and Confidence based on real-time market regimes.")
    if is_dynamic != engine.config.get("dynamic_risk_enabled", True):
        engine.config["dynamic_risk_enabled"] = is_dynamic
        engine.save_config({"dynamic_risk_enabled": is_dynamic})
        st.toast(f"Dynamic Risk Engine {'ACTIVE' if is_dynamic else 'MANUAL OVERRIDE'}")

    if is_dynamic:
        st.caption("✨ *Risk, SL, TP & Confidence are being autonomously managed by the AI engine.*")
        
        base_risk = st.slider("Base Risk Anchor (%)", min_value=0.25, max_value=2.0, value=float(engine.config.get("risk_pct_per_trade", 1.0)), step=0.25)
        ceiling_risk = st.slider("Max Risk Ceiling Cap (%)", min_value=1.0, max_value=3.5, value=float(engine.config.get("max_risk_ceiling_pct", 2.5)), step=0.25)
        max_daily_risk = st.slider("Max Daily Risk Circuit Breaker (%)", min_value=1.0, max_value=6.0, value=float(engine.config.get("max_daily_risk_pct", 3.0)), step=0.5)
        max_pos = st.slider("Max Concurrent Positions", min_value=1, max_value=4, value=int(engine.config.get("max_positions", 2)), step=1)
        
        if (base_risk != engine.config.get("risk_pct_per_trade") or 
            ceiling_risk != engine.config.get("max_risk_ceiling_pct") or 
            max_daily_risk != engine.config.get("max_daily_risk_pct") or 
            max_pos != engine.config.get("max_positions")):
            engine.save_config({
                "risk_pct_per_trade": base_risk,
                "max_risk_ceiling_pct": ceiling_risk,
                "max_daily_risk_pct": max_daily_risk,
                "max_positions": max_pos
            })
            st.toast("Updated Dynamic Risk Bounds!")
    else:
        st.caption("⚠️ *Manual Override Active: Fixed parameters enforced.*")
        fixed_risk = st.slider("Fixed Risk Per Trade (%)", min_value=0.25, max_value=3.0, value=float(engine.config.get("risk_pct_per_trade", 1.0)), step=0.25)
        fixed_sl = st.slider("Stop Loss (x ATR)", min_value=1.0, max_value=3.0, value=float(engine.config.get("strategy", {}).get("atr_sl_multiplier", 1.5)), step=0.1)
        fixed_tp = st.slider("Take Profit (x R:R)", min_value=1.5, max_value=5.0, value=float(engine.config.get("strategy", {}).get("tp_rr", 2.5)), step=0.25)
        fixed_conf = st.slider("Confidence Threshold", min_value=0.50, max_value=0.85, value=float(engine.config.get("confidence_threshold", 0.60)), step=0.05)
        
        strat = engine.config.get("strategy", {})
        if (fixed_risk != engine.config.get("risk_pct_per_trade") or 
            fixed_sl != strat.get("atr_sl_multiplier") or 
            fixed_tp != strat.get("tp_rr") or 
            fixed_conf != engine.config.get("confidence_threshold")):
            strat["atr_sl_multiplier"] = fixed_sl
            strat["tp_rr"] = fixed_tp
            engine.save_config({
                "risk_pct_per_trade": fixed_risk,
                "confidence_threshold": fixed_conf,
                "strategy": strat
            })
            st.toast("Manual Strategy Risk Saved!")

    trailing_active = st.toggle("Dynamic ATR Trailing Stop", value=engine.config.get("strategy", {}).get("trailing_stop_active", True))
    if trailing_active != engine.config.get("strategy", {}).get("trailing_stop_active", True):
        engine.config["strategy"]["trailing_stop_active"] = trailing_active
        engine.save_config({"strategy": engine.config["strategy"]})

    st.markdown("---")
    st.markdown("#### 🕹️ Manual AI Execution")
    manual_lot = st.number_input("Lot Size", min_value=0.01, max_value=2.0, value=0.02, step=0.01)
    col_b, col_s = st.columns(2)
    with col_b:
        if st.button("BUY NOW", use_container_width=True):
            curr_p = float(tick.get("price", 2900.0))
            atr = float(signal.get("atr", 1.5))
            sl_mult = float(dyn_risk.get("atr_sl_multiplier", 1.5))
            tp_rr = float(dyn_risk.get("tp_rr", 2.5))
            res = engine.bridge.open_trade("XAUUSD", "BUY", manual_lot, stop_loss=curr_p - (atr * sl_mult), take_profit=curr_p + (atr * sl_mult * tp_rr), comment="Bot5_Manual_BUY")
            st.toast("BUY Order Dispatched!" if res.get("success") else "Order Failed!")
    with col_s:
        if st.button("SELL NOW", use_container_width=True):
            curr_p = float(tick.get("price", 2900.0))
            atr = float(signal.get("atr", 1.5))
            sl_mult = float(dyn_risk.get("atr_sl_multiplier", 1.5))
            tp_rr = float(dyn_risk.get("tp_rr", 2.5))
            res = engine.bridge.open_trade("XAUUSD", "SELL", manual_lot, stop_loss=curr_p + (atr * sl_mult), take_profit=curr_p - (atr * sl_mult * tp_rr), comment="Bot5_Manual_SELL")
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

# ── 🛡️ Dynamic Strategy Risk Engine HUD ────────────────────────────────────────
is_dyn_active = dyn_risk.get("enabled", True)
mode_label = dyn_risk.get("regime_mode", "🛡️ DYNAMIC AUTONOMOUS RISK")
atr_val = float(signal.get("atr", 1.5))

st.markdown(f"""
<div class="risk-hud-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div style="font-size: 14px; font-weight: 800; color: #f472b6; letter-spacing: 0.5px;">
            ⚙️ DYNAMIC STRATEGY RISK GOVERNOR — {mode_label}
        </div>
        <span class="status-badge {'badge-pink' if is_dyn_active else 'badge-cyan'}">
            {'AUTO-PILOT ACTIVE' if is_dyn_active else 'MANUAL OVERRIDE'}
        </span>
    </div>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
        <div>
            <div class="metric-title">Dynamic Risk Per Trade</div>
            <div class="metric-val" style="color: #ec4899;">{dyn_risk.get('risk_pct', 1.0):.2f}%</div>
            <div class="metric-sub" style="color: #94a3b8;">Base: {engine.config.get('risk_pct_per_trade', 1.0):.2f}%</div>
        </div>
        <div>
            <div class="metric-title">Dynamic Stop Loss Buffer</div>
            <div class="metric-val" style="color: #f43f5e;">{dyn_risk.get('atr_sl_multiplier', 1.5):.2f}x ATR</div>
            <div class="metric-sub" style="color: #94a3b8;">Dist: ${(atr_val * float(dyn_risk.get('atr_sl_multiplier', 1.5))):.2f}</div>
        </div>
        <div>
            <div class="metric-title">Dynamic Take Profit Target</div>
            <div class="metric-val" style="color: #10b981;">{dyn_risk.get('tp_rr', 2.5):.1f}x R:R</div>
            <div class="metric-sub" style="color: #94a3b8;">Target: ${(atr_val * float(dyn_risk.get('atr_sl_multiplier', 1.5)) * float(dyn_risk.get('tp_rr', 2.5))):.2f}</div>
        </div>
        <div>
            <div class="metric-title">Dynamic Confidence Bar</div>
            <div class="metric-val" style="color: #38bdf8;">{float(dyn_risk.get('confidence_threshold', 0.60))*100:.0f}%</div>
            <div class="metric-sub" style="color: #94a3b8;">Signal Conf: {float(signal.get('confidence', 0.0))*100:.0f}%</div>
        </div>
        <div>
            <div class="metric-title">Dynamic Breakeven / Trail</div>
            <div class="metric-val" style="color: #c084fc;">+{dyn_risk.get('be_trigger_rr', 1.0):.1f}R / {dyn_risk.get('trailing_atr_multiplier', 1.2):.1f}x</div>
            <div class="metric-sub" style="color: #94a3b8;">Max Positions: {dyn_risk.get('max_positions', 2)}</div>
        </div>
    </div>
    <div style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
""", unsafe_allow_html=True)

for r in dyn_risk.get("reasons", []):
    st.markdown(f'<span class="status-badge badge-purple" style="font-size: 11px;">🔍 {r}</span>', unsafe_allow_html=True)
st.markdown("</div></div>", unsafe_allow_html=True)

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
    thresh_val = float(dyn_risk.get("confidence_threshold", 0.60)) * 100.0

    st.markdown(f"""
    <div class="metric-card" style="border-left: 4px solid {sig_color};">
        <div class="metric-title">Ensemble Signal Output</div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
            <span style="font-size: 18px; font-weight: 800; color: {sig_color};">{sig_dir}</span>
            <span class="status-badge" style="background: {sig_color}22; color: {sig_color}; border: 1px solid {sig_color}44;">{sig_conf:.0f}% CONF</span>
        </div>
        <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">
            Dynamic Threshold: {thresh_val:.0f}% &bull; {signal.get('timestamp', '')}
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
