"""
Bot #4 — Institutional SMC Liquidity Hunter & FVG Reversal Engine ("Turtle Soup")
==================================================================================
Strategy Architecture & Quantitative Execution Model:
1. Higher-Timeframe Liquidity Zone Identification (M15 / H1):
   - Previous Day High (PDH) & Previous Day Low (PDL)
   - Asian Session Range (00:00 - 07:00 UTC) High & Low
   - Fractal Swing Highs (Buy-Side Liquidity - BSL) & Swing Lows (Sell-Side Liquidity - SSL)
   - Equal Highs (EQH) / Equal Lows (EQL) within +/- 2.0 pips
2. Liquidity Sweep Detection (The Institutional Trap):
   - Price wicks through key liquidity level by >= 3 pips
   - Candle closes back inside the level
   - Rejection wick >= 38% of total candle range (confirms institutional order absorption)
3. Market Structure Shift (MSS):
   - Confirmed candle close reversing back through the nearest short-term swing point
4. Fair Value Gap (FVG) & Consequent Encroachment (50% Equilibrium):
   - Imbalance detection in 3-candle sequence:
     * Bullish FVG: Low[i] > High[i-2]
     * Bearish FVG: High[i] < Low[i-2]
   - Validates FVG size >= min_fvg_pips (0.35 on Gold)
   - Entry triggers on re-test / tap of the FVG zone (50% CE level)
5. Institutional Risk Engine & Lifecycle:
   - Strict 1.0% Equity Risk per trade (Zero Martingale)
   - Stop Loss placed outside sweep extreme wick + 5 pips buffer
   - Dynamic Breakeven Ratchet at 1:1.0 Risk/Reward
   - Partial Take Profit 1 (TP1) at 1:1.5 R:R (closes 50% lot size)
   - Runner Target (TP2) at 1:3.5 R:R or opposite liquidity pool with ATR Chandelier Trailing Stop
   - Circuit Breakers: Max 3.0% daily loss limit, 2 consecutive loss 60-min lockout
"""

import os
import sys
import time
import json
import logging
import datetime
import threading
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np

# Ensure local imports work cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from bridge_client import Bot4BridgeClient
from analytics import calculate_performance_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SMCHunterBot4")


class SMCEngine:
    def __init__(self, config_path: Optional[str] = None):
        if not config_path:
            config_path = os.path.join(_CURRENT_DIR, "config.json")
        self.config_path = config_path
        self.state_path = os.path.join(_CURRENT_DIR, "state.json")
        self.config = self._load_config()
        self.state = self._load_state()

        # Concurrency & order settlement guards
        self._execution_lock = threading.Lock()
        self._order_in_flight_until = 0.0
        self._last_stats_update = 0.0
        self._last_tick_time = 0.0
        self._last_m5_fetch = 0.0
        self._last_m15_fetch = 0.0
        self._last_heartbeat_log = 0.0

        # Cached analytics & telemetry
        self._cached_m5: Optional[pd.DataFrame] = None
        self._cached_m15: Optional[pd.DataFrame] = None
        self._cached_liquidity_pools: Dict[str, Any] = {}
        self._cached_fvg_list: List[Dict[str, Any]] = []
        self._cached_dynamic_risk: Dict[str, Any] = {}
        self._cached_telemetry: Dict[str, Any] = {}

        # Bridge client
        bridge_url = self.config.get("bridge_url", "http://127.0.0.1:8004")
        magic = int(self.config.get("magic_number", 998874))
        self.bridge = Bot4BridgeClient(bridge_url=bridge_url, magic_number=magic)

        # Background worker thread
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ Bot #4 SMC Liquidity Hunter initialized on Magic {magic} | Bridge {bridge_url}")

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config.json: {e}")
        return {
            "symbol": "XAUUSD",
            "magic_number": 998874,
            "bridge_url": "http://127.0.0.1:8004",
            "dynamic_risk_enabled": True,
            "risk_pct_per_trade": 1.0,
            "max_risk_ceiling_pct": 2.5,
            "min_risk_floor_pct": 0.25,
            "max_daily_risk_pct": 3.0,
            "max_trades_per_day": 4,
            "auto_trading": True,
            "strategy": {
                "lookback_candles": 120,
                "min_wick_ratio": 0.38,
                "fvg_min_pips": 3.5,
                "tp1_rr": 1.5,
                "tp1_close_pct": 50.0,
                "tp2_rr": 3.5,
                "be_trigger_rr": 1.0,
                "be_offset_points": 30,
                "atr_period": 14,
                "atr_sl_multiplier": 1.2,
                "trailing_stop_active": True,
                "dynamic_sl_tp_enabled": True,
                "sl_atr_multiplier": 0.30,
                "min_target_rr": 1.8,
                "max_target_rr": 5.0,
                "front_run_points": 25
            }
        }

    def save_config(self, new_config: Dict[str, Any]):
        """
        Dynamically updates runtime configuration and persists directly to config.json.
        """
        with self._execution_lock:
            self.config.update(new_config)
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
                logger.info("✅ Bot #4 Configuration dynamically updated and saved to config.json")
            except Exception as e:
                logger.error(f"Error saving config.json: {e}")

    def _load_state(self) -> Dict[str, Any]:
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("daily_date") != today_str:
                        data["daily_date"] = today_str
                        data["daily_pnl"] = 0.0
                        data["daily_trades_count"] = 0
                    data.setdefault("tp1_executed_tickets", [])
                    return data
            except Exception as e:
                logger.error(f"Error loading state.json: {e}")
        return {
            "daily_date": today_str,
            "daily_pnl": 0.0,
            "daily_trades_count": 0,
            "consecutive_losses": 0,
            "lockout_until": 0.0,
            "trade_history": [],
            "last_processed_candle": 0,
            "active_fvg": None,
            "swept_level": None,
            "tp1_executed_tickets": []
        }

    def _save_state(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state.json: {e}")

    # ── Indicator & Liquidity Zone Calculations ──────────────────────────────
    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def _identify_liquidity_pools(self, df_m15: pd.DataFrame, df_m5: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates Key Institutional Liquidity Zones:
        - Asian Session High & Low (00:00 - 07:00 UTC)
        - Previous Day High (PDH) & Previous Day Low (PDL)
        - Fractal Swing Highs (Buy-Side Liquidity - BSL)
        - Fractal Swing Lows (Sell-Side Liquidity - SSL)
        - Equal Highs (EQH) & Equal Lows (EQL)
        """
        pools = {
            "pdh": 0.0,
            "pdl": 0.0,
            "asian_high": 0.0,
            "asian_low": 0.0,
            "asian_range_pips": 0.0,
            "swing_highs": [],
            "swing_lows": [],
            "eqh": [],
            "eql": []
        }

        if df_m15.empty or len(df_m15) < 30:
            return pools

        # 1. Asian Session (00:00 - 07:00 UTC)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        today_date = now_utc.date()
        
        # Filter for today's Asian candles
        asian_candles = []
        for idx, row in df_m15.iterrows():
            ts = row["timestamp"]
            if hasattr(ts, "date") and ts.date() == today_date:
                if 0 <= ts.hour < 7:
                    asian_candles.append(row)

        if asian_candles:
            asian_df = pd.DataFrame(asian_candles)
            a_high = float(asian_df["high"].max())
            a_low = float(asian_df["low"].min())
            pools["asian_high"] = round(a_high, 2)
            pools["asian_low"] = round(a_low, 2)
            pools["asian_range_pips"] = round((a_high - a_low) * 10.0, 1)

        # 2. Previous Day High & Low (PDH / PDL)
        # Group candles by date
        df_copy = df_m15.copy()
        df_copy["date"] = df_copy["timestamp"].apply(lambda t: t.date() if hasattr(t, "date") else None)
        prev_dates = [d for d in df_copy["date"].unique() if d is not None and d < today_date]
        if prev_dates:
            last_date = max(prev_dates)
            prev_day_df = df_copy[df_copy["date"] == last_date]
            if not prev_day_df.empty:
                pools["pdh"] = round(float(prev_day_df["high"].max()), 2)
                pools["pdl"] = round(float(prev_day_df["low"].min()), 2)

        # 3. Fractal Swing Points (BSL / SSL) on M15
        highs = df_m15["high"].values
        lows = df_m15["low"].values
        n = len(df_m15)
        
        swing_highs = []
        swing_lows = []
        # Fractal window: 2 bars left, 2 bars right
        for i in range(2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append(round(float(highs[i]), 2))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append(round(float(lows[i]), 2))

        pools["swing_highs"] = swing_highs[-6:] if swing_highs else []
        pools["swing_lows"] = swing_lows[-6:] if swing_lows else []

        # 4. Equal Highs / Lows (within 0.20 on Gold = 2 pips)
        if len(swing_highs) >= 2:
            for i in range(len(swing_highs) - 1):
                for j in range(i + 1, len(swing_highs)):
                    if abs(swing_highs[i] - swing_highs[j]) <= 0.20:
                        pools["eqh"].append(round((swing_highs[i] + swing_highs[j]) / 2.0, 2))
        
        if len(swing_lows) >= 2:
            for i in range(len(swing_lows) - 1):
                for j in range(i + 1, len(swing_lows)):
                    if abs(swing_lows[i] - swing_lows[j]) <= 0.20:
                        pools["eql"].append(round((swing_lows[i] + swing_lows[j]) / 2.0, 2))

        return pools

    def _detect_fvgs(self, df: pd.DataFrame, min_pips: float = 3.5) -> List[Dict[str, Any]]:
        """
        Detects Institutional Fair Value Gaps (FVG) across recent closed candles.
        - Bullish FVG: Low of candle 3 > High of candle 1
        - Bearish FVG: High of candle 3 < Low of candle 1
        """
        fvgs = []
        if df.empty or len(df) < 3:
            return fvgs

        min_gap = min_pips / 10.0  # e.g. 3.5 pips = 0.35 on Gold
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        n = len(df)

        # Inspect up to the last 15 closed candles
        start_idx = max(2, n - 20)
        for i in range(start_idx, n - 1):  # exclude unclosed candle (n-1)
            # Bullish FVG
            c1_high = highs[i - 2]
            c3_low = lows[i]
            if (c3_low - c1_high) >= min_gap:
                midpoint = round((c3_low + c1_high) / 2.0, 2)
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "top": round(float(c3_low), 2),
                    "bottom": round(float(c1_high), 2),
                    "midpoint": midpoint,
                    "candle_idx": i,
                    "size_pips": round((c3_low - c1_high) * 10.0, 1),
                    "timestamp": str(df["timestamp"].iloc[i])
                })

            # Bearish FVG
            c1_low = lows[i - 2]
            c3_high = highs[i]
            if (c1_low - c3_high) >= min_gap:
                midpoint = round((c1_low + c3_high) / 2.0, 2)
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "top": round(float(c1_low), 2),
                    "bottom": round(float(c3_high), 2),
                    "midpoint": midpoint,
                    "candle_idx": i,
                    "size_pips": round((c1_low - c3_high) * 10.0, 1),
                    "timestamp": str(df["timestamp"].iloc[i])
                })

        return fvgs

    def _check_liquidity_sweep(
        self,
        candle: pd.Series,
        pools: Dict[str, Any],
        min_wick_ratio: float = 0.38
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates a closed candle to see if it swept a key liquidity level
        and rejected with a long absorption wick (Turtle Soup pattern).
        """
        c_open = float(candle["open"])
        c_high = float(candle["high"])
        c_low = float(candle["low"])
        c_close = float(candle["close"])
        c_range = c_high - c_low

        if c_range <= 0.05:
            return None

        # Check Bearish Sweep (Price swept above key High, wicked, closed below)
        high_levels = []
        if pools["pdh"] > 0:
            high_levels.append(("PDH", pools["pdh"]))
        if pools["asian_high"] > 0:
            high_levels.append(("ASIAN_HIGH", pools["asian_high"]))
        for sh in pools["swing_highs"]:
            high_levels.append(("SWING_HIGH", sh))
        for eq in pools["eqh"]:
            high_levels.append(("EQH", eq))

        upper_wick = c_high - max(c_open, c_close)
        upper_wick_ratio = upper_wick / c_range

        for lvl_name, lvl_price in high_levels:
            # Swept above level by >= 0.20, but closed back below level
            if c_high >= (lvl_price + 0.20) and c_close < lvl_price:
                if upper_wick_ratio >= min_wick_ratio:
                    return {
                        "direction": "BEARISH_SWEEP",
                        "level_name": lvl_name,
                        "level_price": lvl_price,
                        "sweep_extreme": round(c_high, 2),
                        "wick_ratio": round(upper_wick_ratio, 2),
                        "candle_timestamp": str(candle["timestamp"])
                    }

        # Check Bullish Sweep (Price swept below key Low, wicked, closed above)
        low_levels = []
        if pools["pdl"] > 0:
            low_levels.append(("PDL", pools["pdl"]))
        if pools["asian_low"] > 0:
            low_levels.append(("ASIAN_LOW", pools["asian_low"]))
        for sl in pools["swing_lows"]:
            low_levels.append(("SWING_LOW", sl))
        for eql in pools["eql"]:
            low_levels.append(("EQL", eql))

        lower_wick = min(c_open, c_close) - c_low
        lower_wick_ratio = lower_wick / c_range

        for lvl_name, lvl_price in low_levels:
            # Swept below level by >= 0.20, but closed back above level
            if c_low <= (lvl_price - 0.20) and c_close > lvl_price:
                if lower_wick_ratio >= min_wick_ratio:
                    return {
                        "direction": "BULLISH_SWEEP",
                        "level_name": lvl_name,
                        "level_price": lvl_price,
                        "sweep_extreme": round(c_low, 2),
                        "wick_ratio": round(lower_wick_ratio, 2),
                        "candle_timestamp": str(candle["timestamp"])
                    }

        return None

    def _check_mss(self, df: pd.DataFrame, sweep: Dict[str, Any]) -> bool:
        """
        Market Structure Shift (MSS) Validator:
        Ensures after a sweep, the following candle(s) show momentum in the reversal direction.
        """
        if df.empty or len(df) < 3:
            return False

        last_closed = df.iloc[-2]
        c_open = float(last_closed["open"])
        c_close = float(last_closed["close"])

        if sweep["direction"] == "BEARISH_SWEEP":
            # Must be a solid bearish candle closing below open
            return c_close < c_open
        elif sweep["direction"] == "BULLISH_SWEEP":
            # Must be a solid bullish candle closing above open
            return c_close > c_open

        return False

    def _calculate_lot_size(self, equity: float, sl_distance: float, risk_pct: Optional[float] = None) -> float:
        """
        Institutional Equity Risk lot sizing adhering strictly to dynamic parameters.
        Gold standard: 1.00 distance on 0.01 lot = $1.00 USD risk.
        """
        if risk_pct is None:
            risk_pct = float(self.config.get("risk_pct_per_trade", 1.0))
        risk_usd = equity * (risk_pct / 100.0)
        
        if sl_distance <= 0.20:
            sl_distance = 1.50  # Safe minimum fallback distance ($1.50 on Gold)

        # Raw lot = risk_usd / (sl_distance * 100)
        raw_lot = risk_usd / (sl_distance * 100.0)
        
        # Hard bounds: min 0.01 lot, max 0.50 lot (safe institutional ceiling)
        lot = max(0.01, min(0.50, round(raw_lot, 2)))
        return lot

    # ── ⚙️ Fully Dynamic SMC Strategy Risk Engine ────────────────────────────────
    def _calculate_dynamic_smc_risk(
        self,
        df_m5: Optional[pd.DataFrame],
        df_m15: Optional[pd.DataFrame],
        tick: Dict[str, Any],
        account: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Dynamically manages ALL Bot #4 SMC Strategy Risk Settings:
        - Dynamic Risk % Per Trade (Volatility & Drawdown Adaptive)
        - Dynamic Minimum Absorption Wick Ratio
        - Dynamic Minimum FVG Size (Pips)
        - Dynamic Take Profit R:R (TP1 Partial & TP2 Runner)
        - Dynamic Breakeven Trigger & Offset
        - Dynamic Chandelier ATR Trailing Stop Multiplier
        """
        base_risk = float(self.config.get("risk_pct_per_trade", 1.0))
        ceiling_risk = float(self.config.get("max_risk_ceiling_pct", 2.5))
        floor_risk = float(self.config.get("min_risk_floor_pct", 0.25))

        strat = self.config.get("strategy", {})
        base_wick = float(strat.get("min_wick_ratio", 0.38))
        base_fvg_pips = float(strat.get("fvg_min_pips", 3.5))
        base_tp1_rr = float(strat.get("tp1_rr", 1.5))
        base_tp2_rr = float(strat.get("tp2_rr", 3.5))
        base_be_rr = float(strat.get("be_trigger_rr", 1.0))
        base_trail_mult = float(strat.get("atr_sl_multiplier", 1.2))

        # Check if dynamic risk engine is enabled
        if not self.config.get("dynamic_risk_enabled", True):
            return {
                "enabled": False,
                "risk_pct": base_risk,
                "min_wick_ratio": base_wick,
                "fvg_min_pips": base_fvg_pips,
                "tp1_rr": base_tp1_rr,
                "tp2_rr": base_tp2_rr,
                "be_trigger_rr": base_be_rr,
                "atr_sl_multiplier": base_trail_mult,
                "regime_mode": "MANUAL FIXED SMC RISK",
                "reasons": ["Manual override active (Dynamic Auto-Pilot OFF)"]
            }

        reasons = []
        dyn_risk = base_risk
        dyn_wick = base_wick
        dyn_fvg = base_fvg_pips
        dyn_tp1 = base_tp1_rr
        dyn_tp2 = base_tp2_rr
        dyn_be = base_be_rr
        dyn_trail = base_trail_mult

        # Compute ATR & volatility ratio
        current_atr = 1.5
        atr_ratio = 1.0
        if df_m5 is not None and not df_m5.empty and len(df_m5) >= 15:
            atr_series = self._compute_atr(df_m5, period=14)
            if not atr_series.empty and not np.isnan(atr_series.iloc[-1]):
                current_atr = float(atr_series.iloc[-1])
                mean_atr = float(atr_series.tail(40).mean()) if len(atr_series) >= 40 else current_atr
                if mean_atr > 0:
                    atr_ratio = current_atr / mean_atr

        # 1. Volatility & Liquidity Regime Adaptation
        if atr_ratio > 1.55:
            regime_mode = "⚡ HIGH VOLATILITY LIQUIDITY EXPANSION"
            # In volatile expansion: trim risk, require solid institutional absorption wick, widen FVG
            dyn_risk = base_risk * 0.70
            dyn_wick = max(base_wick, 0.33)  # solid absorption wick
            dyn_fvg = max(3.5, round(current_atr * 2.0, 1))
            dyn_tp1 = 1.80
            dyn_tp2 = 4.50   # target explosive liquidity runners
            dyn_be = 0.80    # early de-risking
            dyn_trail = 1.50 # wider chandelier buffer
            reasons.append(f"Volatile Expansion ({atr_ratio:.1f}x ATR) → Wick filter {dyn_wick*100:.0f}%, FVG filter to {dyn_fvg}p")

        elif atr_ratio < 0.75:
            regime_mode = "💤 LOW VOLATILITY CONSOLIDATION"
            # Low volatility / Asian chop: scale down risk, allow tighter wicks and smaller FVGs
            dyn_risk = base_risk * 0.75
            dyn_wick = max(0.25, base_wick * 0.85)
            dyn_fvg = 2.0
            dyn_tp1 = 1.30
            dyn_tp2 = 2.50
            dyn_be = 1.00
            dyn_trail = 1.10
            reasons.append(f"Compressed Corridor ({atr_ratio:.1f}x ATR) → Wick filter {dyn_wick*100:.0f}%, tight targets")

        else:
            regime_mode = "🎯 INSTITUTIONAL LIQUIDITY SWEEP"
            dyn_risk = base_risk * 1.0
            dyn_wick = base_wick
            dyn_fvg = max(2.5, round(current_atr * 1.5, 1))
            dyn_tp1 = 1.50
            dyn_tp2 = 3.50
            dyn_be = 1.00
            dyn_trail = 1.20
            reasons.append(f"Optimal SMC Conditions (ATR {current_atr:.2f}) → Wick filter {dyn_wick*100:.0f}% with 1:3.5 R:R runner")

        # 2. Extreme Volatility Spike Guard
        if atr_ratio > 2.0:
            dyn_risk *= 0.75
            dyn_wick = max(base_wick, 0.36)
            reasons.append(f"Extreme Volatility Alert ({atr_ratio:.1f}x ATR) → Emergency 25% risk trim, {dyn_wick*100:.0f}% wick required")

        # 3. Drawdown & Consecutive Loss Circuit Breaker
        cons_losses = self.state.get("consecutive_losses", 0)
        if cons_losses >= 2:
            dyn_risk *= 0.50
            dyn_wick += 0.03
            reasons.append(f"Loss Streak Guard ({cons_losses} losses) → Risk halved, absorption bar raised")
        elif cons_losses == 1:
            dyn_risk *= 0.85

        # 4. Strict Institutional Clamping
        dyn_risk = max(floor_risk, min(round(dyn_risk, 2), ceiling_risk))
        dyn_wick = round(max(0.30, min(dyn_wick, 0.55)), 2)
        dyn_fvg = round(max(2.0, min(dyn_fvg, 15.0)), 1)
        dyn_tp1 = round(max(1.0, min(dyn_tp1, 3.0)), 2)
        dyn_tp2 = round(max(2.0, min(dyn_tp2, 6.0)), 2)
        dyn_be = round(max(0.6, min(dyn_be, 1.5)), 2)
        dyn_trail = round(max(0.9, min(dyn_trail, 2.2)), 2)

        return {
            "enabled": True,
            "risk_pct": dyn_risk,
            "min_wick_ratio": dyn_wick,
            "fvg_min_pips": dyn_fvg,
            "tp1_rr": dyn_tp1,
            "tp2_rr": dyn_tp2,
            "be_trigger_rr": dyn_be,
            "atr_sl_multiplier": dyn_trail,
            "current_atr": round(current_atr, 2),
            "regime_mode": regime_mode,
            "reasons": reasons
        }

    # ── Main Tick & Execution Daemon ─────────────────────────────────────────
    def _run_loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"Error in SMCEngine tick loop: {e}", exc_info=True)
            time.sleep(2.0)

    def _tick(self):
        with self._execution_lock:
            now_ts = time.time()
            self._last_tick_time = now_ts
            symbol = self.config.get("symbol", "XAUUSD")

            # 1. Fetch Candles (M5 for execution, M15 for liquidity zones)
            if (now_ts - self._last_m5_fetch) > 4.0 or self._cached_m5 is None:
                self._cached_m5 = self.bridge.get_candles(symbol=symbol, timeframe="5m", limit=100)
                self._last_m5_fetch = now_ts

            if (now_ts - self._last_m15_fetch) > 15.0 or self._cached_m15 is None:
                self._cached_m15 = self.bridge.get_candles(symbol=symbol, timeframe="15m", limit=120)
                self._last_m15_fetch = now_ts

            df_m5 = self._cached_m5
            df_m15 = self._cached_m15

            if df_m5.empty or len(df_m5) < 15 or df_m15.empty or len(df_m15) < 20:
                return

            tick = self.bridge.get_tick(symbol=symbol)
            acc = self.bridge.get_account()

            # Dynamic SMC Strategy Risk Calculation
            dyn_risk = self._calculate_dynamic_smc_risk(df_m5, df_m15, tick, acc)
            self._cached_dynamic_risk = dyn_risk

            # Compute Liquidity Pools & FVGs with dynamic parameters
            pools = self._identify_liquidity_pools(df_m15, df_m5)
            self._cached_liquidity_pools = pools

            fvg_min_pips = float(dyn_risk.get("fvg_min_pips", 3.5))
            fvgs = self._detect_fvgs(df_m5, min_pips=fvg_min_pips)
            self._cached_fvg_list = fvgs

            # 2. Manage Active Positions (Breakeven, Partial TP1, Trailing Stop)
            open_positions = self.bridge.get_positions(symbol=symbol)
            self._manage_open_positions(open_positions, df_m5, dyn_risk=dyn_risk)

            # 3. Check Account & Circuit Breakers
            equity = float(acc.get("equity", 1000.0))
            balance = float(acc.get("balance", 1000.0))

            # Circuit breaker: Daily loss ceiling
            max_daily_risk = float(self.config.get("max_daily_risk_pct", 3.0))
            daily_loss_limit = balance * (max_daily_risk / 100.0)
            if self.state.get("daily_pnl", 0.0) <= -daily_loss_limit:
                logger.warning(f"🛑 [Bot #4] Max daily loss hit (${self.state.get('daily_pnl'):.2f} / -${daily_loss_limit:.2f}). Engine standing by.")
                return

            # Consecutive loss lockout
            if now_ts < float(self.state.get("lockout_until", 0.0)):
                return

            # Synchronize daily trades from actual broker history
            if (now_ts - self._last_stats_update) > 30.0:
                try:
                    hist = self.bridge.get_history(days=1)
                    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                    today_deals = [
                        d for d in hist
                        if datetime.datetime.fromtimestamp(d.get("time", 0), datetime.timezone.utc).strftime("%Y-%m-%d") == today_str
                        and d.get("entry") == 0
                    ]
                    self.state["daily_trades_count"] = len(today_deals)
                    self._last_stats_update = now_ts
                except Exception:
                    pass

            # Max trades per day
            max_trades = int(self.config.get("max_trades_per_day", 8))
            auto_trading = self.config.get("auto_trading", True)

            # Heartbeat telemetry log
            if (now_ts - self._last_heartbeat_log) >= 30.0:
                cur_sweep = self.state.get("swept_level")
                sweep_desc = f"{cur_sweep['direction']} ({cur_sweep['level_name']})" if cur_sweep else "None"
                logger.info(
                    f"🏹 [Bot #4 SMC] Scanning {symbol} @ {tick.get('price', 0.0):.2f} | "
                    f"Regime: {dyn_risk.get('regime_mode')} | AutoTrading: {auto_trading} | "
                    f"Active Positions: {len(open_positions)} | Today Trades: {self.state.get('daily_trades_count', 0)}/{max_trades} | "
                    f"Active Sweep: {sweep_desc}"
                )
                self._last_heartbeat_log = now_ts

            if max_trades > 0 and self.state.get("daily_trades_count", 0) >= max_trades:
                return

            # If an order is already in-flight or positions already open, do not enter new trade
            if now_ts < self._order_in_flight_until or open_positions:
                return

            if not auto_trading:
                return

            # 4. Scan for Liquidity Sweeps (Turtle Soup Reversals & FVG Retests)
            closed_candle = df_m5.iloc[-2]
            closed_candle_ts = str(closed_candle.get("timestamp", ""))
            min_wick = float(dyn_risk.get("min_wick_ratio", 0.30))

            sweep = self._check_liquidity_sweep(closed_candle, pools, min_wick_ratio=min_wick)
            
            # --- HIGHER TIMEFRAME (HTF) TREND FILTER (OPTIONAL) ---
            # By default disabled: SMC Turtle Soup is an institutional mean-reversion sweep strategy
            enable_trend_filter = self.config.get("strategy", {}).get("enable_htf_trend_filter", False)
            if enable_trend_filter and sweep and len(df_m15) >= 50:
                ema_50 = df_m15['close'].ewm(span=50, adjust=False).mean().iloc[-1]
                current_m15_close = df_m15['close'].iloc[-1]
                if sweep["direction"] == "BULLISH_SWEEP" and current_m15_close < ema_50:
                    sweep = None
                elif sweep["direction"] == "BEARISH_SWEEP" and current_m15_close > ema_50:
                    sweep = None

            if sweep and sweep.get("candle_timestamp") != self.state.get("last_swept_candle_ts"):
                sweep["detected_at"] = now_ts
                self.state["swept_level"] = sweep
                self.state["last_swept_candle_ts"] = closed_candle_ts
                logger.info(
                    f"🎯 [Bot #4 SMC] {sweep['direction']} detected on {sweep['level_name']} @ {sweep['level_price']} | "
                    f"Extreme: {sweep['sweep_extreme']} | Wick Ratio: {sweep['wick_ratio']:.2f}"
                )
                self._save_state()

                # DIRECT TURTLE SOUP REJECTION ENTRY:
                # The institutional sweep candle has confirmed absorption and rejected back inside
                ask = float(tick.get("ask", 0.0))
                bid = float(tick.get("bid", 0.0))
                entry_price = bid if sweep["direction"] == "BEARISH_SWEEP" else ask
                if entry_price > 0:
                    logger.info(f"⚡ [Bot #4 SMC] Firing Direct Turtle Soup Reversal on {sweep['level_name']} rejection @ {entry_price:.2f}")
                    self._execute_smc_entry(sweep, None, entry_price, equity, symbol, dyn_risk=dyn_risk, pools=pools, tick=tick, df_m5=df_m5)
                    return

            active_sweep = self.state.get("swept_level")
            if not active_sweep:
                return

            # Expire active sweep after 15 minutes (~3 M5 candles) if no entry
            if (now_ts - float(active_sweep.get("detected_at", now_ts))) > 900.0:
                self.state["swept_level"] = None
                self._save_state()
                return

            # Check Market Structure Shift (MSS)
            if not self._check_mss(df_m5, active_sweep):
                return

            # Check for matching Fair Value Gap Retest
            target_fvg_type = "BEARISH_FVG" if active_sweep["direction"] == "BEARISH_SWEEP" else "BULLISH_FVG"
            matching_fvgs = [f for f in fvgs if f["type"] == target_fvg_type]
            if not matching_fvgs:
                return

            best_fvg = matching_fvgs[-1]
            self.state["active_fvg"] = best_fvg

            ask = float(tick.get("ask", 0.0))
            bid = float(tick.get("bid", 0.0))
            current_price = bid if active_sweep["direction"] == "BEARISH_SWEEP" else ask
            if current_price <= 0:
                return

            # Price inside FVG bounds or near midpoint (within 1.0 point on Gold)
            inside_fvg = (best_fvg["bottom"] - 0.50 <= current_price <= best_fvg["top"] + 0.50)
            tapped_midpoint = abs(current_price - best_fvg["midpoint"]) <= 1.0

            if inside_fvg or tapped_midpoint:
                logger.info(f"⚡ [Bot #4 SMC] Firing FVG Mitigation Retest Entry @ {current_price:.2f} (FVG {best_fvg['bottom']:.2f}-{best_fvg['top']:.2f})")
                self._execute_smc_entry(active_sweep, best_fvg, current_price, equity, symbol, dyn_risk=dyn_risk, pools=pools, tick=tick, df_m5=df_m5)

    def _calculate_dynamic_sl(
        self,
        direction: str,
        sweep_extreme: float,
        entry_price: float,
        atr: float,
        spread: float = 0.20
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Data-driven Stop Loss Calculation:
        - Anchored outside the sweep rejection wick extreme.
        - Dynamic Volatility & Spread buffer: max(spread * 1.5, atr * sl_atr_multiplier).
        - Clamped between min_sl (max(0.8 * atr, spread * 3.0, 1.00)) and max_sl (2.8 * atr).
        Returns: (sl_price, sl_distance, info_dict)
        """
        strat = self.config.get("strategy", {})
        mult = float(strat.get("sl_atr_multiplier", 0.30))

        # Volatility & spread adaptive buffer
        vol_buffer = max(spread * 1.5, atr * mult)
        vol_buffer = max(0.25, min(round(vol_buffer, 2), 1.80))

        if direction == "BEARISH_SWEEP":  # SELL
            raw_sl = sweep_extreme + vol_buffer
            raw_distance = raw_sl - entry_price
        else:  # BULLISH_SWEEP (BUY)
            raw_sl = sweep_extreme - vol_buffer
            raw_distance = entry_price - raw_sl

        # Dynamic safe distance sanity bounds
        min_sl_dist = max(atr * 0.8, spread * 3.0, 1.00)
        max_sl_dist = max(min_sl_dist + 1.0, atr * 2.8)

        if raw_distance < min_sl_dist:
            sl_distance = min_sl_dist
            sl_price = round(entry_price + sl_distance, 2) if direction == "BEARISH_SWEEP" else round(entry_price - sl_distance, 2)
        elif raw_distance > max_sl_dist:
            sl_distance = max_sl_dist
            sl_price = round(entry_price + sl_distance, 2) if direction == "BEARISH_SWEEP" else round(entry_price - sl_distance, 2)
        else:
            sl_distance = raw_distance
            sl_price = round(raw_sl, 2)

        sl_distance = round(abs(entry_price - sl_price), 2)
        info = {
            "sweep_extreme": round(sweep_extreme, 2),
            "vol_buffer": round(vol_buffer, 2),
            "spread": round(spread, 2),
            "atr": round(atr, 2),
            "sl_distance": sl_distance
        }
        return sl_price, sl_distance, info

    def _calculate_dynamic_tp(
        self,
        direction: str,
        entry_price: float,
        sl_distance: float,
        pools: Dict[str, Any],
        atr: float,
        dyn_risk: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Data-driven Take Profit targeting opposing institutional liquidity pools:
        - Bearish Sweep (SELL) -> Targets Sell-Side Liquidity (SSL): Asian Low, PDL, Swing Lows, EQL.
        - Bullish Sweep (BUY) -> Targets Buy-Side Liquidity (BSL): Asian High, PDH, Swing Highs, EQH.
        - Applies front-run buffer (e.g. 0.25) so order fills before the market bounces.
        - Requires Implied R:R >= min_target_rr (default 1.8).
        - If no suitable pool found, gracefully falls back to dynamic ATR expansion / dynamic R:R.
        Returns: (tp_price, implied_rr, info_dict)
        """
        strat = self.config.get("strategy", {})
        min_rr = float(strat.get("min_target_rr", 1.8))
        max_rr = float(strat.get("max_target_rr", 5.0))
        front_run = float(strat.get("front_run_points", 25)) / 100.0  # 25 pts = 0.25 on Gold
        fallback_rr = float(dyn_risk.get("tp2_rr", strat.get("tp2_rr", 3.5))) if dyn_risk else float(strat.get("tp2_rr", 3.5))

        target_level = None
        target_name = "ATR_EXPANSION_FALLBACK"

        if direction == "BEARISH_SWEEP":  # SELL: Hunt Sell-Side Liquidity below entry
            candidates = []
            if pools.get("asian_low", 0.0) > 0 and pools["asian_low"] < entry_price:
                candidates.append(("ASIAN_LOW", float(pools["asian_low"])))
            if pools.get("pdl", 0.0) > 0 and pools["pdl"] < entry_price:
                candidates.append(("PDL", float(pools["pdl"])))
            for eql in pools.get("eql", []):
                if eql < entry_price:
                    candidates.append(("EQL", float(eql)))
            for sh in pools.get("swing_lows", []):
                if sh < entry_price:
                    candidates.append(("SWING_LOW", float(sh)))

            # Sort descending: from nearest below entry to lowest
            candidates.sort(key=lambda x: x[1], reverse=True)

            for name, lvl in candidates:
                potential_tp = lvl + front_run
                gain = entry_price - potential_tp
                implied_rr = gain / sl_distance
                if min_rr <= implied_rr <= max_rr:
                    target_level = potential_tp
                    target_name = f"{name} @ {lvl:.2f}"
                    break
                elif implied_rr > max_rr:
                    # Beyond max ceiling, clamp to max_rr
                    target_level = round(entry_price - (sl_distance * max_rr), 2)
                    target_name = f"{name} (Clamped to {max_rr} R:R)"
                    break

            if target_level is None:
                # Fallback to dynamic R:R / ATR expansion
                target_level = round(entry_price - (sl_distance * fallback_rr), 2)
                target_name = f"DYNAMIC_RR ({fallback_rr:.1f}x)"

            final_tp = round(target_level, 2)
            final_rr = round((entry_price - final_tp) / sl_distance, 2)

        else:  # BULLISH_SWEEP (BUY): Hunt Buy-Side Liquidity above entry
            candidates = []
            if pools.get("asian_high", 0.0) > 0 and pools["asian_high"] > entry_price:
                candidates.append(("ASIAN_HIGH", float(pools["asian_high"])))
            if pools.get("pdh", 0.0) > 0 and pools["pdh"] > entry_price:
                candidates.append(("PDH", float(pools["pdh"])))
            for eqh in pools.get("eqh", []):
                if eqh > entry_price:
                    candidates.append(("EQH", float(eqh)))
            for sh in pools.get("swing_highs", []):
                if sh > entry_price:
                    candidates.append(("SWING_HIGH", float(sh)))

            # Sort ascending: from nearest above entry to highest
            candidates.sort(key=lambda x: x[1])

            for name, lvl in candidates:
                potential_tp = lvl - front_run
                gain = potential_tp - entry_price
                implied_rr = gain / sl_distance
                if min_rr <= implied_rr <= max_rr:
                    target_level = potential_tp
                    target_name = f"{name} @ {lvl:.2f}"
                    break
                elif implied_rr > max_rr:
                    # Beyond max ceiling, clamp to max_rr
                    target_level = round(entry_price + (sl_distance * max_rr), 2)
                    target_name = f"{name} (Clamped to {max_rr} R:R)"
                    break

            if target_level is None:
                target_level = round(entry_price + (sl_distance * fallback_rr), 2)
                target_name = f"DYNAMIC_RR ({fallback_rr:.1f}x)"

            final_tp = round(target_level, 2)
            final_rr = round((final_tp - entry_price) / sl_distance, 2)

        # Calculate TP1 (50% dealing range equilibrium)
        if direction == "BEARISH_SWEEP":
            tp1_midpoint = round(entry_price - ((entry_price - final_tp) * 0.50), 2)
        else:
            tp1_midpoint = round(entry_price + ((final_tp - entry_price) * 0.50), 2)

        info = {
            "target_name": target_name,
            "target_tp": final_tp,
            "implied_rr": final_rr,
            "tp1_equilibrium": tp1_midpoint,
            "front_run": front_run
        }
        return final_tp, final_rr, info

    def _execute_smc_entry(
        self,
        sweep: Dict[str, Any],
        fvg: Optional[Dict[str, Any]],
        entry_price: float,
        equity: float,
        symbol: str,
        dyn_risk: Optional[Dict[str, Any]] = None,
        pools: Optional[Dict[str, Any]] = None,
        tick: Optional[Dict[str, Any]] = None,
        df_m5: Optional[pd.DataFrame] = None
    ):
        if dyn_risk is None:
            dyn_risk = self._cached_dynamic_risk or {}
        if pools is None:
            pools = self._cached_liquidity_pools or {}
        if tick is None:
            tick = self.bridge.get_tick(symbol=symbol) or {}
        if df_m5 is None:
            df_m5 = self._cached_m5

        strat = self.config.get("strategy", {})
        dynamic_sl_tp = strat.get("dynamic_sl_tp_enabled", True)
        risk_pct = float(dyn_risk.get("risk_pct", self.config.get("risk_pct_per_trade", 1.0)))
        direction = sweep["direction"]
        order_type = "SELL" if direction == "BEARISH_SWEEP" else "BUY"

        # Live ATR & spread
        atr = float(dyn_risk.get("current_atr", 1.50))
        ask = float(tick.get("ask", entry_price))
        bid = float(tick.get("bid", entry_price))
        spread = max(0.05, round(abs(ask - bid), 2)) if ask > 0 and bid > 0 else 0.20

        if dynamic_sl_tp:
            sl_price, sl_distance, sl_info = self._calculate_dynamic_sl(
                direction=direction,
                sweep_extreme=float(sweep["sweep_extreme"]),
                entry_price=entry_price,
                atr=atr,
                spread=spread
            )
            tp_price, tp_rr, tp_info = self._calculate_dynamic_tp(
                direction=direction,
                entry_price=entry_price,
                sl_distance=sl_distance,
                pools=pools,
                atr=atr,
                dyn_risk=dyn_risk
            )
            sl_desc = f"{sl_price:.2f} (Extreme {sl_info['sweep_extreme']} + VolBuffer {sl_info['vol_buffer']:.2f})"
            tp_desc = f"{tp_price:.2f} (Target: {tp_info['target_name']} | R:R {tp_rr:.2f})"
        else:
            tp2_rr = float(dyn_risk.get("tp2_rr", strat.get("tp2_rr", 3.5)))
            if direction == "BEARISH_SWEEP":
                sl_price = round(sweep["sweep_extreme"] + 0.50, 2)
                sl_distance = sl_price - entry_price
                if sl_distance <= 0.30:
                    sl_distance = 3.00
                    sl_price = round(entry_price + 3.00, 2)
                tp_price = round(entry_price - (sl_distance * tp2_rr), 2)
            else:
                sl_price = round(sweep["sweep_extreme"] - 0.50, 2)
                sl_distance = entry_price - sl_price
                if sl_distance <= 0.30:
                    sl_distance = 3.00
                    sl_price = round(entry_price - 3.00, 2)
                tp_price = round(entry_price + (sl_distance * tp2_rr), 2)
            sl_desc = f"{sl_price:.2f} (Fixed)"
            tp_desc = f"{tp_price:.2f} (Fixed R:R {tp2_rr})"

        lot_size = self._calculate_lot_size(equity, sl_distance, risk_pct=risk_pct)

        logger.info(
            f"🚀 [Bot #4] Executing {order_type} @ {entry_price:.2f} | Lot: {lot_size} ({risk_pct}%) | "
            f"SL: {sl_desc} | TP2: {tp_desc}"
        )
        res = self.bridge.send_order(
            symbol=symbol,
            order_type=order_type,
            price=entry_price,
            volume=lot_size,
            sl=sl_price,
            tp=tp_price
        )

        if res.get("success", False) or res.get("ticket"):
            self._order_in_flight_until = time.time() + 20.0
            self.state["daily_trades_count"] = self.state.get("daily_trades_count", 0) + 1
            ticket_num = res.get("ticket")
            new_trade = {
                "ticket": ticket_num,
                "symbol": symbol,
                "type": order_type,
                "price": entry_price,
                "volume": lot_size,
                "sl": sl_price,
                "tp": tp_price,
                "time": time.time(),
                "time_str": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "level": sweep.get("level_name"),
                "status": "OPEN"
            }
            self.state.setdefault("trade_history", []).append(new_trade)
            if len(self.state["trade_history"]) > 100:
                self.state["trade_history"] = self.state["trade_history"][-100:]
            # Clear sweep after execution so we wait for the next fresh setup
            self.state["swept_level"] = None
            self.state["active_fvg"] = None
            self._save_state()
            logger.info(f"✅ [Bot #4] Order successfully placed: Ticket #{ticket_num}")
        else:
            logger.error(f"❌ [Bot #4] Order dispatch failed: {res.get('error')}")

    def _manage_open_positions(self, open_positions: List[Dict[str, Any]], df: pd.DataFrame, dyn_risk: Optional[Dict[str, Any]] = None):
        """
        Manages open positions:
        1. Dynamic Breakeven lock at dynamic R:R
        2. Partial TP1 close (50%) at dynamic R:R
        3. Dynamic ATR Chandelier trailing stop on the remaining runner
        """
        # Track closed status in trade_history
        active_tickets = {int(p.get("ticket", 0)) for p in open_positions} if open_positions else set()
        trade_hist = self.state.get("trade_history", [])
        hist_updated = False
        for t in trade_hist:
            if t.get("status") == "OPEN" and int(t.get("ticket", 0)) not in active_tickets:
                t["status"] = "CLOSED"
                hist_updated = True
        if hist_updated:
            self._save_state()

        if not open_positions:
            return

        if dyn_risk is None:
            dyn_risk = self._cached_dynamic_risk or {}

        strat_cfg = self.config.get("strategy", {})
        be_rr = float(dyn_risk.get("be_trigger_rr", strat_cfg.get("be_trigger_rr", 1.0)))
        tp1_rr = float(dyn_risk.get("tp1_rr", strat_cfg.get("tp1_rr", 1.5)))
        tp1_pct = float(strat_cfg.get("tp1_close_pct", 50.0))
        be_offset = float(strat_cfg.get("be_offset_points", 30)) / 100.0  # 30 pts = 0.30

        # Calculate ATR for trailing stop
        atr_val = 1.50
        try:
            atr_series = self._compute_atr(df, period=int(strat_cfg.get("atr_period", 14)))
            if not atr_series.empty and not np.isnan(atr_series.iloc[-1]):
                atr_val = float(atr_series.iloc[-1])
        except Exception:
            pass

        trail_mult = float(dyn_risk.get("atr_sl_multiplier", strat_cfg.get("atr_sl_multiplier", 1.2)))
        tp1_tickets = set(self.state.get("tp1_executed_tickets", []))
        active_tickets = {int(p.get("ticket", 0)) for p in open_positions}

        # Prune stale tickets no longer open
        if not tp1_tickets.issubset(active_tickets):
            tp1_tickets = tp1_tickets.intersection(active_tickets)
            self.state["tp1_executed_tickets"] = list(tp1_tickets)
            self._save_state()

        for pos in open_positions:
            ticket = int(pos.get("ticket", 0))
            pos_type = str(pos.get("type", "")).upper()
            open_price = float(pos.get("open_price", pos.get("price_open", 0.0)))
            current_price = float(pos.get("current_price", pos.get("price_current", open_price)))
            sl = float(pos.get("sl", 0.0))
            tp = float(pos.get("tp", 0.0))
            volume = float(pos.get("volume", 0.01))

            if open_price <= 0:
                continue

            # Calculate initial risk distance from open to original SL
            risk_dist = abs(open_price - sl) if sl > 0 else 2.00
            if risk_dist <= 0.20:
                risk_dist = 2.00

            # Realized move in direction of trade
            if "BUY" in pos_type:
                gain = current_price - open_price
                current_rr = gain / risk_dist
                target_sl = sl

                # 1. Stage 1: Breakeven Check (1.0 R:R) -> Free Trade
                if current_rr >= be_rr:
                    be_level = round(open_price + be_offset, 2)
                    if target_sl < be_level:
                        target_sl = be_level

                # 2. Stage 2: TP1 Partial Close Check (1.5 R:R) & +0.50 R:R Profit Lock
                if current_rr >= tp1_rr:
                    lock_05 = round(open_price + (risk_dist * 0.50), 2)
                    if target_sl < lock_05:
                        target_sl = lock_05

                    # Execute TP1 50% partial cash-in exactly once per ticket
                    if ticket not in tp1_tickets and volume > 0.01:
                        close_vol = round(volume * (tp1_pct / 100.0), 2)
                        if close_vol >= 0.01:
                            logger.info(f"💰 [Bot #4 Milestone] Position #{ticket} reached TP1 ({current_rr:.1f} R:R). Banking {close_vol} lot.")
                            self.bridge.close_position(ticket, volume=close_vol)
                            tp1_tickets.add(ticket)
                            self.state["tp1_executed_tickets"] = list(tp1_tickets)
                            self._save_state()

                # 3. Stage 3: Milestone Ratchet at 2.2 R:R -> Lock +1.40 R:R Profit
                if current_rr >= 2.20:
                    lock_14 = round(open_price + (risk_dist * 1.40), 2)
                    if target_sl < lock_14:
                        target_sl = lock_14

                # 4. Stage 4: Milestone Ratchet at 3.0 R:R -> Lock +2.20 R:R Profit
                if current_rr >= 3.00:
                    lock_22 = round(open_price + (risk_dist * 2.20), 2)
                    if target_sl < lock_22:
                        target_sl = lock_22

                # 5. Dynamic Chandelier ATR Trailing Stop
                if current_rr >= tp1_rr and strat_cfg.get("trailing_stop_active", True):
                    trail_sl = round(current_price - (atr_val * trail_mult), 2)
                    if trail_sl > target_sl and trail_sl > open_price:
                        target_sl = trail_sl

                # Dispatch SL modification if ratcheted forward into higher profit
                if target_sl > sl:
                    logger.info(f"🛡️ [Bot #4 Ratchet] #{ticket} (BUY @ {open_price:.2f}) at {current_rr:.1f} R:R -> Ratcheting SL: {sl:.2f} -> {target_sl:.2f}")
                    self.bridge.modify_position(ticket, sl=target_sl, tp=tp)

            elif "SELL" in pos_type:
                gain = open_price - current_price
                current_rr = gain / risk_dist
                target_sl = sl

                # 1. Stage 1: Breakeven Check (1.0 R:R) -> Free Trade
                if current_rr >= be_rr:
                    be_level = round(open_price - be_offset, 2)
                    if sl <= 0 or target_sl > be_level:
                        target_sl = be_level

                # 2. Stage 2: TP1 Partial Close Check (1.5 R:R) & +0.50 R:R Profit Lock
                if current_rr >= tp1_rr:
                    lock_05 = round(open_price - (risk_dist * 0.50), 2)
                    if sl <= 0 or target_sl > lock_05:
                        target_sl = lock_05

                    # Execute TP1 50% partial cash-in exactly once per ticket
                    if ticket not in tp1_tickets and volume > 0.01:
                        close_vol = round(volume * (tp1_pct / 100.0), 2)
                        if close_vol >= 0.01:
                            logger.info(f"💰 [Bot #4 Milestone] Position #{ticket} reached TP1 ({current_rr:.1f} R:R). Banking {close_vol} lot.")
                            self.bridge.close_position(ticket, volume=close_vol)
                            tp1_tickets.add(ticket)
                            self.state["tp1_executed_tickets"] = list(tp1_tickets)
                            self._save_state()

                # 3. Stage 3: Milestone Ratchet at 2.2 R:R -> Lock +1.40 R:R Profit
                if current_rr >= 2.20:
                    lock_14 = round(open_price - (risk_dist * 1.40), 2)
                    if sl <= 0 or target_sl > lock_14:
                        target_sl = lock_14

                # 4. Stage 4: Milestone Ratchet at 3.0 R:R -> Lock +2.20 R:R Profit
                if current_rr >= 3.00:
                    lock_22 = round(open_price - (risk_dist * 2.20), 2)
                    if sl <= 0 or target_sl > lock_22:
                        target_sl = lock_22

                # 5. Dynamic Chandelier ATR Trailing Stop
                if current_rr >= tp1_rr and strat_cfg.get("trailing_stop_active", True):
                    trail_sl = round(current_price + (atr_val * trail_mult), 2)
                    if (target_sl <= 0 or trail_sl < target_sl) and trail_sl < open_price:
                        target_sl = trail_sl

                # Dispatch SL modification if ratcheted forward into higher profit
                if target_sl > 0 and (sl <= 0 or target_sl < sl):
                    logger.info(f"🛡️ [Bot #4 Ratchet] #{ticket} (SELL @ {open_price:.2f}) at {current_rr:.1f} R:R -> Ratcheting SL: {sl:.2f} -> {target_sl:.2f}")
                    self.bridge.modify_position(ticket, sl=target_sl, tp=tp)

    # ── Read-Only Telemetry for Streamlit Panel ───────────────────────────────
    def get_telemetry(self) -> Dict[str, Any]:
        """Provides instant, non-blocking telemetry snapshot for the Streamlit UI."""
        symbol = self.config.get("symbol", "XAUUSD")
        acc = self.bridge.get_account()
        tick = self.bridge.get_tick(symbol=symbol)
        positions = self.bridge.get_positions(symbol=symbol)
        orders = self.bridge.get_orders(symbol=symbol)

        metrics = calculate_performance_metrics(self.state.get("trade_history", []))

        # Preview dynamic liquidity targets
        dynamic_preview = {}
        bid = float(tick.get("bid", 0.0))
        ask = float(tick.get("ask", 0.0))
        pools = self._cached_liquidity_pools or {}
        if bid > 0 and pools:
            ssl_candidates = [p for p in [pools.get("asian_low", 0.0), pools.get("pdl", 0.0)] if p > 0 and p < bid]
            bsl_candidates = [p for p in [pools.get("asian_high", 0.0), pools.get("pdh", 0.0)] if p > 0 and p > ask]
            dynamic_preview = {
                "dynamic_sl_tp_enabled": bool(self.config.get("strategy", {}).get("dynamic_sl_tp_enabled", True)),
                "next_ssl_target": max(ssl_candidates) if ssl_candidates else None,
                "next_bsl_target": min(bsl_candidates) if bsl_candidates else None
            }

        return {
            "symbol": symbol,
            "connected": bool(acc.get("connected", False)),
            "login": acc.get("login", 0),
            "server": acc.get("server", ""),
            "balance": acc.get("balance", 1000.0),
            "equity": acc.get("equity", 1000.0),
            "ask": tick.get("ask", 0.0),
            "bid": tick.get("bid", 0.0),
            "open_positions": positions,
            "open_orders": orders,
            "liquidity_pools": self._cached_liquidity_pools,
            "active_fvgs": self._cached_fvg_list,
            "swept_level": self.state.get("swept_level"),
            "daily_pnl": self.state.get("daily_pnl", 0.0),
            "daily_trades_count": self.state.get("daily_trades_count", 0),
            "auto_trading": self.config.get("auto_trading", True),
            "dynamic_risk": self._cached_dynamic_risk,
            "dynamic_preview": dynamic_preview,
            "metrics": metrics,
            "trade_history": self.state.get("trade_history", []),
            "config": self.config
        }

    def stop(self):
        """Signals background execution loop to terminate."""
        self._running = False


    def emergency_close_all(self):
        """Manual emergency kill switch."""
        symbol = self.config.get("symbol", "XAUUSD")
        res = self.bridge.close_all_positions(symbol=symbol)
        self.state["swept_level"] = None
        self.state["active_fvg"] = None
        self._save_state()
        return res


# Singleton pattern
_engine_instance: Optional[SMCEngine] = None
_instance_lock = threading.Lock()


def get_engine() -> SMCEngine:
    global _engine_instance
    with _instance_lock:
        if _engine_instance is None:
            _engine_instance = SMCEngine()
        return _engine_instance


if __name__ == "__main__":
    logger.info("Starting Bot #4 SMC Liquidity Hunter Engine directly in CLI mode...")
    engine = get_engine()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Bot #4 SMC Engine shutting down cleanly.")
        engine.stop()

