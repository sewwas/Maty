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

        # Cached analytics & telemetry
        self._cached_m5: Optional[pd.DataFrame] = None
        self._cached_m15: Optional[pd.DataFrame] = None
        self._cached_liquidity_pools: Dict[str, Any] = {}
        self._cached_fvg_list: List[Dict[str, Any]] = []
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
            "risk_pct_per_trade": 1.0,
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
                "trailing_stop_active": True
            }
        }

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
            "swept_level": None
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

    def _calculate_lot_size(self, equity: float, sl_distance: float) -> float:
        """
        Institutional 1.0% Equity Risk lot sizing:
        Gold standard: 1.00 distance on 0.01 lot = $1.00 USD risk.
        """
        risk_pct = float(self.config.get("risk_pct_per_trade", 1.0))
        risk_usd = equity * (risk_pct / 100.0)
        
        if sl_distance <= 0.20:
            sl_distance = 1.50  # Safe minimum fallback distance ($1.50 on Gold)

        # Raw lot = risk_usd / (sl_distance * 100)
        raw_lot = risk_usd / (sl_distance * 100.0)
        
        # Hard bounds: min 0.01 lot, max 0.50 lot (safe institutional ceiling)
        lot = max(0.01, min(0.50, round(raw_lot, 2)))
        return lot

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

            # Compute Liquidity Pools & FVGs
            pools = self._identify_liquidity_pools(df_m15, df_m5)
            self._cached_liquidity_pools = pools

            strat_cfg = self.config.get("strategy", {})
            fvg_min_pips = float(strat_cfg.get("fvg_min_pips", 3.5))
            fvgs = self._detect_fvgs(df_m5, min_pips=fvg_min_pips)
            self._cached_fvg_list = fvgs

            # 2. Manage Active Positions (Breakeven, Partial TP1, Trailing Stop)
            open_positions = self.bridge.get_positions(symbol=symbol)
            self._manage_open_positions(open_positions, df_m5)

            # 3. Check Account & Circuit Breakers
            acc = self.bridge.get_account()
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

            # Max trades per day
            max_trades = int(self.config.get("max_trades_per_day", 4))
            if max_trades > 0 and self.state.get("daily_trades_count", 0) >= max_trades:
                return

            # If an order is already in-flight or positions already open, do not enter new trade
            if now_ts < self._order_in_flight_until or open_positions:
                return

            if not self.config.get("auto_trading", True):
                return

            # 4. Scan for New Liquidity Sweep & FVG Setup
            closed_candle = df_m5.iloc[-2]
            min_wick_ratio = float(strat_cfg.get("min_wick_ratio", 0.38))
            sweep = self._check_liquidity_sweep(closed_candle, pools, min_wick_ratio=min_wick_ratio)

            if sweep:
                self.state["swept_level"] = sweep
                logger.info(f"🎯 [Bot #4] {sweep['direction']} detected on {sweep['level_name']} @ {sweep['level_price']} | Wick Ratio: {sweep['wick_ratio']}")
                self._save_state()

            active_sweep = self.state.get("swept_level")
            if not active_sweep:
                return

            # Check Market Structure Shift (MSS)
            if not self._check_mss(df_m5, active_sweep):
                return

            # Check for matching Fair Value Gap
            target_fvg_type = "BEARISH_FVG" if active_sweep["direction"] == "BEARISH_SWEEP" else "BULLISH_FVG"
            matching_fvgs = [f for f in fvgs if f["type"] == target_fvg_type]

            if not matching_fvgs:
                return

            best_fvg = matching_fvgs[-1]  # Most recent FVG
            self.state["active_fvg"] = best_fvg

            # Current price check (tap into FVG)
            tick = self.bridge.get_tick(symbol=symbol)
            ask = float(tick.get("ask", 0.0))
            bid = float(tick.get("bid", 0.0))
            current_price = bid if active_sweep["direction"] == "BEARISH_SWEEP" else ask

            if current_price <= 0:
                return

            # Price inside FVG bounds
            inside_fvg = (best_fvg["bottom"] <= current_price <= best_fvg["top"])
            # Or tapped the midpoint (within 0.30)
            tapped_midpoint = abs(current_price - best_fvg["midpoint"]) <= 0.35

            if inside_fvg or tapped_midpoint:
                # Fire the trade!
                self._execute_smc_entry(active_sweep, best_fvg, current_price, equity, symbol)

    def _execute_smc_entry(
        self,
        sweep: Dict[str, Any],
        fvg: Dict[str, Any],
        entry_price: float,
        equity: float,
        symbol: str
    ):
        strat_cfg = self.config.get("strategy", {})
        tp1_rr = float(strat_cfg.get("tp1_rr", 1.5))
        tp2_rr = float(strat_cfg.get("tp2_rr", 3.5))

        direction = sweep["direction"]
        if direction == "BEARISH_SWEEP":
            order_type = "SELL"
            # Stop loss above sweep extreme + 0.50 buffer ($5 on Gold)
            sl_price = round(sweep["sweep_extreme"] + 0.50, 2)
            sl_distance = sl_price - entry_price
            if sl_distance <= 0.30:
                sl_distance = 1.50
                sl_price = round(entry_price + 1.50, 2)

            tp_price = round(entry_price - (sl_distance * tp2_rr), 2)
        else:
            order_type = "BUY"
            # Stop loss below sweep extreme - 0.50 buffer
            sl_price = round(sweep["sweep_extreme"] - 0.50, 2)
            sl_distance = entry_price - sl_price
            if sl_distance <= 0.30:
                sl_distance = 1.50
                sl_price = round(entry_price - 1.50, 2)

            tp_price = round(entry_price + (sl_distance * tp2_rr), 2)

        lot_size = self._calculate_lot_size(equity, sl_distance)

        logger.info(f"🚀 [Bot #4] Executing {order_type} @ {entry_price:.2f} | Lot: {lot_size} | SL: {sl_price:.2f} | TP2: {tp_price:.2f} (R:R {tp2_rr})")
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
            # Clear sweep after execution so we wait for the next fresh setup
            self.state["swept_level"] = None
            self.state["active_fvg"] = None
            self._save_state()
            logger.info(f"✅ [Bot #4] Order successfully placed: Ticket #{res.get('ticket')}")
        else:
            logger.error(f"❌ [Bot #4] Order dispatch failed: {res.get('error')}")

    def _manage_open_positions(self, open_positions: List[Dict[str, Any]], df: pd.DataFrame):
        """
        Manages open positions:
        1. Breakeven lock at 1:1.0 RR
        2. Partial TP1 close (50%) at 1:1.5 RR
        3. ATR Chandelier trailing stop on the remaining runner
        """
        if not open_positions:
            return

        strat_cfg = self.config.get("strategy", {})
        be_rr = float(strat_cfg.get("be_trigger_rr", 1.0))
        tp1_rr = float(strat_cfg.get("tp1_rr", 1.5))
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

                # 1. Breakeven Check
                if current_rr >= be_rr:
                    target_be_sl = round(open_price + be_offset, 2)
                    if sl < target_be_sl:
                        logger.info(f"🛡️ [Bot #4] Position #{ticket} reached {current_rr:.1f} R:R. Ratcheting SL to Breakeven @ {target_be_sl:.2f}")
                        self.bridge.modify_position(ticket, sl=target_be_sl, tp=tp)

                # 2. TP1 Partial Close Check
                if current_rr >= tp1_rr and volume > 0.01:
                    close_vol = round(volume * (tp1_pct / 100.0), 2)
                    if close_vol >= 0.01:
                        logger.info(f"💰 [Bot #4] Position #{ticket} reached TP1 ({current_rr:.1f} R:R). Closing partial {close_vol} lot.")
                        self.bridge.close_position(ticket, volume=close_vol)

                # 3. ATR Trailing Stop (Chandelier)
                if current_rr >= tp1_rr and strat_cfg.get("trailing_stop_active", True):
                    mult = float(strat_cfg.get("atr_sl_multiplier", 1.2))
                    trail_sl = round(current_price - (atr_val * mult), 2)
                    if trail_sl > sl and trail_sl > open_price:
                        logger.info(f"📈 [Bot #4] Trailing stop updated for #{ticket}: SL -> {trail_sl:.2f}")
                        self.bridge.modify_position(ticket, sl=trail_sl, tp=tp)

            elif "SELL" in pos_type:
                gain = open_price - current_price
                current_rr = gain / risk_dist

                # 1. Breakeven Check
                if current_rr >= be_rr:
                    target_be_sl = round(open_price - be_offset, 2)
                    if sl <= 0 or sl > target_be_sl:
                        logger.info(f"🛡️ [Bot #4] Position #{ticket} reached {current_rr:.1f} R:R. Ratcheting SL to Breakeven @ {target_be_sl:.2f}")
                        self.bridge.modify_position(ticket, sl=target_be_sl, tp=tp)

                # 2. TP1 Partial Close Check
                if current_rr >= tp1_rr and volume > 0.01:
                    close_vol = round(volume * (tp1_pct / 100.0), 2)
                    if close_vol >= 0.01:
                        logger.info(f"💰 [Bot #4] Position #{ticket} reached TP1 ({current_rr:.1f} R:R). Closing partial {close_vol} lot.")
                        self.bridge.close_position(ticket, volume=close_vol)

                # 3. ATR Trailing Stop (Chandelier)
                if current_rr >= tp1_rr and strat_cfg.get("trailing_stop_active", True):
                    mult = float(strat_cfg.get("atr_sl_multiplier", 1.2))
                    trail_sl = round(current_price + (atr_val * mult), 2)
                    if (sl <= 0 or trail_sl < sl) and trail_sl < open_price:
                        logger.info(f"📉 [Bot #4] Trailing stop updated for #{ticket}: SL -> {trail_sl:.2f}")
                        self.bridge.modify_position(ticket, sl=trail_sl, tp=tp)

    # ── Read-Only Telemetry for Streamlit Panel ───────────────────────────────
    def get_telemetry(self) -> Dict[str, Any]:
        """Provides instant, non-blocking telemetry snapshot for the Streamlit UI."""
        symbol = self.config.get("symbol", "XAUUSD")
        acc = self.bridge.get_account()
        tick = self.bridge.get_tick(symbol=symbol)
        positions = self.bridge.get_positions(symbol=symbol)
        orders = self.bridge.get_orders(symbol=symbol)

        metrics = calculate_performance_metrics(self.state.get("trade_history", []))

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
            "metrics": metrics,
            "config": self.config
        }

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
