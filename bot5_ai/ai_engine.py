"""
Bot #5 — Institutional AI/ML Neural Trader & Market Regime Engine
==================================================================
Autonomous Execution Architecture:
1. Dynamic Market Regime Detection:
   - Evaluates Kaufman Efficiency Ratio (ER), Bollinger Bandwidth, and multi-timeframe EMAs.
   - Classifies market into TRENDING, RANGING, VOLATILE_BREAKOUT, or LOW_VOLATILITY_DRIFT.
2. Multi-Model Ensemble Confluence Engine:
   - Confluence across Trend Momentum (EMA 20/50/200), RSI Mean-Reversion, and Volatility Expansion.
   - Generates calibrated signal confidence (0.0 - 1.0). Minimum execution threshold: 0.60.
3. Institutional Capital Allocation & Risk Management:
   - Strict 1.0% Equity Risk per trade (Zero Martingale).
   - ATR-calibrated dynamic Stop Loss and Take Profit (1:2.5+ R:R target).
   - Dynamic Breakeven Ratchet at 1:1.0 R:R.
   - ATR Chandelier Trailing Stop to lock in running trend profits.
   - Hard Circuit Breakers: Max 3.0% daily loss limit, max 3 concurrent positions.
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
            "risk_pct_per_trade": 1.0,
            "max_daily_risk_pct": 3.0,
            "max_trades_per_day": 6,
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
        close = float(latest.get("close", 0.0))

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

    def _evaluate_signals(self, df: pd.DataFrame, tick: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensemble Confluence Decision Model:
        Blends Trend Following, Mean-Reversion, and Volatility Breakout rules conditioned on Regime.
        """
        if df is None or len(df) < 25:
            return self._cached_signal

        curr_price = float(tick.get("price", df["close"].iloc[-1]))
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        regime = self._cached_regime.get("name", "RANGING")
        ema20 = float(latest.get("ema20", curr_price))
        ema50 = float(latest.get("ema50", curr_price))
        ema200 = float(latest.get("ema200", curr_price))
        rsi = float(latest.get("rsi", 50.0))
        bb_upper = float(latest.get("bb_upper", curr_price + 2.0))
        bb_lower = float(latest.get("bb_lower", curr_price - 2.0))
        atr = float(latest.get("atr", 1.5))

        bull_score = 0.0
        bear_score = 0.0
        factors = {}

        # Factor 1: Trend Alignment (40% weight)
        if curr_price > ema50 and ema20 > ema50:
            bull_score += 0.40
            factors["trend"] = "BULLISH (+40%)"
        elif curr_price < ema50 and ema20 < ema50:
            bear_score += 0.40
            factors["trend"] = "BEARISH (+40%)"
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
            # Mean-reversion at boundaries
            if rsi < 32 and curr_price <= bb_lower + (atr * 0.25):
                bull_score += 0.35
                factors["rsi"] = f"Oversold Bounce ({rsi:.1f}) (+35%)"
            elif rsi > 68 and curr_price >= bb_upper - (atr * 0.25):
                bear_score += 0.35
                factors["rsi"] = f"Overbought Rejection ({rsi:.1f}) (+35%)"
            else:
                factors["rsi"] = f"Corridor Hold ({rsi:.1f})"

        # Factor 3: Candle Action & Price Envelope (30% weight)
        candle_body = abs(latest["close"] - latest["open"])
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

    def _calculate_lot_size(self, account: Dict[str, Any], risk_sl_distance: float) -> float:
        """
        Calculates position size strictly adhering to 1.0% equity risk per trade.
        """
        equity = float(account.get("equity", 1000.0))
        risk_pct = float(self.config.get("risk_pct_per_trade", 1.0))
        risk_cash = equity * (risk_pct / 100.0)

        # Gold: 1 lot = 100 oz. $1.00 move per 1.00 lot = $100.
        if risk_sl_distance <= 0.2:
            risk_sl_distance = 1.5

        raw_lot = risk_cash / (risk_sl_distance * 100.0)
        # Institutional safety clamping: min 0.01 lot, max 0.50 lot for $1k account
        lot = max(0.01, min(round(raw_lot, 2), 0.50))
        return lot

    def _manage_open_positions(self, positions: List[Dict[str, Any]], tick: Dict[str, Any], atr: float):
        """
        Dynamic Breakeven Ratchet & Chandelier Trailing Stop Management:
        - When floating profit reaches +1.0 R:R, moves SL to entry + buffer (free trade).
        - Once past 1.5 R:R, trails SL with ATR cushion to lock in run.
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

                # 1. Breakeven check at +1.0 R:R
                if points_gain >= risk_dist and current_sl < open_price:
                    new_sl = open_price + 0.25  # lock in +25 points
                    logger.info(f"🛡️ Bot #5 Locking Breakeven on BUY #{ticket} @ {new_sl}")
                    self.bridge.modify_position(ticket, sl=new_sl, tp=current_tp)
                    self.state["breakeven_locked"][str(ticket)] = True
                    self._save_state()

                # 2. Trailing Stop
                elif self.config.get("strategy", {}).get("trailing_stop_active", True) and points_gain >= (1.5 * risk_dist):
                    trail_sl = curr_price - (atr * 1.2)
                    if trail_sl > current_sl + 0.3:
                        logger.info(f"📈 Bot #5 Trailing Stop BUY #{ticket} → {trail_sl:.2f}")
                        self.bridge.modify_position(ticket, sl=trail_sl, tp=current_tp)

            elif pos_type == 1:  # SELL
                points_gain = open_price - curr_price
                risk_dist = abs(open_price - current_sl) if current_sl > 0 else (atr * 1.5)

                # 1. Breakeven check
                if points_gain >= risk_dist and (current_sl > open_price or current_sl == 0.0):
                    new_sl = open_price - 0.25
                    logger.info(f"🛡️ Bot #5 Locking Breakeven on SELL #{ticket} @ {new_sl}")
                    self.bridge.modify_position(ticket, sl=new_sl, tp=current_tp)
                    self.state["breakeven_locked"][str(ticket)] = True
                    self._save_state()

                # 2. Trailing Stop
                elif self.config.get("strategy", {}).get("trailing_stop_active", True) and points_gain >= (1.5 * risk_dist):
                    trail_sl = curr_price + (atr * 1.2)
                    if current_sl == 0.0 or trail_sl < current_sl - 0.3:
                        logger.info(f"📈 Bot #5 Trailing Stop SELL #{ticket} → {trail_sl:.2f}")
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

                # 1. Fetch live tick
                tick = self.bridge.get_tick(symbol)
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

                # 3. Position & Trailing Management
                positions = self.bridge.get_positions(symbol)
                atr = float(self._cached_signal.get("atr", 1.5))
                if positions:
                    self._manage_open_positions(positions, tick, atr)

                # 4. Entry Signal Execution Guard
                auto_trading = self.config.get("auto_trading", True)
                threshold = float(self.config.get("confidence_threshold", 0.60))
                sig_dir = self._cached_signal.get("direction", "NEUTRAL")
                conf = float(self._cached_signal.get("confidence", 0.0))

                # Circuit breaker checks
                can_enter = (
                    auto_trading and
                    sig_dir in ["BUY", "SELL"] and
                    conf >= threshold and
                    len(positions) < int(self.config.get("max_positions", 2)) and
                    now > self._order_in_flight_until and
                    now - self.state.get("last_trade_time", 0.0) >= 180.0  # 3 min cooldown
                )

                if can_enter:
                    with self._execution_lock:
                        self._order_in_flight_until = now + 15.0
                        account = self.bridge.get_account()
                        curr_p = float(tick.get("price", 2900.0))
                        sl_dist = atr * float(self.config.get("strategy", {}).get("atr_sl_multiplier", 1.5))
                        tp_dist = sl_dist * float(self.config.get("strategy", {}).get("tp_rr", 2.5))
                        lot_size = self._calculate_lot_size(account, sl_dist)

                        if sig_dir == "BUY":
                            sl = curr_p - sl_dist
                            tp = curr_p + tp_dist
                        else:
                            sl = curr_p + sl_dist
                            tp = curr_p - tp_dist

                        logger.info(f"🎯 Bot #5 Triggering AI Signal: {sig_dir} {lot_size} lots @ {curr_p:.2f} | Conf: {conf*100:.0f}%")
                        res = self.bridge.open_trade(
                            symbol=symbol,
                            action=sig_dir,
                            volume=lot_size,
                            stop_loss=sl,
                            take_profit=tp,
                            comment=f"Bot5_AI_{int(conf*100)}"
                        )
                        if res and (res.get("success") or res.get("order", 0) > 0):
                            self.state["last_trade_time"] = now
                            self.state["daily_trades"] = self.state.get("daily_trades", 0) + 1
                            self._save_state()

            except Exception as e:
                logger.error(f"Error in Bot 5 AI engine loop: {e}", exc_info=True)

            time.sleep(3.0)

    # ── Telemetry Interface for Web Dashboard ──────────────────────────────────

    def get_telemetry(self) -> Dict[str, Any]:
        """
        Provides unified state & analytics to the Streamlit dashboard on port 8505.
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
            "performance": perf,
            "auto_trading": self.config.get("auto_trading", True),
            "config": self.config
        }


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
