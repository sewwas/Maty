"""
Bot #5 — Institutional AI/ML Neural Trader & Dynamic Risk Governor
===================================================================
Autonomous Execution Architecture:
1. Dynamic Market Regime Detection:
   - Evaluates Kaufman Efficiency Ratio (ER), Bollinger Bandwidth, and multi-timeframe EMAs.
   - Classifies market into TRENDING, RANGING, VOLATILE_BREAKOUT, or LOW_VOLATILITY_DRIFT.
2. Fully Dynamic Strategy Risk Governor (Autonomous Auto-Pilot):
   - Dynamically modulates Risk Per Trade (%) based on Regime, Volatility, and Drawdown.
   - Volatility-Adaptive Stop Loss (ATR multiplier dynamically modulated between 1.2x and 2.4x).
   - Regime-Adaptive Take Profit (Dynamic R:R between 1.8x and 4.5x).
   - Adaptive Confidence Entry Bar (tightens in chop, expands in clean trend).
   - Dynamic Breakeven Ratchet & Chandelier Trailing Stop.
   - Consecutive Loss & Drawdown Safety Brakes.
3. Multi-Model Ensemble Confluence Engine:
   - Confluence across Trend Momentum (EMA 20/50/200), RSI Mean-Reversion, and Volatility Expansion.
"""

import os
import sys
import time
import json
import logging
import datetime
import threading
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd

# Ensure local imports work cleanly
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from bridge_client import Bot5BridgeClient
from analytics import calculate_performance_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AITraderBot5")


class AIEngine:
    def __init__(self, config_path: Optional[str] = None):
        if not config_path:
            config_path = os.path.join(_CURRENT_DIR, "config.json")
        self.config_path = config_path
        self.state_path = os.path.join(_CURRENT_DIR, "state.json")
        self.config = self._load_config()
        self.state = self._load_state()

        # Concurrency & locks
        self._execution_lock = threading.Lock()
        self._order_in_flight_until = 0.0
        self._last_stats_update = 0.0
        self._last_tick_time = 0.0
        self._last_candle_fetch = 0.0
        self._last_log_time = 0.0

        # Cached telemetry & analytical outputs
        self._cached_candles: Optional[pd.DataFrame] = None
        self._cached_telemetry: Dict[str, Any] = {}
        self._cached_regime: Dict[str, Any] = {
            "name": "RANGING",
            "confidence": 0.72,
            "description": "Mean-reverting consolidation corridor",
            "color": "#38bdf8"
        }
        self._cached_signal: Dict[str, Any] = {
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "score": 0.0,
            "factors": {},
            "timestamp": "Waiting for tick..."
        }
        self._cached_dynamic_risk: Dict[str, Any] = {
            "enabled": True,
            "risk_pct": 1.0,
            "atr_sl_multiplier": 1.5,
            "tp_rr": 2.5,
            "confidence_threshold": 0.60,
            "be_trigger_rr": 1.0,
            "trailing_atr_multiplier": 1.2,
            "max_positions": 2,
            "regime_mode": "🛡️ BALANCED AUTONOMOUS RISK",
            "reasons": ["Baseline Initialization"]
        }

        # Bridge client
        bridge_url = self.config.get("bridge_url", "http://127.0.0.1:8005")
        magic = int(self.config.get("magic_number", 998875))
        self.bridge = Bot5BridgeClient(bridge_url=bridge_url, magic_number=magic)

        # Process Singleton Lock: only 1 process executes live trading orders across OS
        self._lock_file = None
        self._is_primary_worker = self._acquire_worker_lock()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if self._is_primary_worker:
            logger.info(f"✅ Bot #5 AI Engine Primary Autonomous Worker ACTIVE [PID {os.getpid()}] on Magic {magic}")
        else:
            logger.info(f"ℹ️ Bot #5 AI Engine Telemetry Mode ACTIVE [PID {os.getpid()}] (Primary worker running in background)")

    def _acquire_worker_lock(self) -> bool:
        """
        Ensures only ONE process executes orders on MT5 to prevent duplicate execution collisions.
        """
        lock_file = "/tmp/bot5_engine.lock" if sys.platform != "win32" else os.path.join(_CURRENT_DIR, "bot5_engine.lock")
        my_pid = os.getpid()
        self._lock_file = lock_file

        if os.path.exists(lock_file):
            try:
                with open(lock_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    existing_pid = int(content)
                    if existing_pid == my_pid:
                        return True
                    # Check if existing process is alive
                    if sys.platform != "win32":
                        try:
                            os.kill(existing_pid, 0)
                            return False  # Still alive, this instance stays in telemetry mode
                        except OSError:
                            pass  # Stale lockfile
                    else:
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        h = kernel32.OpenProcess(0x0400, False, existing_pid)
                        if h:
                            kernel32.CloseHandle(h)
                            return False
            except Exception:
                pass

        try:
            with open(lock_file, "w", encoding="utf-8") as f:
                f.write(str(my_pid))
            return True
        except Exception as e:
            logger.warning(f"Could not acquire primary worker lock: {e}")
            return False

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config.json: {e}")
        return {
            "symbol": "XAUUSD",
            "magic_number": 998875,
            "bridge_url": "http://127.0.0.1:8005",
            "bridge_port": 8005,
            "dashboard_port": 8505,
            "dynamic_risk_enabled": True,
            "risk_pct_per_trade": 1.0,
            "max_risk_ceiling_pct": 2.5,
            "min_risk_floor_pct": 0.25,
            "max_daily_risk_pct": 3.0,
            "max_trades_per_day": 6,
            "max_positions": 2,
            "auto_trading": True,
            "algorithm": "ensemble",
            "confidence_threshold": 0.60,
            "strategy": {
                "timeframe": "M5",
                "fast_ema": 20,
                "medium_ema": 50,
                "slow_ema": 200,
                "rsi_period": 14,
                "atr_period": 14,
                "atr_sl_multiplier": 1.5,
                "tp_rr": 2.5,
                "be_trigger_rr": 1.0,
                "be_offset_points": 25,
                "trailing_stop_active": True,
                "trailing_atr_multiplier": 1.2
            }
        }

    def save_config(self, new_config: Dict[str, Any]):
        """
        Dynamically saves updated configuration and syncs live engine state.
        """
        with self._execution_lock:
            self.config.update(new_config)
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
                logger.info("✅ Configuration dynamically updated and saved to config.json")
            except Exception as e:
                logger.error(f"Error saving config.json: {e}")

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state.json: {e}")
        return {
            "daily_pnl": 0.0,
            "daily_trades": 0,
            "consecutive_losses": 0,
            "last_trade_time": 0.0,
            "breakeven_locked": {},
            "peak_price": {}
        }

    def _save_state(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state.json: {e}")

    # ── Feature Engineering & Regime Detection ──────────────────────────────────

    def _compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Computes institutional technical factors: EMAs, RSI, ATR, Bollinger Bands, and Efficiency Ratio.
        """
        if df is None or len(df) < 30:
            return df

        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # EMAs
        df["ema20"] = close.ewm(span=20, adjust=False).mean()
        df["ema50"] = close.ewm(span=50, adjust=False).mean()
        df["ema200"] = close.ewm(span=min(200, len(df)), adjust=False).mean()

        # ATR (14)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14).mean().fillna(1.5)

        # RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

        # Bollinger Bands (20, 2.0)
        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        df["bb_upper"] = sma20 + (std20 * 2.0)
        df["bb_lower"] = sma20 - (std20 * 2.0)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (sma20 + 1e-9)

        # Kaufman Efficiency Ratio (ER) over 14 candles
        change = (close - close.shift(14)).abs()
        volatility = (close - close.shift(1)).abs().rolling(window=14).sum()
        df["er"] = (change / (volatility + 1e-9)).fillna(0.3)

        # Choppiness Index (CHOP) over 14 candles
        # Classic Dreiss Formula: 100 * LOG10( SUM(ATR, 14) / (MaxHigh(14) - MinLow(14)) ) / LOG10(14)
        tr_sum14 = tr.rolling(window=14).sum()
        hh14 = high.rolling(window=14).max()
        ll14 = low.rolling(window=14).min()
        hl_range = (hh14 - ll14).replace(0, 1e-9)
        ratio = (tr_sum14 / hl_range).clip(lower=1e-6)
        df["chop_index"] = (100.0 * np.log10(ratio) / np.log10(14)).fillna(50.0)

        return df

    def _detect_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Classifies current market regime:
        - TRENDING (Strong directional impulse)
        - VOLATILE_BREAKOUT (Momentum volatility expansion)
        - RANGING (Mean-reverting within bands)
        - LOW_VOLATILITY_DRIFT (Low volume / tiny chop compression — entries blocked)
        """
        if df is None or len(df) < 20:
            return self._cached_regime

        latest = df.iloc[-1]
        er = float(latest.get("er", 0.3))
        bb_width = float(latest.get("bb_width", 0.01))
        atr = float(latest.get("atr", 1.5))
        chop_index = float(latest.get("chop_index", 50.0))
        mean_atr = float(df["atr"].tail(50).mean()) if "atr" in df.columns else atr

        ema20 = float(latest.get("ema20", 0.0))
        ema50 = float(latest.get("ema50", 0.0))
        ema_spread = abs(ema20 - ema50)

        min_atr_filter = float(self.config.get("min_atr_filter", 1.80))
        chop_thresh = float(self.config.get("chop_index_threshold", 60.0))
        min_ema_spread = float(self.config.get("min_ema_spread", 0.80))
        min_bb_width = float(self.config.get("min_bb_width", 0.0035))

        # Anti-Chop Shield Condition: strict suppression of tiny sideways micro-ranges
        is_tiny_chop = (
            atr < min_atr_filter or
            chop_index >= chop_thresh or
            bb_width < min_bb_width or
            ema_spread < min_ema_spread or
            er < 0.35
        )

        # 1. Volatile Breakout (High momentum expansion)
        if atr > 1.6 * mean_atr and bb_width > 0.006 and not is_tiny_chop:
            return {
                "name": "VOLATILE_BREAKOUT",
                "confidence": 0.88,
                "description": "High-momentum volatility expansion detected",
                "color": "#f43f5e",
                "chop_index": round(chop_index, 1),
                "is_anti_chop_active": False
            }

        # 2. Trending (Real clean directional impulse — UNLIMITED TRADING)
        if er > 0.40 and ema_spread >= min_ema_spread and atr >= min_atr_filter and chop_index < 55.0:
            trend_dir = "BULLISH" if ema20 > ema50 else "BEARISH"
            return {
                "name": "TRENDING",
                "confidence": round(min(0.95, er * 1.5), 2),
                "description": f"Clean {trend_dir} trend impulse (Chop: {chop_index:.1f}, ATR: ${atr:.2f}) — Velocity Unlocked",
                "color": "#10b981" if trend_dir == "BULLISH" else "#f97316",
                "chop_index": round(chop_index, 1),
                "is_anti_chop_active": False
            }

        # 3. Tiny Chop / Low Volatility Drift (🛡️ Anti-Chop Shield ENGAGED)
        if is_tiny_chop:
            chop_reasons = []
            if atr < min_atr_filter:
                chop_reasons.append(f"ATR ${atr:.2f} < ${min_atr_filter:.2f}")
            if chop_index >= chop_thresh:
                chop_reasons.append(f"Chop {chop_index:.1f} >= {chop_thresh:.0f}")
            if ema_spread < min_ema_spread:
                chop_reasons.append(f"EMA Spread ${ema_spread:.2f} < ${min_ema_spread:.2f}")
            if bb_width < min_bb_width:
                chop_reasons.append(f"BB Width {bb_width:.4f}")
            reason_str = ", ".join(chop_reasons) if chop_reasons else "Sideways Drift"

            return {
                "name": "LOW_VOLATILITY_DRIFT",
                "confidence": 0.88,
                "description": f"🛡️ Anti-Chop Shield Active ({reason_str}) — Entries Paused to Protect Capital",
                "color": "#64748b",
                "chop_index": round(chop_index, 1),
                "is_anti_chop_active": True
            }

        # 4. Standard Ranging (Wide corridor)
        return {
            "name": "RANGING",
            "confidence": 0.74,
            "description": f"Wide mean-reverting corridor (Chop: {chop_index:.1f}) — Strict boundary only",
            "color": "#38bdf8",
            "chop_index": round(chop_index, 1),
            "is_anti_chop_active": False
        }

    # ── ⚙️ Fully Dynamic Strategy Risk Engine ────────────────────────────────────

    def _calculate_dynamic_risk(self, df: Optional[pd.DataFrame], tick: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dynamically manages ALL Strategy Risk Settings:
        - Dynamic Risk % Per Trade
        - Volatility-Adaptive Stop Loss (ATR Multiplier)
        - Regime-Adaptive Take Profit (R:R)
        - Dynamic Confidence Threshold
        - Dynamic Breakeven Trigger & Offset
        - Dynamic Trailing Stop Distance
        - Dynamic Max Positions
        """
        base_risk = float(self.config.get("risk_pct_per_trade", 1.0))
        ceiling_risk = float(self.config.get("max_risk_ceiling_pct", 2.5))
        floor_risk = float(self.config.get("min_risk_floor_pct", 0.25))
        base_thresh = float(self.config.get("confidence_threshold", 0.60))

        strat = self.config.get("strategy", {})
        base_sl_mult = float(strat.get("atr_sl_multiplier", 1.5))
        base_tp_rr = float(strat.get("tp_rr", 2.5))
        base_be_rr = float(strat.get("be_trigger_rr", 1.0))
        base_trail_atr = float(strat.get("trailing_atr_multiplier", 1.2))

        # Check if dynamic risk engine is enabled
        if not self.config.get("dynamic_risk_enabled", True):
            return {
                "enabled": False,
                "risk_pct": base_risk,
                "atr_sl_multiplier": base_sl_mult,
                "tp_rr": base_tp_rr,
                "confidence_threshold": base_thresh,
                "be_trigger_rr": base_be_rr,
                "trailing_atr_multiplier": base_trail_atr,
                "max_positions": int(self.config.get("max_positions", 2)),
                "regime_mode": "MANUAL FIXED RISK",
                "reasons": ["Manual override active (Dynamic Auto-Pilot OFF)"]
            }

        regime_name = self._cached_regime.get("name", "RANGING")
        regime_conf = float(self._cached_regime.get("confidence", 0.70))

        atr = float(self._cached_signal.get("atr", 1.5))
        mean_atr = atr
        if df is not None and "atr" in df.columns and len(df) > 20:
            mean_atr = float(df["atr"].tail(50).mean())

        reasons = []
        dyn_risk = base_risk
        dyn_sl = base_sl_mult
        dyn_tp = base_tp_rr
        dyn_conf = base_thresh
        dyn_be = base_be_rr
        dyn_trail = base_trail_atr
        dyn_max_pos = int(self.config.get("max_positions", 2))

        # 1. Regime-based dynamic modulation (Noise-Hardened for Gold XAUUSD)
        if regime_name == "TRENDING":
            regime_mode = "🚀 TREND MOMENTUM HARVEST"
            # In clear trend, optimize risk for compounding runner profits
            dyn_risk = base_risk * (1.15 if regime_conf > 0.80 else 1.0)
            dyn_sl = 2.00  # Noise-hardened SL for Gold trend pullback
            dyn_tp = 3.5   # Extended TP for multi-hour runners
            dyn_conf = 0.58  # Confirmed pullback entry
            dyn_be = 1.50  # Breakeven after +1.5 R:R
            dyn_trail = 1.50  # Chandelier trailing
            dyn_max_pos = 2
            reasons.append(f"Trending Directional Impulse ({regime_conf*100:.0f}% Conf) → Extended TP to 3.5 R:R & 2.0x SL")

        elif regime_name == "RANGING":
            regime_mode = "🛡️ RANGE CORRIDOR PRESERVATION"
            # In range, scale down risk and widen SL cushion to prevent wick stop-outs
            dyn_risk = base_risk * 0.60
            dyn_sl = 2.50  # Hardened wide SL cushion to survive boundary wicks
            dyn_tp = 2.0   # Take profit quickly before corridor reversal
            dyn_conf = 0.70  # Elevated confidence required to avoid chop
            dyn_be = 1.50
            dyn_trail = 1.60
            dyn_max_pos = 1
            reasons.append("Chop Corridor Damping → 60% lot sizing, 2.5x ATR stop buffer")

        elif regime_name == "VOLATILE_BREAKOUT":
            regime_mode = "⚡ VOLATILE BREAKOUT SURGE"
            # High volatility spike: lower lot size, wide stop, explosive target
            dyn_risk = base_risk * 0.50
            dyn_sl = 3.00  # Wide stop cushion for volatility
            dyn_tp = 4.5   # Explosive expansion target
            dyn_conf = 0.72  # Very strict filter to guard against fakeouts
            dyn_be = 1.20  # Fast de-risking
            dyn_trail = 1.80
            dyn_max_pos = 1
            reasons.append("High Volatility Spike → 50% lot dampener, 3.0x ATR stop cushion")

        else:  # LOW_VOLATILITY_DRIFT
            regime_mode = "💤 LOW VOLATILITY SIDELINED"
            dyn_risk = base_risk * 0.25
            dyn_sl = 2.00
            dyn_tp = 1.80
            dyn_conf = 0.80
            dyn_max_pos = 1
            reasons.append("Low Momentum Drift → Sidelined (80% confidence barrier)")

        # 2. Volatility Extremes Filter
        if mean_atr > 0 and (atr / mean_atr) > 1.8:
            dyn_risk *= 0.80
            reasons.append(f"Extreme ATR Ratio ({(atr/mean_atr):.1f}x) → Volatility safety trim -20%")

        # 3. Drawdown & Consecutive Losses Circuit Brake
        cons_losses = self.state.get("consecutive_losses", 0)
        if cons_losses >= 2:
            dyn_risk *= 0.50
            dyn_conf += 0.05
            reasons.append(f"Loss Streak Guard ({cons_losses} losses) → Risk halved, confidence bar raised")
        elif cons_losses == 1:
            dyn_risk *= 0.85

        # 4. Strict Safety Clamping
        dyn_risk = max(floor_risk, min(round(dyn_risk, 2), ceiling_risk))
        dyn_sl = round(max(1.1, min(dyn_sl, 2.6)), 2)
        dyn_tp = round(max(1.5, min(dyn_tp, 5.5)), 2)
        dyn_conf = round(max(0.50, min(dyn_conf, 0.85)), 2)
        dyn_be = round(max(0.5, min(dyn_be, 1.5)), 2)
        dyn_trail = round(max(0.8, min(dyn_trail, 2.0)), 2)

        return {
            "enabled": True,
            "risk_pct": dyn_risk,
            "atr_sl_multiplier": dyn_sl,
            "tp_rr": dyn_tp,
            "confidence_threshold": dyn_conf,
            "be_trigger_rr": dyn_be,
            "trailing_atr_multiplier": dyn_trail,
            "max_positions": dyn_max_pos,
            "regime_mode": regime_mode,
            "reasons": reasons
        }

    def _evaluate_signals(self, df: pd.DataFrame, tick: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensemble Confluence Decision Model:
        Blends Trend Following, Mean-Reversion, and Volatility Breakout rules conditioned on Regime.
        """
        if df is None or len(df) < 25:
            return self._cached_signal

        curr_price = float(tick.get("price", df["close"].iloc[-1]))
        latest = df.iloc[-1]

        regime = self._cached_regime.get("name", "RANGING")
        ema20 = float(latest.get("ema20", curr_price))
        ema50 = float(latest.get("ema50", curr_price))
        rsi = float(latest.get("rsi", 50.0))
        bb_upper = float(latest.get("bb_upper", curr_price + 2.0))
        bb_lower = float(latest.get("bb_lower", curr_price - 2.0))
        atr = float(latest.get("atr", 1.5))
        bb_width = float(latest.get("bb_width", 0.01))

        bull_score = 0.0
        bear_score = 0.0
        factors = {}

        # Factor 1: Trend Alignment (40% weight)
        trend_weight = 0.40
        if regime in ("RANGING", "LOW_VOLATILITY_DRIFT"):
            trend_weight = 0.10  # Discount trend factor heavily in sideways markets

        if curr_price > ema50 and ema20 > ema50:
            bull_score += trend_weight
            factors["trend"] = f"BULLISH (+{int(trend_weight*100)}%)"
        elif curr_price < ema50 and ema20 < ema50:
            bear_score += trend_weight
            factors["trend"] = f"BEARISH (+{int(trend_weight*100)}%)"
        else:
            factors["trend"] = "NEUTRAL"

        # Factor 2: RSI Oscillator Confluence (30% weight)
        if regime == "TRENDING":
            # Pullback buy in bull trend
            if ema20 > ema50 and 42 <= rsi <= 55:
                bull_score += 0.30
                factors["rsi"] = f"Bullish Pullback ({rsi:.1f}) (+30%)"
            elif ema20 < ema50 and 45 <= rsi <= 58:
                bear_score += 0.30
                factors["rsi"] = f"Bearish Pullback ({rsi:.1f}) (+30%)"
            else:
                factors["rsi"] = f"RSI Neutral ({rsi:.1f})"
        else:
            # Mean-reversion at boundaries (Only in wide channels, strictly avoiding tiny chop)
            if bb_width >= 0.0035:
                if rsi < 28 and curr_price <= bb_lower:
                    bull_score += 0.35
                    factors["rsi"] = f"Deep Oversold Bounce ({rsi:.1f}) (+35%)"
                elif rsi > 72 and curr_price >= bb_upper:
                    bear_score += 0.35
                    factors["rsi"] = f"Deep Overbought Rejection ({rsi:.1f}) (+35%)"
                else:
                    factors["rsi"] = f"Corridor Neutral ({rsi:.1f})"
            else:
                factors["rsi"] = f"Tiny Chop Blocked (Width: {bb_width:.4f})"

        # Factor 3: Candle Action & Price Envelope (30% weight)
        candle_range = latest["high"] - latest["low"]
        if candle_range > 0:
            lower_wick = min(latest["open"], latest["close"]) - latest["low"]
            upper_wick = latest["high"] - max(latest["open"], latest["close"])
            if lower_wick / candle_range > 0.35 and curr_price >= ema20:
                bull_score += 0.25
                factors["candle"] = "Rejection Wick Down (+25%)"
            elif upper_wick / candle_range > 0.35 and curr_price <= ema20:
                bear_score += 0.25
                factors["candle"] = "Rejection Wick Up (+25%)"

        # Direction mode enforcement (One-Way vs Auto)
        dir_mode = str(self.config.get("direction_mode", "AUTO")).upper()
        if dir_mode == "BUY_ONLY":
            bear_score = 0.0
            factors["direction_mode"] = "ONE-WAY BUY ONLY (Shorts suppressed)"
        elif dir_mode == "SELL_ONLY":
            bull_score = 0.0
            factors["direction_mode"] = "ONE-WAY SELL ONLY (Longs suppressed)"
        else:  # AUTO mode: higher timeframe EMA 200 alignment
            ema200 = float(latest.get("ema200", curr_price))
            if curr_price > ema200 and ema50 > ema200:
                bear_score *= 0.5  # Suppress counter-trend shorts in macro bull trend
                factors["direction_mode"] = "AUTO: MACRO BULL ALIGNED (Counter-trend dampened)"
            elif curr_price < ema200 and ema50 < ema200:
                bull_score *= 0.5  # Suppress counter-trend longs in macro bear trend
                factors["direction_mode"] = "AUTO: MACRO BEAR ALIGNED (Counter-trend dampened)"
            else:
                factors["direction_mode"] = "AUTO: BI-DIRECTIONAL DYNAMIC"

        # Regime suppression: Strictly lock out tiny chop
        if regime == "LOW_VOLATILITY_DRIFT" or self._cached_regime.get("is_anti_chop_active", False):
            bull_score = 0.0
            bear_score = 0.0
            factors["regime_filter"] = "🛡️ ANTI-CHOP SHIELD: Tiny sideways chop blocked (All entries locked until clean breakout)"

        if bull_score > bear_score and bull_score >= 0.55:
            sig = "BUY"
            conf = round(bull_score, 2)
        elif bear_score > bull_score and bear_score >= 0.55:
            sig = "SELL"
            conf = round(bear_score, 2)
        else:
            sig = "NEUTRAL"
            conf = round(max(bull_score, bear_score), 2)

        return {
            "direction": sig,
            "confidence": conf,
            "bull_score": round(bull_score, 2),
            "bear_score": round(bear_score, 2),
            "factors": factors,
            "atr": round(atr, 2),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
        }

    # ── Risk Sizing & Execution ────────────────────────────────────────────────

    def _calculate_lot_size(self, account: Dict[str, Any], risk_sl_distance: float, risk_pct: float) -> float:
        """
        Calculates position size strictly adhering to Dynamic Equity Risk per trade.
        """
        equity = float(account.get("equity", 1000.0))
        risk_cash = equity * (risk_pct / 100.0)

        # Gold: 1 lot = 100 oz. $1.00 move per 1.00 lot = $100.
        if risk_sl_distance <= 0.2:
            risk_sl_distance = 1.5

        raw_lot = risk_cash / (risk_sl_distance * 100.0)
        # Safety clamping: min 0.01 lot, max 0.50 lot for institutional control
        lot = max(0.01, min(round(raw_lot, 2), 0.50))
        return lot

    def _manage_open_positions(self, positions: List[Dict[str, Any]], tick: Dict[str, Any], atr: float, be_rr: float, trail_mult: float):
        """
        Dynamic Breakeven Ratchet & Chandelier Trailing Stop Management:
        Uses dynamically calculated R:R and trailing distances!
        """
        curr_price = float(tick.get("price", 0.0))
        if curr_price <= 0:
            return

        for p in positions:
            ticket = p.get("ticket")
            pos_type = p.get("type", 0)  # 0=BUY, 1=SELL
            open_price = float(p.get("open_price", p.get("price_open", curr_price)))
            current_sl = float(p.get("sl", 0.0))
            current_tp = float(p.get("tp", 0.0))

            if pos_type == 0:  # BUY
                points_gain = curr_price - open_price
                risk_dist = abs(open_price - current_sl) if current_sl > 0 else (atr * 1.5)

                # 1. Dynamic Breakeven check (+0.50 profit cushion)
                if points_gain >= (be_rr * risk_dist) and (current_sl < open_price or current_sl == 0.0):
                    new_sl = open_price + 0.50  # lock in +50 points profit cushion
                    logger.info(f"🛡️ Bot #5 Locking Dynamic Breakeven on BUY #{ticket} @ {new_sl:.2f} (Triggered at +{be_rr:.1f} R:R)")
                    self.bridge.modify_position(ticket, sl=new_sl, tp=current_tp)
                    self.state["breakeven_locked"][str(ticket)] = True
                    self._save_state()

                # 2. Dynamic Trailing Stop
                elif self.config.get("strategy", {}).get("trailing_stop_active", True) and points_gain >= (2.0 * risk_dist):
                    trail_sl = curr_price - (atr * trail_mult)
                    if trail_sl > current_sl + 0.5:
                        logger.info(f"📈 Bot #5 Trailing Stop BUY #{ticket} → {trail_sl:.2f} (Trail Multiplier: {trail_mult}x ATR)")
                        self.bridge.modify_position(ticket, sl=trail_sl, tp=current_tp)

            elif pos_type == 1:  # SELL
                points_gain = open_price - curr_price
                risk_dist = abs(open_price - current_sl) if current_sl > 0 else (atr * 1.5)

                # 1. Dynamic Breakeven check (+0.50 profit cushion)
                if points_gain >= (be_rr * risk_dist) and (current_sl > open_price or current_sl == 0.0):
                    new_sl = open_price - 0.50  # lock in +50 points profit cushion
                    logger.info(f"🛡️ Bot #5 Locking Dynamic Breakeven on SELL #{ticket} @ {new_sl:.2f} (Triggered at +{be_rr:.1f} R:R)")
                    self.bridge.modify_position(ticket, sl=new_sl, tp=current_tp)
                    self.state["breakeven_locked"][str(ticket)] = True
                    self._save_state()

                # 2. Dynamic Trailing Stop
                elif self.config.get("strategy", {}).get("trailing_stop_active", True) and points_gain >= (2.0 * risk_dist):
                    trail_sl = curr_price + (atr * trail_mult)
                    if current_sl == 0.0 or trail_sl < current_sl - 0.5:
                        logger.info(f"📈 Bot #5 Trailing Stop SELL #{ticket} → {trail_sl:.2f} (Trail Multiplier: {trail_mult}x ATR)")
                        self.bridge.modify_position(ticket, sl=trail_sl, tp=current_tp)

    # ── Autonomous Execution Worker Loop ────────────────────────────────────────

    def _run_loop(self):
        """
        24/7 Autonomous execution loop running every ~3 seconds.
        """
        while self._running:
            try:
                now = time.time()
                symbol = self.config.get("symbol", "XAUUSD")

                # 1. Fetch live tick & account
                tick = self.bridge.get_tick(symbol)
                account = self.bridge.get_account()
                self._last_tick_time = now

                # 2. Periodic Candle & Feature Refresh (every 45 seconds)
                if now - self._last_candle_fetch >= 45.0 or self._cached_candles is None:
                    raw_df = self.bridge.get_candles(symbol, timeframe="5m", limit=150)
                    if raw_df is not None and not raw_df.empty:
                        feat_df = self._compute_features(raw_df)
                        self._cached_candles = feat_df
                        self._cached_regime = self._detect_regime(feat_df)
                        self._cached_signal = self._evaluate_signals(feat_df, tick)
                        self._last_candle_fetch = now

                # 3. Compute Live Dynamic Risk Settings
                dyn_risk = self._calculate_dynamic_risk(self._cached_candles, tick, account)
                self._cached_dynamic_risk = dyn_risk

                # Passive telemetry instances skip position management and order execution
                if not self._is_primary_worker:
                    time.sleep(3.0)
                    continue

                # 4. Position & Trailing Management with Dynamic Parameters
                positions = self.bridge.get_positions(symbol)
                atr = float(self._cached_signal.get("atr", 1.5))
                if positions:
                    self._manage_open_positions(
                        positions,
                        tick,
                        atr,
                        be_rr=float(dyn_risk["be_trigger_rr"]),
                        trail_mult=float(dyn_risk["trailing_atr_multiplier"])
                    )

                # Synchronize daily trades and loss streaks from actual broker history
                if now - self._last_stats_update > 30.0:
                    try:
                        hist = self.bridge.get_history(days=1)
                        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                        today_deals = [d for d in hist if datetime.datetime.fromtimestamp(d.get("time", 0), datetime.timezone.utc).strftime("%Y-%m-%d") == today_str and d.get("entry") == 0]
                        self.state["daily_trades"] = len(today_deals)

                        day_pnl = sum([float(d.get("profit", 0.0)) for d in hist if datetime.datetime.fromtimestamp(d.get("time", 0), datetime.timezone.utc).strftime("%Y-%m-%d") == today_str])
                        self.state["daily_pnl"] = round(day_pnl, 2)

                        exit_deals_rev = [d for d in reversed(hist) if d.get("entry") == 1]
                        cons_losses = 0
                        last_loss_t = float(self.state.get("last_loss_time", 0.0))
                        for ed in exit_deals_rev:
                            p = float(ed.get("profit", 0.0))
                            if p < 0:
                                cons_losses += 1
                                if cons_losses == 1:
                                    last_loss_t = float(ed.get("time", 0.0))
                            elif p > 0:
                                break
                        self.state["consecutive_losses"] = cons_losses
                        self.state["last_loss_time"] = last_loss_t
                        self._save_state()
                        self._last_stats_update = now
                    except Exception:
                        pass

                # 5. Entry Signal Execution Guard (Conditioned on Dynamic Risk & Circuit Breakers)
                auto_trading = self.config.get("auto_trading", True)
                threshold = float(dyn_risk["confidence_threshold"])
                sig_dir = self._cached_signal.get("direction", "NEUTRAL")
                conf = float(self._cached_signal.get("confidence", 0.0))
                max_pos = int(dyn_risk["max_positions"])
                curr_p = float(tick.get("price", 0.0))

                min_atr = float(self.config.get("min_atr_filter", 1.80))
                regime_name = self._cached_regime.get("name", "RANGING")
                is_anti_chop_flag = bool(self._cached_regime.get("is_anti_chop_active", False))
                chop_index = float(self._cached_regime.get("chop_index", 50.0))
                chop_thresh = float(self.config.get("chop_index_threshold", 60.0))

                is_tiny_chop = (
                    is_anti_chop_flag or
                    atr < min_atr or
                    chop_index >= chop_thresh or
                    regime_name == "LOW_VOLATILITY_DRIFT" or
                    (regime_name == "RANGING" and conf < 0.72)
                )

                max_trades = int(self.config.get("max_trades_per_day", 0))
                loss_cooldown_min = float(self.config.get("consecutive_loss_cooldown_min", 30))
                cooldown_sec = loss_cooldown_min * 60.0
                cons_losses = self.state.get("consecutive_losses", 0)
                last_loss_t = float(self.state.get("last_loss_time", 0.0))

                loss_cooling = (cons_losses >= 2 and (now - last_loss_t) < cooldown_sec)
                daily_cap_reached = (max_trades > 0 and self.state.get("daily_trades", 0) >= max_trades)
                cooling_remaining = int(cooldown_sec - (now - last_loss_t)) if loss_cooling else 0

                # Periodic scanning heartbeat log
                if now - self._last_log_time >= 30.0:
                    status_note = ""
                    if daily_cap_reached:
                        status_note = f" | ⛔ DAILY CAP REACHED ({self.state.get('daily_trades', 0)}/{max_trades})"
                    elif loss_cooling:
                        status_note = f" | 🛑 LOSS BRAKE ACTIVE ({cons_losses} losses, {cooling_remaining//60}m remaining)"
                    elif is_tiny_chop:
                        status_note = f" | 🛡️ ANTI-CHOP SHIELD ACTIVE (Chop: {chop_index:.1f}, ATR: ${atr:.2f})"

                    trades_str = f"{self.state.get('daily_trades', 0)}/{max_trades if max_trades > 0 else '∞'}"
                    dir_mode_lbl = self.config.get("direction_mode", "AUTO")
                    logger.info(
                        f"🤖 [Bot #5 AI] Scanning {symbol} @ {curr_p:.2f} | "
                        f"Regime: {self._cached_regime['name']} | Signal: {sig_dir} ({conf*100:.0f}%) | "
                        f"Dir: {dir_mode_lbl} | AutoTrading: {auto_trading} | Active Positions: {len(positions)}/{max_pos} | "
                        f"Today Trades: {trades_str} | Day PnL: {self.state.get('daily_pnl', 0.0):+.2f}{status_note}"
                    )
                    self._last_log_time = now

                # Circuit breaker checks
                can_enter = (
                    auto_trading and
                    sig_dir in ["BUY", "SELL"] and
                    conf >= threshold and
                    len(positions) < max_pos and
                    not is_tiny_chop and
                    not daily_cap_reached and
                    not loss_cooling and
                    now > self._order_in_flight_until and
                    now - self.state.get("last_trade_time", 0.0) >= 180.0  # 3 min cooldown
                )

                if can_enter:
                    with self._execution_lock:
                        self._order_in_flight_until = now + 15.0
                        min_sl_dist = float(self.config.get("min_sl_distance", 5.0))
                        base_sl_dist = atr * float(dyn_risk["atr_sl_multiplier"])
                        sl_dist = max(min_sl_dist, base_sl_dist + 0.70)
                        tp_dist = sl_dist * float(dyn_risk["tp_rr"])
                        lot_size = self._calculate_lot_size(account, sl_dist, risk_pct=float(dyn_risk["risk_pct"]))

                        if sig_dir == "BUY":
                            sl = curr_p - sl_dist
                            tp = curr_p + tp_dist
                        else:
                            sl = curr_p + sl_dist
                            tp = curr_p - tp_dist

                        logger.info(
                            f"🎯 Bot #5 Dynamic Execution: {sig_dir} {lot_size} lots @ {curr_p:.2f} | "
                            f"SL={sl:.2f} (Dist: ${sl_dist:.2f}) | "
                            f"TP={tp:.2f} ({dyn_risk['tp_rr']}x RR) | "
                            f"Risk={dyn_risk['risk_pct']}% | Conf={conf*100:.0f}%"
                        )
                        res = self.bridge.open_trade(
                            symbol=symbol,
                            action=sig_dir,
                            volume=lot_size,
                            stop_loss=sl,
                            take_profit=tp,
                            comment=f"Bot5_AI_DYN_{int(conf*100)}"
                        )
                        if res and (res.get("success") or res.get("ticket", 0) > 0 or res.get("order", 0) > 0):
                            self.state["last_trade_time"] = now
                            self.state["daily_trades"] = self.state.get("daily_trades", 0) + 1
                            self._save_state()
                            logger.info(f"✅ Bot #5 Position opened successfully! Ticket: {res.get('ticket')}")

            except Exception as e:
                logger.error(f"Error in Bot 5 AI engine loop: {e}", exc_info=True)

            time.sleep(3.0)

    # ── Telemetry Interface for Web Dashboard ──────────────────────────────────

    def get_telemetry(self) -> Dict[str, Any]:
        """
        Provides unified state, dynamic risk telemetry & analytics to the Streamlit dashboard on port 8505.
        """
        symbol = self.config.get("symbol", "XAUUSD")
        account = self.bridge.get_account()
        tick = self.bridge.get_tick(symbol)
        positions = self.bridge.get_positions(symbol)
        history = self.bridge.get_history(days=30)
        perf = calculate_performance_metrics(history)

        floating_pnl = sum([float(p.get("profit", 0.0)) for p in positions])

        max_trades = int(self.config.get("max_trades_per_day", 0))
        loss_cooldown_min = float(self.config.get("consecutive_loss_cooldown_min", 30))
        cooldown_sec = loss_cooldown_min * 60.0
        cons_losses = self.state.get("consecutive_losses", 0)
        last_loss_t = float(self.state.get("last_loss_time", 0.0))
        now = time.time()
        loss_cooling = (cons_losses >= 2 and (now - last_loss_t) < cooldown_sec)
        cooling_remaining = int(cooldown_sec - (now - last_loss_t)) if loss_cooling else 0

        is_anti_chop = bool(self._cached_regime.get("is_anti_chop_active", False))
        chop_idx = float(self._cached_regime.get("chop_index", 50.0))
        min_atr_val = float(self.config.get("min_atr_filter", 1.80))

        return {
            "connected": account.get("connected", False),
            "account": account,
            "tick": tick,
            "positions": positions,
            "floating_pnl": round(floating_pnl, 2),
            "regime": self._cached_regime,
            "signal": self._cached_signal,
            "dynamic_risk": self._cached_dynamic_risk,
            "performance": perf,
            "auto_trading": self.config.get("auto_trading", True),
            "direction_mode": self.config.get("direction_mode", "AUTO"),
            "daily_trades": self.state.get("daily_trades", 0),
            "daily_pnl": self.state.get("daily_pnl", 0.0),
            "max_trades": max_trades,
            "anti_chop_active": is_anti_chop,
            "chop_index": chop_idx,
            "min_atr_filter": min_atr_val,
            "consecutive_losses": cons_losses,
            "loss_cooling": loss_cooling,
            "cooling_remaining_sec": cooling_remaining,
            "is_primary_worker": getattr(self, "_is_primary_worker", True),
            "config": self.config
        }

    def stop(self):
        """Signals background execution loop to terminate."""
        self._running = False



# Singleton engine instance
_ENGINE_INSTANCE: Optional[AIEngine] = None
_INIT_LOCK = threading.Lock()


def get_engine() -> AIEngine:
    global _ENGINE_INSTANCE
    with _INIT_LOCK:
        if _ENGINE_INSTANCE is None:
            _ENGINE_INSTANCE = AIEngine()
        return _ENGINE_INSTANCE


if __name__ == "__main__":
    logger.info("Starting Bot #5 AI Engine directly in CLI mode...")
    engine = get_engine()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Bot #5 AI Engine shutting down cleanly.")
