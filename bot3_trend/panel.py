"""
Bot #3 - Smart Martingale Trend Strategy Web Panel
==================================================
Port: 8503
"""

import os
import sys
import time
import datetime
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(
    page_title="Profity AI - Smart Martingale Bot #3",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from trend_engine import get_engine

st.markdown("""
<style>
    .reportview-container { background-color: #0b0e14; }
    .main-header {
        font-size: 26px;
        font-weight: 700;
        background: linear-gradient(90deg, #3b82f6, #9333ea);
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
    .status-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-green { background-color: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
    .badge-amber { background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-blue { background-color: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
</style>
""", unsafe_allow_html=True)

engine = get_engine(start_daemon=False)
status = engine.get_telemetry()
bridge_ok = True if status.get("price", 0) > 0 else False

with st.sidebar:
    st.markdown("### ⚙️ Bot #3 Settings")
    st.markdown(f"**Instance**: Bot #3 (`:8503`)")
    
    st.markdown("---")
    auto_trade = st.toggle("🤖 Auto-Trading Active", value=status.get("auto_trading", True))
    
    st.markdown("#### 🚨 Emergency Controls")
    if st.button("🛑 Close All Trades", width='stretch', type="primary"):
        res = engine.bridge.close_all_positions(status.get("symbol", "XAUUSD"))
        st.toast(f"Closed {res.get('closed_count', 0)} trades!")
        st.rerun()

col_h1, col_h2 = st.columns([3, 2])
with col_h1:
    st.markdown('<p class="main-header">⚡ Profity AI - Bot #3: Smart Martingale</p>', unsafe_allow_html=True)
    st.markdown(f"**Strategy**: Dynamic ATR Grid Spacing + Equity Circuit Breaker + Basket Take Profit")

with col_h2:
    badge_cls = "badge-green" if bridge_ok else "badge-amber"
    badge_txt = "BRIDGE ONLINE (:8003)" if bridge_ok else "BRIDGE STANDBY"
    st.markdown(f"""
    <div style="text-align: right; margin-top: 8px;">
        <span class="status-badge {badge_cls}">{badge_txt}</span>
        <span class="status-badge badge-blue">{"ACTIVE" if status.get("auto_trading") else "PAUSED"}</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

c1, c2, c3, c4 = st.columns(4)

drawdown = status.get("drawdown_pct", 0.0)
dd_color = "#f87171" if drawdown >= (status.get("protect_pct", 15.0) * 0.8) else "#4ade80"

c1.markdown(f"""
<div class="metric-card">
    <div class="metric-title">Price ({status.get("symbol", "XAUUSD")})</div>
    <div class="metric-val">{status.get("price", 0.0):.3f}</div>
</div>
""", unsafe_allow_html=True)

c2.markdown(f"""
<div class="metric-card">
    <div class="metric-title">Trend Filter</div>
    <div class="metric-val">{status.get("trend", "UNKNOWN")}</div>
</div>
""", unsafe_allow_html=True)

c3.markdown(f"""
<div class="metric-card">
    <div class="metric-title">Active Grid Levels</div>
    <div class="metric-val">{status.get("grid_level", 0)}</div>
</div>
""", unsafe_allow_html=True)

c4.markdown(f"""
<div class="metric-card">
    <div class="metric-title">Basket Floating Profit</div>
    <div class="metric-val" style="color: {dd_color};">${status.get("total_profit", 0.0):.2f}</div>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"### Current Account Drawdown: <span style='color:{dd_color}'>{drawdown:.2f}%</span> (Circuit Breaker at {status.get('protect_pct', 15.0)}%)", unsafe_allow_html=True)
