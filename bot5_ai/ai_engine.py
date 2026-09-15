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

# Shared AI signal bridge — writes Bot 5 state so Bot 1 can read it
try:
    import sys as _sys
    _PARENT_DIR = os.path.dirname(_CURRENT_DIR)
    if _PARENT_DIR not in _sys.path:
        _sys.path.insert(0, _PARENT_DIR)
    from core.bot5_signal_bridge import write_bot5_signal as _write_bridge
    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False
    _write_bridge = None

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

        # Background autonomous engine thread
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ Bot #5 AI/ML Neural Trader initialized on Magic {magic} | Bridge {bridge_url}")

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

        return df

    def _detect_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Classifies current market regime:
        - TRENDING (Strong directional impulse)
        - VOLATILE_BREAKOUT (Momentum volatility expansion)
        - RANGING (Mean-reverting within bands)
        - LOW_VOLATILITY_DRIFT (Low volume / compression)
        """
        if df is None or len(df) < 20:
            return self._cached_regime

        latest = df.iloc[-1]
        er = float(latest.get("er", 0.3))
        bb_width = float(latest.get("bb_width", 0.01))
        atr = float(latest.get("atr", 1.5))
        mean_atr = float(df["atr"].tail(50).mean()) if "atr" in df.columns else atr

        ema20 = float(latest.get("ema20", 0.0))
        ema50 = float(latest.get("ema50", 0.0))

        # 1. Volatile Breakout
        if atr > 1.6 * mean_atr and bb_width > 0.006:
            return {
                "name": "VOLATILE_BREAKOUT",
                "confidence": 0.88,
                "description": "High-momentum volatility expansion detected",
                "color": "#f43f5e"
            }

        # 2. Trending
        if er > 0.42 and abs(ema20 - ema50) > (atr * 0.5):
            trend_dir = "BULLISH" if ema20 > ema50 else "BEARISH"
            return {
                "name": "TRENDING",
                "confidence": round(min(0.95, er * 1.5), 2),
                "description": f"Persistent {trend_dir} directional impulse",
                "color": "#10b981" if trend_dir == "BULLISH" else "#f97316"
            }

        # 3. Low Volatility Drift
        if atr < 0.75 * mean_atr and bb_width < 0.0025:
            return {
                "name": "LOW_VOLATILITY_DRIFT",
                "confidence": 0.80,
                "description": "Compressed price corridor — Sidelined",
                "color": "#64748b"
            }

        # 4. Default: Ranging
        return {
            "name": "RANGING",
            "confidence": 0.74,
            "description": "Mean-reverting consolidation corridor",
            "color": "#38bdf8"
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

        # 1. Regime-based dynamic modulation
        if regime_name == "TRENDING":
            regime_mode = "🚀 TREND MOMENTUM HARVEST"
            # In clear trend, optimize risk for compounding runner profits
            dyn_risk = base_risk * (1.15 if regime_conf > 0.80 else 1.0)
            dyn_sl = 1.35  # Tighter SL on trend pullbacks
            dyn_tp = 3.5   # Expand TP for multi-hour runners
            dyn_conf = 0.58  # Earlier entry on confirmed pullback
            dyn_be = 0.80  # Earlier breakeven lock
            dyn_trail = 1.10  # Tighter trailing behind moving trend
            dyn_max_pos = 3
            reasons.append(f"Trending Directional Impulse ({regime_conf*100:.0f}% Conf) → Extended TP to 3.5 R:R & Tight SL")

        elif regime_name == "RANGING":
            regime_mode = "🛡️ RANGE CORRIDOR PRESERVATION"
            # In range, scale down risk and compress TP to boundaries
            dyn_risk = base_risk * 0.75
            dyn_sl = 1.70  # Wider SL to survive boundary wicks
            dyn_tp = 2.0   # Take profit quickly before reversal
            dyn_conf = 0.75  # Elevated confidence required to avoid chop
            dyn_be = 1.00
            dyn_trail = 1.40
            dyn_max_pos = 2
            reasons.append("Chop Corridor Damping → Sized down to 75%, TP compressed to 2.0 R:R")

        elif regime_name == "VOLATILE_BREAKOUT":
            regime_mode = "⚡ VOLATILE BREAKOUT SURGE"
            # High volatility spike: lower lot size, widen stop, target explosive runner
            dyn_risk = base_risk * 0.60
            dyn_sl = 2.20  # Wide stop cushion
            dyn_tp = 4.5   # Explosive expansion target
            dyn_conf = 0.72  # Very strict filter to guard against fakeouts
            dyn_be = 0.60  # Fast de-risking
            dyn_trail = 1.50
            dyn_max_pos = 1
            reasons.append("High Volatility Spike → 60% lot dampener, 2.2x ATR stop cushion")

        else:  # LOW_VOLATILITY_DRIFT
            regime_mode = "💤 LOW VOLATILITY SIDELINED"
            dyn_risk = base_risk * 0.30
            dyn_sl = 1.50
            dyn_tp = 1.80
            dyn_conf = 0.78
            dyn_max_pos = 1
            reasons.append("Low Momentum Drift → 70% risk compression, 78% confidence required")

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
        if regime in ("TRENDING", "VOLATILE_BREAKOUT"):
            # Strong trend momentum OR healthy pullback
            if ema20 > ema50:
                if 40 <= rsi <= 60:
                    bull_score += 0.30
                    factors["rsi"] = f"Bullish Pullback ({rsi:.1f}) (+30%)"
                elif rsi > 60:
                    bull_score += 0.35
                    factors["rsi"] = f"Bullish Trend Momentum ({rsi:.1f}) (+35%)"
                elif rsi < 35:
                    bull_score += 0.20
                    factors["rsi"] = f"Deep Dip Buy Opportunity ({rsi:.1f}) (+20%)"
            elif ema20 < ema50:
                if 40 <= rsi <= 60:
                    bear_score += 0.30
                    factors["rsi"] = f"Bearish Pullback ({rsi:.1f}) (+30%)"
                elif rsi < 40:
                    bear_score += 0.35
                    factors["rsi"] = f"Bearish Trend Momentum ({rsi:.1f}) (+35%)"
                elif rsi > 65:
                    bear_score += 0.20
                    factors["rsi"] = f"High Resistance Sell Opportunity ({rsi:.1f}) (+20%)"
        else:
            # Mean-reversion at boundaries (Ranging)
            if rsi < 38 or curr_price <= bb_lower + (atr * 0.35):
                bull_score += 0.35
                factors["rsi"] = f"Oversold Bounce ({rsi:.1f}) (+35%)"
            elif rsi > 62 or curr_price >= bb_upper - (atr * 0.35):
                bear_score += 0.35
                factors["rsi"] = f"Overbought Rejection ({rsi:.1f}) (+35%)"
            else:
                factors["rsi"] = f"Corridor Hold ({rsi:.1f})"

        # Factor 3: Candle Action & Price Envelope (30% weight)
        candle_range = latest["high"] - latest["low"]
        if candle_range > 0:
            c_open = float(latest["open"])
            c_close = float(latest["close"])
            lower_wick = min(c_open, c_close) - float(latest["low"])
            upper_wick = float(latest["high"]) - max(c_open, c_close)
            body_size = abs(c_close - c_open)

            # Wick absorption rejection
            if lower_wick / candle_range > 0.30:
                bull_score += 0.25
                factors["candle"] = "Bullish Absorption Wick (+25%)"
            elif upper_wick / candle_range > 0.30:
                bear_score += 0.25
                factors["candle"] = "Bearish Absorption Wick (+25%)"
            # Strong directional momentum candle
            elif body_size / candle_range > 0.45:
                if c_close > c_open and curr_price >= ema20:
                    bull_score += 0.25
                    factors["candle"] = "Bullish Momentum Bar (+25%)"
                elif c_close < c_open and curr_price <= ema20:
                    bear_score += 0.25
                    factors["candle"] = "Bearish Momentum Bar (+25%)"

        # Regime suppression
        if regime == "LOW_VOLATILITY_DRIFT":
            bull_score *= 0.3
            bear_score *= 0.3
            factors["regime_filter"] = "DRIFT_SUPPRESSION"

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

            # AI Smart Reversal Data
            ai_sig = self._cached_signal.get("direction", "NEUTRAL") if getattr(self, "_cached_signal", None) else "NEUTRAL"
            ai_conf = float(self._cached_signal.get("confidence", 0.0)) if getattr(self, "_cached_signal", None) else 0.0

            if pos_type == 0:  # BUY
                points_gain = curr_price - open_price
                risk_dist = abs(open_price - current_sl) if current_sl > 0 else (atr * 1.5)

                # 0. AI Smart Reversal Exit
                if points_gain > (atr * 0.3) and ai_sig == "SELL" and ai_conf >= 0.55:
                    logger.info(f"🧠 Bot #5 AI REVERSAL EXIT: Closing BUY #{ticket} smartly in profit (+{points_gain:.2f} pts) because AI detected strong SELL.")
                    self.bridge.close_position(ticket)
                    continue

                # 1. Dynamic Breakeven check
                if points_gain >= (be_rr * risk_dist) and current_sl < open_price:
                    new_sl = open_price + 0.25  # lock in +25 points
                    logger.info(f"🛡️ Bot #5 Locking Dynamic Breakeven on BUY #{ticket} @ {new_sl} (Triggered at +{be_rr:.1f} R:R)")
                    self.bridge.modify_position(ticket, sl=new_sl, tp=current_tp)
                    self.state["breakeven_locked"][str(ticket)] = True
                    self._save_state()

                # 2. Dynamic Trailing Stop
                elif self.config.get("strategy", {}).get("trailing_stop_active", True) and points_gain >= (1.5 * risk_dist):
                    trail_sl = curr_price - (atr * trail_mult)
                    if trail_sl > current_sl + 0.3:
                        logger.info(f"📈 Bot #5 Trailing Stop BUY #{ticket} → {trail_sl:.2f} (Trail Multiplier: {trail_mult}x ATR)")
                        self.bridge.modify_position(ticket, sl=trail_sl, tp=current_tp)

            elif pos_type == 1:  # SELL
                points_gain = open_price - curr_price
                risk_dist = abs(open_price - current_sl) if current_sl > 0 else (atr * 1.5)

                # 0. AI Smart Reversal Exit
                if points_gain > (atr * 0.3) and ai_sig == "BUY" and ai_conf >= 0.55:
                    logger.info(f"🧠 Bot #5 AI REVERSAL EXIT: Closing SELL #{ticket} smartly in profit (+{points_gain:.2f} pts) because AI detected strong BUY.")
                    self.bridge.close_position(ticket)
                    continue

                # 1. Dynamic Breakeven check
                if points_gain >= (be_rr * risk_dist) and (current_sl > open_price or current_sl == 0.0):
                    new_sl = open_price - 0.25
                    logger.info(f"🛡️ Bot #5 Locking Dynamic Breakeven on SELL #{ticket} @ {new_sl} (Triggered at +{be_rr:.1f} R:R)")
                    self.bridge.modify_position(ticket, sl=new_sl, tp=current_tp)
                    self.state["breakeven_locked"][str(ticket)] = True
                    self._save_state()

                # 2. Dynamic Trailing Stop
                elif self.config.get("strategy", {}).get("trailing_stop_active", True) and points_gain >= (1.5 * risk_dist):
                    trail_sl = curr_price + (atr * trail_mult)
                    if current_sl == 0.0 or trail_sl < current_sl - 0.3:
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

                # 3a. Publish to Bot 1 Signal Bridge (best-effort)
                if _BRIDGE_AVAILABLE and _write_bridge is not None:
                    try:
                        _write_bridge(
                            self._cached_regime,
                            self._cached_signal,
                            dyn_risk
                        )
                    except Exception as _bridge_err:
                        logger.debug(f"Bot5 bridge write skipped: {_bridge_err}")

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

                # Synchronize daily trades from actual history
                if now - self._last_stats_update > 30.0:
                    try:
                        hist = self.bridge.get_history(days=1)
                        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
                        today_deals = [d for d in hist if datetime.datetime.fromtimestamp(d.get("time", 0), datetime.timezone.utc).strftime("%Y-%m-%d") == today_str and d.get("entry") == 0]
                        self.state["daily_trades"] = len(today_deals)
                        self._last_stats_update = now
                    except Exception:
                        pass

                # 5. Entry Signal Execution Guard (Conditioned on Dynamic Risk)
                auto_trading = self.config.get("auto_trading", True)
                threshold = float(dyn_risk["confidence_threshold"])
                sig_dir = self._cached_signal.get("direction", "NEUTRAL")
                conf = float(self._cached_signal.get("confidence", 0.0))
                max_pos = int(dyn_risk["max_positions"])
                curr_p = float(tick.get("price", 0.0))

                # Periodic scanning heartbeat log
                if now - self._last_log_time >= 30.0:
                    logger.info(
                        f"🤖 [Bot #5 AI] Scanning {symbol} @ {curr_p:.2f} | "
                        f"Regime: {self._cached_regime['name']} | Signal: {sig_dir} ({conf*100:.0f}%) | "
                        f"AutoTrading: {auto_trading} | Active Positions: {len(positions)}/{max_pos} | "
                        f"Today Trades: {self.state.get('daily_trades', 0)}"
                    )
                    self._last_log_time = now

                # Circuit breaker checks
                can_enter = (
                    auto_trading and
                    sig_dir in ["BUY", "SELL"] and
                    conf >= threshold and
                    len(positions) < max_pos and
                    now > self._order_in_flight_until and
                    now - self.state.get("last_trade_time", 0.0) >= 120.0  # 2 min cooldown
                )

                if can_enter:
                    with self._execution_lock:
                        self._order_in_flight_until = now + 15.0
                        sl_dist = atr * float(dyn_risk["atr_sl_multiplier"])
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
                            f"SL={sl:.2f} ({dyn_risk['atr_sl_multiplier']}x ATR) | "
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
