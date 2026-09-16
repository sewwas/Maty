"""
Bot #6 — FVG Crossfire Web Panel
======================================================
Port: 8506
Connects to MT5 Bridge Port 8006
"""

import os
import sys
import time
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Set page configuration
st.set_page_config(
    page_title="Profity AI — Bot #6 FVG Crossfire",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Dark Theme CSS
st.markdown("""
<style>
    .reportview-container { background-color: #0b0f17; }
    .main-header {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(90deg, #14b8a6, #3b82f6, #8b5cf6);
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
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 600;
    }
    .badge-green { background-color: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-red { background-color: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">Bot #6 — FVG Crossfire Dashboard</div>', unsafe_allow_html=True)
st.markdown("<p style='color: #94a3b8; font-size: 14px; margin-top: -5px;'>3-Signal Confluence (FVG + POC + Crossfire Zone) • Connected to Port 8006</p>", unsafe_allow_html=True)

# Fetch Data from Bridge
BRIDGE_URL = "http://127.0.0.1:8006"

def fetch_data(endpoint):
    try:
        r = requests.get(f"{BRIDGE_URL}/{endpoint}", timeout=2.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

account = fetch_data("account") or {}
positions = fetch_data("positions") or []
pos_list = positions.get("positions", []) if isinstance(positions, dict) else positions

# Sidebar
with st.sidebar:
    st.markdown("### 🔥 Bot #6 Controls")
    if not account:
        st.error("Bridge Disconnected. Please ensure start_bridges.sh/bat is running for Bot 6.")
    else:
        st.success(f"Bridge Connected: {account.get('server', 'MT5')}")

    st.markdown("---")
    st.markdown("#### ⚙️ Quick Actions")
    if st.button("Close All Bot 6 Positions", use_container_width=True):
        res = fetch_data("close_all?magic=60000")
        if res and res.get("success"):
            st.toast("Successfully closed all positions.")
        else:
            st.error("Failed to close positions.")

    st.markdown("---")
    st.caption("Refresh rate: 5s. Auto-refresh enabled via Streamlit.")

# Top Metrics
c1, c2, c3, c4 = st.columns(4)
balance = account.get("balance", 0.0)
equity = account.get("equity", 0.0)
margin_free = account.get("margin_free", 0.0)
floating_pnl = equity - balance

with c1:
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Account Balance</div>
            <div class="metric-val">${balance:,.2f}</div>
        </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Live Equity</div>
            <div class="metric-val">${equity:,.2f}</div>
        </div>
    """, unsafe_allow_html=True)
with c3:
    color = "#34d399" if floating_pnl >= 0 else "#f87171"
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Floating PnL</div>
            <div class="metric-val" style="color: {color};">${floating_pnl:,.2f}</div>
        </div>
    """, unsafe_allow_html=True)
with c4:
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Active Positions</div>
            <div class="metric-val">{len(pos_list)} Open</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Active Positions Table
st.markdown("#### Live Active Positions")
if pos_list:
    df_pos = pd.DataFrame(pos_list)
    # Map types
    type_map = {0: "BUY", 1: "SELL"}
    if "type" in df_pos.columns:
        df_pos["Type"] = df_pos["type"].map(type_map).fillna("UNKNOWN")
    
    # Select relevant cols
    cols = {"ticket": "Ticket", "symbol": "Symbol", "Type": "Type", "volume": "Lots", "price_open": "Open", "sl": "SL", "tp": "TP", "price_current": "Current", "profit": "Profit"}
    display_df = df_pos[[c for c in cols.keys() if c in df_pos.columns]].rename(columns=cols)
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("No active positions matching Bot #6 Magic Number (60000). Waiting for FVG setup...")

# Auto refresh trigger (crude implementation for st)
try:
    import time
    time.sleep(5)
    st.rerun()
except Exception:
    pass
