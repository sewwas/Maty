"""
Bot #3 — Smart Money London Breakout & Trend Runner Web Panel
==============================================================
Port: 8503
Connects to MT5 Bridge Port 8003
Visualizes:
- Live Gold Candlestick Chart with Asian Session Box & EMA 50/200
- Active Breakout Orders & Positions
- Real-Time Trailing Stop & Breakeven Monitor
- Risk Configuration & Emergency Kill-Switch
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
    page_title="Profity AI — Bot #3 Trend Runner",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Ensure local imports work cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from trend_engine import get_engine
from analytics import calculate_performance_metrics

# Custom Dark Theme CSS
st.markdown("""
<style>
    .reportview-container { background-color: #0b0e14; }
    .main-header {
        font-size: 26px;
        font-weight: 700;
        background: linear-gradient(90deg, #f59e0b, #e11d48);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
    }
    .metric-card {
        background: #151a23;
        border-radius: 10px;
        padding: 14px 18px;
        border: 1px solid #232936;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }
    .metric-title { font-size: 12px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .metric-val { font-size: 22px; font-weight: 700; color: #f8fafc; margin-top: 4px; }
    .metric-sub { font-size: 12px; margin-top: 2px; }
    .status-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-green { background-color: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge-amber { background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-blue { background-color: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
</style>
""", unsafe_allow_html=True)

engine = get_engine(start_daemon=False)

# Read-only telemetry: Autonomous execution runs strictly in the background daemon
status = engine.get_telemetry()

# Sidebar: Controls & Settings
with st.sidebar:
    st.markdown("### ⚙️ Bot #3 Settings")
    st.markdown(f"**Instance**: Bot #3 (`:8503`)  \n**Bridge**: Port `8003`  \n**Magic**: `{engine.config.get('magic_number', 998873)}`")
    
    st.markdown("---")
    auto_trade = st.toggle("🤖 Auto-Trading Active", value=engine.config.get("auto_trading", True))
    if auto_trade != engine.config.get("auto_trading", True):
        engine.config["auto_trading"] = auto_trade
        engine.save_config()
        st.rerun()

    st.markdown("#### 🛡️ Risk Management (Zero Martingale)")
    risk_pct = st.slider("Risk % per Trade", min_value=0.25, max_value=3.0, value=float(engine.config.get("risk_pct_per_trade", 1.0)), step=0.25)
    if risk_pct != float(engine.config.get("risk_pct_per_trade", 1.0)):
        engine.config["risk_pct_per_trade"] = risk_pct
        engine.save_config()

    tp1_rr = st.slider("Take Profit Target (R:R)", min_value=0.5, max_value=3.0, value=float(engine.config.get("strategy", {}).get("tp1_rr", 1.0)), step=0.1)
    if tp1_rr != float(engine.config.get("strategy", {}).get("tp1_rr", 1.0)):
        engine.config.setdefault("strategy", {})["tp1_rr"] = tp1_rr
        engine.save_config()

    trail_mult = st.slider("Chandelier Trailing ATR Mult", min_value=1.0, max_value=4.0, value=float(engine.config.get("strategy", {}).get("trailing_atr_multiplier", 2.0)), step=0.5)
    if trail_mult != float(engine.config.get("strategy", {}).get("trailing_atr_multiplier", 2.0)):
        engine.config.setdefault("strategy", {})["trailing_atr_multiplier"] = trail_mult
        engine.save_config()

    st.markdown("#### 🌐 Asian Session Volatility Gates")
    curr_max_asian = float(engine.config.get("strategy", {}).get("max_asian_range_pips", 650.0))
    max_asian_val = st.slider(
        "Max Asian Range (pips)",
        min_value=100.0,
        max_value=1200.0,
        value=curr_max_asian,
        step=25.0,
        help="Ceiling for Asian range. Default 650 pips ($65) accounts for Gold volatility at $4,300+."
    )
    if max_asian_val != curr_max_asian:
        engine.config.setdefault("strategy", {})["max_asian_range_pips"] = max_asian_val
        engine.save_config()
        engine.recalculate_asian_range()
        st.rerun()

    curr_bypass = bool(engine.config.get("strategy", {}).get("allow_exhausted_breakouts", False))
    bypass_val = st.toggle(
        "⚡ Bypass Standby (Trade High Volatility)",
        value=curr_bypass,
        help="Enables breakouts even if Asian session range is exhausted."
    )
    if bypass_val != curr_bypass:
        engine.config.setdefault("strategy", {})["allow_exhausted_breakouts"] = bypass_val
        engine.save_config()
        engine.recalculate_asian_range()
        st.rerun()

    current_max = int(engine.config.get("max_trades_per_day", 0))
    trade_opts = [0, 3, 5, 10, 20]
    sel_idx = trade_opts.index(current_max) if current_max in trade_opts else 0
    max_trades_sel = st.selectbox(
        "Daily Executions Limit",
        trade_opts,
        index=sel_idx,
        format_func=lambda x: "Unlimited (No Limit)" if x == 0 else f"{x} Trades Max",
        help="0 = No limits. Bot executes every confirmed breakout setup."
    )
    if max_trades_sel != current_max:
        engine.config["max_trades_per_day"] = max_trades_sel
        engine.save_config()
        st.rerun()

    st.markdown("---")
    st.markdown("#### 🚨 Emergency Controls")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        if st.button("🛑 Close All", width='stretch', type="primary"):
            res = engine.bridge.close_all_positions(engine.config.get("symbol", "XAUUSD"))
            st.toast(f"Closed {res.get('closed_count', 0)} trades!")
            st.rerun()
    with col_c2:
        if st.button("❌ Cancel Orders", width='stretch'):
            res = engine.bridge.cancel_all_orders(engine.config.get("symbol", "XAUUSD"))
            st.toast(f"Cancelled {res.get('cancelled_count', 0)} orders!")
            st.rerun()

# Header
col_h1, col_h2 = st.columns([3, 2])
with col_h1:
    st.markdown('<p class="main-header">⚡ Profity AI — Bot #3: Trend & Breakout Runner</p>', unsafe_allow_html=True)
    st.markdown(f"**Strategy**: London Session Open Volatility Expansion + Multi-Timeframe EMA Trend + ATR Trailing Runner")

with col_h2:
    acc_info = engine.bridge.get_account()
    bridge_ok = engine.bridge.is_healthy() or bool(acc_info.get("connected"))
    badge_cls = "badge-green" if bridge_ok else "badge-amber"
    badge_txt = "BRIDGE ONLINE (:8003)" if bridge_ok else "BRIDGE STANDBY / OFFLINE"
    st.markdown(f"""
    <div style="text-align: right; margin-top: 8px;">
        <span class="status-badge {badge_cls}">{badge_txt}</span>
        <span class="status-badge badge-blue">{status.get('session', 'London Open')}</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Active Safeguard Banners
box_info = status.get("asian_box", {})
if status.get("daily_risk_halt"):
    c_b1, c_b2 = st.columns([5, 1])
    with c_b1:
        st.error("🚨 **DAILY MAX RISK CIRCUIT BREAKER TRIPPED**: Cumulative daily loss limit reached. Auto-trading is paused for today to protect capital.")
    with c_b2:
        if st.button("🔄 Reset Breaker", key="btn_reset_breaker", use_container_width=True):
            engine.reset_circuit_breaker()
            st.rerun()
elif status.get("is_sell_locked"):
    c_b1, c_b2 = st.columns([5, 1])
    with c_b1:
        st.warning("⚠️ **SELL CIRCUIT BREAKER ACTIVE**: 2 consecutive SELL stop-losses detected. SELL entries are locked out for 60 minutes to prevent sideways whip-sawing.")
    with c_b2:
        if st.button("🔄 Clear Lock", key="btn_clear_sell_lock", use_container_width=True):
            engine.reset_circuit_breaker()
            st.rerun()
elif status.get("is_buy_locked"):
    c_b1, c_b2 = st.columns([5, 1])
    with c_b1:
        st.warning("⚠️ **BUY CIRCUIT BREAKER ACTIVE**: 2 consecutive BUY stop-losses detected. BUY entries are locked out for 60 minutes to prevent sideways whip-sawing.")
    with c_b2:
        if st.button("🔄 Clear Lock", key="btn_clear_buy_lock", use_container_width=True):
            engine.reset_circuit_breaker()
            st.rerun()
elif not box_info.get("valid", False) and box_info.get("range_pips", 0) > 0:
    s_cfg = engine.config.get("strategy", {})
    cfg_min_p = float(s_cfg.get("min_asian_range_pips", 15.0))
    cfg_max_p = float(s_cfg.get("max_asian_range_pips", 650.0))
    c_b1, c_b2 = st.columns([5, 1])
    with c_b1:
        st.info(f"⏸️ **ASIAN RANGE STANDBY**: {box_info.get('status')}. Trading is paused today because session volatility is outside optimal breakout parameters ({cfg_min_p:.0f}–{cfg_max_p:.0f} pips). Use sidebar to raise threshold or enable bypass.")
    with c_b2:
        if st.button("⚡ Re-Evaluate", key="btn_reeval_asian", use_container_width=True):
            engine.recalculate_asian_range()
            st.rerun()
elif "BYPASS" in str(box_info.get("status", "")):
    st.warning(f"⚡ **HIGH VOLATILITY BYPASS ENGAGED**: {box_info.get('status')}. Breakout trading remains active despite extended Asian session range.")

# Top KPI Metric Cards
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Balance / Equity</div>
        <div class="metric-val">${status.get('equity', 1000.0):,.2f}</div>
        <div class="metric-sub" style="color: #94a3b8;">Bal: ${status.get('balance', 1000.0):,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with m2:
    price_val = status.get('price', 2900.0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">XAUUSD Live Price</div>
        <div class="metric-val">${price_val:,.2f}</div>
        <div class="metric-sub" style="color: #94a3b8;">Spread: ${(status.get('ask', 0) - status.get('bid', 0)):.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with m3:
    high_b = box_info.get("high", 0.0)
    low_b = box_info.get("low", 0.0)
    box_valid = box_info.get("valid", False)
    box_status = box_info.get("status", "STANDBY")
    status_col = "#4ade80" if box_valid else "#f87171"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Asian Session Range</div>
        <div class="metric-val">${(high_b - low_b):.2f} <span style="font-size:13px; color:#94a3b8;">({box_info.get('range_pips', 0)} pips)</span></div>
        <div class="metric-sub" style="color: {status_col}; font-weight:600;">{box_status}</div>
    </div>
    """, unsafe_allow_html=True)

with m4:
    macro_t = status.get("macro_trend", "NEUTRAL")
    trend_color = "#4ade80" if "BULLISH" in macro_t else ("#f87171" if "BEARISH" in macro_t else "#fbbf24")
    adx_val = status.get("adx", 20.0)
    rsi_val = status.get("rsi", 50.0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Trend & Momentum</div>
        <div class="metric-val" style="color: {trend_color}; font-size: 17px;">{macro_t}</div>
        <div class="metric-sub" style="color: #94a3b8;">ADX: {adx_val:.1f} | RSI: {rsi_val:.1f} | ATR: ${status.get('atr', 2.5):.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with m5:
    today_cnt = status.get("today_trades_count", engine.state.get("today_trades_count", 0))
    max_d = int(engine.config.get("max_trades_per_day", 0))
    limit_badge = f"/ {max_d} max" if max_d > 0 else "(Unlimited / No Limit)"
    limit_color = "#94a3b8" if max_d > 0 else "#4ade80"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Today's Executions</div>
        <div class="metric-val">{today_cnt} <span style="font-size:12px; color:{limit_color}; font-weight:600;">{limit_badge}</span></div>
        <div class="metric-sub" style="color: #4ade80;">Active Trades: {len(status.get('open_positions', []))}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Main Section: Candlestick Chart with Asian Range Box & EMA lines
st.markdown("### 📈 Live Structure & Breakout Visualizer (M5 Gold)")

candles_df = engine._cached_candles if engine._cached_candles is not None else pd.DataFrame()
if not candles_df.empty and len(candles_df) > 10:
    fig = make_subplots(rows=1, cols=1, shared_xaxes=True)

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=candles_df["timestamp"],
        open=candles_df["open"],
        high=candles_df["high"],
        low=candles_df["low"],
        close=candles_df["close"],
        name="XAUUSD M5",
        increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444"
    ))

    # Fast EMA (50) & Slow EMA (200)
    if "ema_fast" in candles_df.columns:
        fig.add_trace(go.Scatter(
            x=candles_df["timestamp"],
            y=candles_df["ema_fast"],
            line=dict(color="#38bdf8", width=1.5),
            name="EMA 50 (Trend)"
        ))
    if "ema_slow" in candles_df.columns:
        fig.add_trace(go.Scatter(
            x=candles_df["timestamp"],
            y=candles_df["ema_slow"],
            line=dict(color="#fbbf24", width=1.5),
            name="EMA 200 (Macro Baseline)"
        ))

    # Asian Box Horizontal Lines
    if high_b > 0 and low_b > 0:
        fig.add_hline(y=high_b, line_dash="dash", line_color="#a855f7", annotation_text=f"Asian High ${high_b:.2f}", annotation_position="top right")
        fig.add_hline(y=low_b, line_dash="dash", line_color="#a855f7", annotation_text=f"Asian Low ${low_b:.2f}", annotation_position="bottom right")

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e131b",
        plot_bgcolor="#0e131b",
        xaxis_rangeslider_visible=False,
        height=480,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, width='stretch')
else:
    st.info("Loading live candlestick stream from bridge / public liquidity feeds...")

# Active Positions & Trade Management Table
st.markdown("### 🎯 Active Position Management & Trailing Runner Tracker")

open_pos = status.get("open_positions", [])
if open_pos:
    tracked_meta = engine.state.get("positions_tracked", {})
    pos_rows = []
    for p in open_pos:
        t_id = str(p.get("ticket"))
        meta = tracked_meta.get(t_id, {})
        stage = meta.get("stage", 0)
        if stage == 4:
            stage_badge = "🚀 Stage 4: Candle Trail Active"
        elif stage == 3:
            stage_badge = "🎯 Stage 3: Runner Active (TP1 Hit)"
        elif stage == 2:
            stage_badge = "🔒 Stage 2: +50% Profit Locked"
        elif stage == 1:
            stage_badge = "🛡️ Stage 1: Zero Risk (BE Locked)"
        else:
            stage_badge = "⏳ Stage 0: Scanning for +0.5R"
        
        pos_rows.append({
            "Ticket": p.get("ticket"),
            "Type": "BUY" if p.get("type", 0) == 0 else "SELL",
            "Lots": p.get("volume"),
            "Open Price": f"${float(p.get('price_open', 0)):.2f}",
            "Current Price": f"${float(p.get('price_current', 0)):.2f}",
            "Stop Loss": f"${float(p.get('sl', 0)):.2f}",
            "Take Profit": f"${float(p.get('tp', 0)):.2f}",
            "Trailing Ladder Status": stage_badge,
            "Floating Profit": f"${float(p.get('profit', 0)):.2f}"
        })
    st.dataframe(pd.DataFrame(pos_rows), width='stretch', hide_index=True)
else:
    st.markdown("""
    <div style="padding:14px 18px; border-radius:8px; background:#121820; border:1px solid #1f2937; color:#94a3b8; font-size:13px; margin-bottom:12px;">
        🛡️ <strong>Zero open positions.</strong> Bot #3 is actively scanning London Open breakouts with strict risk parameters (Magic #998873).
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════════
# PERFORMANCE ANALYTICS, WIN RATE & TRADE HISTORY
# ════════════════════════════════════════════════════════════════════════════════
st.markdown("---")
h_col1, h_col2 = st.columns([3, 1])
with h_col1:
    st.markdown("### 📊 Performance Analytics & Trade History")
with h_col2:
    hist_period = st.selectbox(
        "Lookback Period",
        [1, 7, 30, 90, 365],
        index=2,
        format_func=lambda x: "Last 24 Hours" if x == 1 else (f"Last {x} Days" if x < 365 else "All Time (365d)"),
        key="bot3_period_sel",
        label_visibility="collapsed"
    )

# Fetch reconstructed closed deals
closed_deals = engine.bridge.get_closed_deals(days=hist_period)
metrics = calculate_performance_metrics(closed_deals)

# Account Currency Handling (Standard $ or Exness Cent ¢)
acct_curr = acc_info.get("currency", "USD") if "acc_info" in locals() else "USD"
curr_sym = "¢" if "C" in acct_curr.upper() else "$"

# Top Performance KPI Cards
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)

with kpi1:
    wr_val = metrics["win_rate"]
    wr_color = "#4ade80" if wr_val >= 60 else ("#fbbf24" if wr_val >= 45 else ("#f87171" if metrics["total_trades"] > 0 else "#94a3b8"))
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Win Rate</div>
        <div class="metric-val" style="color:{wr_color};">{wr_val:.1f}%</div>
        <div class="metric-sub" style="color:#94a3b8;">{metrics['winning_trades']}W / {metrics['losing_trades']}L ({metrics['total_trades']} Total)</div>
    </div>
    """, unsafe_allow_html=True)

with kpi2:
    pf_val = metrics["profit_factor"]
    pf_color = "#4ade80" if pf_val >= 1.75 else ("#fbbf24" if pf_val >= 1.0 else ("#f87171" if metrics["total_trades"] > 0 else "#94a3b8"))
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Profit Factor (PF)</div>
        <div class="metric-val" style="color:{pf_color};">{metrics['profit_factor_label']}</div>
        <div class="metric-sub" style="color:#94a3b8;">+Gross: {metrics['gross_profit']:.1f} | -Loss: {metrics['gross_loss']:.1f}</div>
    </div>
    """, unsafe_allow_html=True)

with kpi3:
    net_pnl = metrics["net_profit"]
    pnl_sign = "+" if net_pnl >= 0 else ""
    pnl_color = "#4ade80" if net_pnl > 0 else ("#f87171" if net_pnl < 0 else "#94a3b8")
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Net Realized P&L</div>
        <div class="metric-val" style="color:{pnl_color};">{pnl_sign}{net_pnl:.2f} {curr_sym}</div>
        <div class="metric-sub" style="color:#94a3b8;">Avg Trade: {metrics['avg_trade']:+.2f} {curr_sym}</div>
    </div>
    """, unsafe_allow_html=True)

with kpi4:
    payoff = metrics["payoff_ratio"]
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Risk:Reward / Payoff</div>
        <div class="metric-val" style="color:#38bdf8;">{payoff:.2f}x</div>
        <div class="metric-sub" style="color:#94a3b8;">Avg Win: +{metrics['avg_win']:.2f} | Loss: -{metrics['avg_loss']:.2f}</div>
    </div>
    """, unsafe_allow_html=True)

with kpi5:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Volume & Streaks</div>
        <div class="metric-val">{metrics['total_volume']:.2f} <span style="font-size:14px; color:#94a3b8;">Lots</span></div>
        <div class="metric-sub" style="color:#94a3b8;">Max Streak: {metrics['max_consecutive_wins']}W / {metrics['max_consecutive_losses']}L</div>
    </div>
    """, unsafe_allow_html=True)

# Interactive Cumulative Equity Growth Curve
eq_data = metrics.get("equity_curve", [])
if len(eq_data) > 1:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 📈 Cumulative Net Profit Growth Curve")
    df_eq = pd.DataFrame(eq_data)
    
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(
        x=df_eq["time"],
        y=df_eq["cumulative_pnl"],
        mode="lines+markers",
        line=dict(color="#4ade80", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(74, 222, 128, 0.08)",
        marker=dict(size=6, color="#22c55e"),
        name=f"Net P&L ({curr_sym})"
    ))
    
    # High Water Mark line
    high_water = df_eq["cumulative_pnl"].cummax()
    fig_eq.add_trace(go.Scatter(
        x=df_eq["time"],
        y=high_water,
        mode="lines",
        line=dict(color="#38bdf8", width=1.2, dash="dot"),
        name="Peak Equity Baseline"
    ))
    
    fig_eq.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e131b",
        plot_bgcolor="#0e131b",
        height=280,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(showgrid=True, gridcolor="#1e293b"),
        yaxis=dict(showgrid=True, gridcolor="#1e293b", title=f"Realized P&L ({curr_sym})"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_eq, width='stretch')

# Closed Trades History Table
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"#### 📜 Reconstructed Closed Deals Log ({len(closed_deals)} deals for Magic #{engine.config.get('magic_number', 998873)})")

if closed_deals:
    hist_rows = []
    for d in closed_deals:
        pnl = float(d.get("net_pnl", 0.0))
        pnl_str = f"+{pnl:.2f} {curr_sym}" if pnl >= 0 else f"{pnl:.2f} {curr_sym}"
        hist_rows.append({
            "Close Time": d.get("close_time", "—"),
            "Ticket": d.get("ticket"),
            "Position ID": d.get("position_id"),
            "Symbol": d.get("symbol"),
            "Side": d.get("side"),
            "Lots": f"{float(d.get('volume', 0)):.2f}",
            "Entry Price": f"${float(d.get('open_price', 0)):.2f}",
            "Exit Price": f"${float(d.get('close_price', 0)):.2f}",
            f"Net P&L ({curr_sym})": pnl_str,
            "Comment / Reason": d.get("comment", "") or "Market Deal"
        })
    df_history = pd.DataFrame(hist_rows)
    st.dataframe(df_history, width='stretch', hide_index=True)
else:
    st.markdown("""
    <div style="padding:18px 24px; border-radius:8px; background:#121820; border:1px solid #1f2937; text-align:center; color:#94a3b8; font-size:13px;">
        ℹ️ <strong>No closed trades found for Bot #3 in the selected period.</strong><br>
        As soon as pending breakout orders are filled and closed via TP1, Stop Loss, or ATR Trailing Stop, complete performance metrics and history will populate here automatically.
    </div>
    """, unsafe_allow_html=True)

# Activity Logs & Signals
st.markdown("---")
with st.expander("📋 Engine Activity & Breakout Logs", expanded=False):
    logs = engine.state.get("logs", [])
    if logs:
        for l in reversed(logs[-25:]):
            st.text(l)
    else:
        st.text("No logs recorded yet.")

# Auto-refresh loop every 5 seconds
time.sleep(5)
st.rerun()

