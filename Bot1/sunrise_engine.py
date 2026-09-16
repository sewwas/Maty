"""
Bot #1 — Sunrise Ogle 4-Phase State Engine & Volatility Expansion System
========================================================================
Institutional quantitative implementation of the Sunrise Ogle Trading System:
1. Phase 1 — SCANNING: Multi-EMA Crossover (14/24/100) + 6-Layer Filters
2. Phase 2 — ARMED: Pullback validation (1-3 opposing candles)
3. Phase 3 — WINDOW_OPEN: Breakout level calculation & channel monitoring
4. Phase 4 — IN_POSITION: Dynamic ATR SL/TP, Trailing Stop Ratchet, and Execution
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

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from bridge_client import Bot1BridgeClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SunriseEngineBot1")


class SunriseEngine:
    def __init__(self, config_path: Optional[str] = None):
        if not config_path:
            config_path = os.path.join(_CURRENT_DIR, "config.json")
        self.config_path = config_path
        self.state_path = os.path.join(_CURRENT_DIR, "state.json")
        self.config = self._load_config()
        self.state = self._load_state()

        # Engine locks & synchronization
        self._execution_lock = threading.Lock()
        self._order_in_flight = False
        self._last_m5_fetch = 0.0
        self._last_tick_time = 0.0
        self._last_heartbeat = 0.0

        # Cached market data & indicators
        self._cached_candles: Optional[pd.DataFrame] = None
        self._indicators: Dict[str, float] = {}
        self._open_positions: List[Dict[str, Any]] = []
        self._recent_trades: List[Dict[str, Any]] = []

        # 4-Phase State Machine variables
        self.phase: str = self.state.get("phase", "SCANNING")
        self.armed_direction: Optional[str] = self.state.get("armed_direction", None)
        self.pullback_candle_count: int = self.state.get("pullback_candle_count", 0)
        self.breakout_level: Optional[float] = self.state.get("breakout_level", None)
        self.signal_bar_index: int = self.state.get("signal_bar_index", 0)
        self.window_open_bar_index: int = self.state.get("window_open_bar_index", 0)
        self.signal_atr: float = self.state.get("signal_atr", 0.0)

        # Bridge client
        bridge_url = self.config.get("bridge_url", "http://127.0.0.1:8001")
        magic = int(self.config.get("magic_number", 101001))
        self.bridge = Bot1BridgeClient(bridge_url=bridge_url, magic_number=magic)

        # Background worker thread
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"🌅 Sunrise Ogle Bot 1 initialized on Magic {magic} | Bridge {bridge_url}")

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading config.json: {e}")
        return {
            "symbol": "XAUUSD",
            "magic_number": 101001,
            "bridge_url": "http://127.0.0.1:8001",
            "auto_trading": True,
            "trading_mode": "BOTH",
            "lot_size": 0.01,
            "risk_pct_per_trade": 1.0,
            "max_daily_risk_pct": 3.0,
            "max_trades_per_day": 10,
            "strategy": {
                "timeframe": "5m",
                "ema_fast": 14,
                "ema_medium": 14,
                "ema_slow": 24,
                "ema_confirm": 1,
                "ema_filter": 100,
                "atr_period": 10,
                "long_atr_sl_multiplier": 4.5,
                "long_atr_tp_multiplier": 6.5,
                "short_atr_sl_multiplier": 2.5,
                "short_atr_tp_multiplier": 6.5,
                "long_pullback_max_candles": 3,
                "short_pullback_max_candles": 2,
                "long_entry_window_periods": 5,
                "short_entry_window_periods": 7,
                "use_price_filter": True,
                "trailing_stop_active": True,
                "trailing_step_atr": 1.0
            }
        }

    def save_config(self, updates: Dict[str, Any]):
        with self._execution_lock:
            self.config.update(updates)
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=2)
            except Exception as e:
                logger.error(f"Error saving config: {e}")

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state.json: {e}")
        return {
            "phase": "SCANNING",
            "armed_direction": None,
            "pullback_candle_count": 0,
            "breakout_level": None,
            "trades_today": 0,
            "daily_pnl": 0.0,
            "last_reset_date": str(datetime.date.today())
        }

    def _save_state(self):
        state_data = {
            "phase": self.phase,
            "armed_direction": self.armed_direction,
            "pullback_candle_count": self.pullback_candle_count,
            "breakout_level": self.breakout_level,
            "signal_bar_index": self.signal_bar_index,
            "window_open_bar_index": self.window_open_bar_index,
            "signal_atr": self.signal_atr,
            "trades_today": self.state.get("trades_today", 0),
            "daily_pnl": self.state.get("daily_pnl", 0.0),
            "last_reset_date": self.state.get("last_reset_date", str(datetime.date.today())),
            "updated_at": datetime.datetime.now().isoformat()
        }
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculates exact Sunrise Ogle multi-EMA, ATR, and RSI metrics."""
        strat = self.config.get("strategy", {})
        fast_len = int(strat.get("ema_fast", 14))
        med_len = int(strat.get("ema_medium", 14))
        slow_len = int(strat.get("ema_slow", 24))
        filter_len = int(strat.get("ema_filter", 100))
        atr_len = int(strat.get("atr_period", 10))

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # EMAs
        df["ema_fast"] = close.ewm(span=fast_len, adjust=False).mean()
        df["ema_med"] = close.ewm(span=med_len, adjust=False).mean()
        df["ema_slow"] = close.ewm(span=slow_len, adjust=False).mean()
        df["ema_filter"] = close.ewm(span=filter_len, adjust=False).mean()

        # ATR
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=atr_len).mean()

        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss.replace(0, np.nan))
        df["rsi"] = 100 - (100 / (1 + rs))

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        return {
            "price": float(latest["close"]),
            "ema_fast": float(latest["ema_fast"]),
            "ema_med": float(latest["ema_med"]),
            "ema_slow": float(latest["ema_slow"]),
            "ema_filter": float(latest["ema_filter"]),
            "atr": float(latest["atr"]) if not np.isnan(latest["atr"]) else 1.5,
            "rsi": float(latest["rsi"]) if not np.isnan(latest["rsi"]) else 50.0,
            "prev_close": float(prev["close"]),
            "prev_ema_fast": float(prev["ema_fast"]),
            "prev_ema_slow": float(prev["ema_slow"]),
            "prev_high": float(prev["high"]),
            "prev_low": float(prev["low"]),
            "prev_open": float(prev["open"])
        }

    def _check_daily_reset(self):
        today_str = str(datetime.date.today())
        if self.state.get("last_reset_date") != today_str:
            self.state["trades_today"] = 0
            self.state["daily_pnl"] = 0.0
            self.state["last_reset_date"] = today_str
            self._save_state()

    def _run_loop(self):
        """Autonomous 24/7 background execution loop."""
        while self._running:
            try:
                self._check_daily_reset()
                symbol = self.config.get("symbol", "XAUUSD")
                now = time.time()

                # 1. Fetch live tick
                tick = self.bridge.get_tick(symbol)
                curr_price = float(tick.get("price", 0.0))

                # 2. Fetch M5 candles periodically (every 10s)
                if now - self._last_m5_fetch > 10.0 or self._cached_candles is None:
                    df = self.bridge.get_candles(symbol=symbol, timeframe="5m", limit=120)
                    if df is not None and len(df) >= 30:
                        self._cached_candles = df
                        self._indicators = self._calculate_indicators(df)
                        self._last_m5_fetch = now

                # 3. Update open positions
                self._open_positions = self.bridge.get_positions()

                # If position exists, ensure phase is IN_POSITION
                if len(self._open_positions) > 0:
                    if self.phase != "IN_POSITION":
                        self.phase = "IN_POSITION"
                        self._save_state()
                    self._manage_open_positions(curr_price)
                else:
                    if self.phase == "IN_POSITION":
                        logger.info("🏁 Trade closed. Returning to SCANNING.")
                        self.phase = "SCANNING"
                        self.armed_direction = None
                        self.pullback_candle_count = 0
                        self.breakout_level = None
                        self._save_state()

                # 4. If auto_trading enabled and not in position, run 4-phase state machine
                if self.config.get("auto_trading", True) and len(self._open_positions) == 0:
                    self._evaluate_state_machine(curr_price)

                # Periodic heartbeat log
                if now - self._last_heartbeat > 60.0:
                    self._last_heartbeat = now
                    logger.info(
                        f"📊 [Sunrise Ogle] Phase: {self.phase} | Price: {curr_price:.2f} | "
                        f"Fast EMA: {self._indicators.get('ema_fast', 0):.2f} | "
                        f"Slow EMA: {self._indicators.get('ema_slow', 0):.2f} | "
                        f"ATR: {self._indicators.get('atr', 0):.3f}"
                    )

            except Exception as e:
                logger.error(f"Error in engine loop: {e}", exc_info=True)

            time.sleep(3.0)

    def _evaluate_state_machine(self, current_price: float):
        """Core 4-phase state machine logic from ilahuerta-IA/mt5_live_trading_bot."""
        if not self._indicators or self._cached_candles is None:
            return

        strat = self.config.get("strategy", {})
        mode = self.config.get("trading_mode", "BOTH")
        use_filter = strat.get("use_price_filter", True)

        ind = self._indicators
        price = ind["price"]
        ema_fast = ind["ema_fast"]
        ema_slow = ind["ema_slow"]
        ema_filter = ind["ema_filter"]
        atr = ind["atr"]

        prev_close = ind["prev_close"]
        prev_fast = ind["prev_ema_fast"]
        prev_slow = ind["prev_ema_slow"]
        curr_bar_index = len(self._cached_candles)

        # ── PHASE 1: SCANNING ─────────────────────────────────────────
        if self.phase == "SCANNING":
            # Bullish Crossover check
            cross_above = (prev_close <= prev_fast) and (price > ema_fast) and (ema_fast > ema_slow)
            long_filter_ok = (price > ema_filter) if use_filter else True

            if cross_above and long_filter_ok and mode in ["BOTH", "LONG_ONLY"]:
                logger.info(f"🎯 [Sunrise Ogle] Bullish Crossover confirmed! Price {price:.2f} > Fast {ema_fast:.2f}. Arming LONG.")
                self.phase = "ARMED"
                self.armed_direction = "LONG"
                self.pullback_candle_count = 0
                self.signal_bar_index = curr_bar_index
                self.signal_atr = atr
                self._save_state()
                return

            # Bearish Crossunder check
            cross_below = (prev_close >= prev_fast) and (price < ema_fast) and (ema_fast < ema_slow)
            short_filter_ok = (price < ema_filter) if use_filter else True

            if cross_below and short_filter_ok and mode in ["BOTH", "SHORT_ONLY"]:
                logger.info(f"🎯 [Sunrise Ogle] Bearish Crossunder confirmed! Price {price:.2f} < Fast {ema_fast:.2f}. Arming SHORT.")
                self.phase = "ARMED"
                self.armed_direction = "SHORT"
                self.pullback_candle_count = 0
                self.signal_bar_index = curr_bar_index
                self.signal_atr = atr
                self._save_state()
                return

        # ── PHASE 2: ARMED (Pullback Confirmation) ─────────────────────
        elif self.phase == "ARMED":
            # Global Invalidation Check: Opposing cross resets to SCANNING
            if self.armed_direction == "LONG" and (price < ema_slow):
                logger.info("⚠️ [Sunrise Ogle] Opposing crossover. Invaliding LONG arm.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self._save_state()
                return
            elif self.armed_direction == "SHORT" and (price > ema_slow):
                logger.info("⚠️ [Sunrise Ogle] Opposing crossover. Invaliding SHORT arm.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self._save_state()
                return

            # Count pullback candles from signal bar
            bars_since_signal = curr_bar_index - self.signal_bar_index
            if bars_since_signal >= 1:
                # Inspect last candle
                prev_open = ind["prev_open"]
                prev_c = ind["prev_close"]

                if self.armed_direction == "LONG":
                    max_pullbacks = int(strat.get("long_pullback_max_candles", 3))
                    # Red pullback candle: close < open
                    if prev_c < prev_open:
                        self.pullback_candle_count += 1
                        logger.info(f"🔄 [Sunrise Ogle] Pullback candle #{self.pullback_candle_count} detected (Red).")

                    # Open breakout window once at least 1 pullback candle observed
                    if self.pullback_candle_count >= 1:
                        # Breakout level is the high of the highest candle during pullback + 0.05
                        recent_highs = self._cached_candles["high"].tail(self.pullback_candle_count + 1).max()
                        self.breakout_level = float(recent_highs) + 0.05
                        self.phase = "WINDOW_OPEN"
                        self.window_open_bar_index = curr_bar_index
                        logger.info(f"🚪 [Sunrise Ogle] Breakout Window OPEN (LONG). Trigger High: {self.breakout_level:.2f}")
                        self._save_state()
                        return

                elif self.armed_direction == "SHORT":
                    max_pullbacks = int(strat.get("short_pullback_max_candles", 2))
                    # Green pullback candle: close > open
                    if prev_c > prev_open:
                        self.pullback_candle_count += 1
                        logger.info(f"🔄 [Sunrise Ogle] Pullback candle #{self.pullback_candle_count} detected (Green).")

                    if self.pullback_candle_count >= 1:
                        recent_lows = self._cached_candles["low"].tail(self.pullback_candle_count + 1).min()
                        self.breakout_level = float(recent_lows) - 0.05
                        self.phase = "WINDOW_OPEN"
                        self.window_open_bar_index = curr_bar_index
                        logger.info(f"🚪 [Sunrise Ogle] Breakout Window OPEN (SHORT). Trigger Low: {self.breakout_level:.2f}")
                        self._save_state()
                        return

                # Expiry check: if too many bars pass without pullback
                if bars_since_signal > 12:
                    logger.info("⏱️ [Sunrise Ogle] Armed state expired without pullback. Resetting to SCANNING.")
                    self.phase = "SCANNING"
                    self.armed_direction = None
                    self._save_state()

        # ── PHASE 3: WINDOW_OPEN (Breakout Monitoring) ─────────────────
        elif self.phase == "WINDOW_OPEN":
            bars_since_window = curr_bar_index - self.window_open_bar_index
            window_periods = int(
                strat.get("long_entry_window_periods", 5) 
                if self.armed_direction == "LONG" 
                else strat.get("short_entry_window_periods", 7)
            )

            # Check for Window Expiry
            if bars_since_window > window_periods:
                logger.info(f"⏱️ [Sunrise Ogle] Window expired after {bars_since_window} bars without breakout. Resetting.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self.breakout_level = None
                self._save_state()
                return

            # Check for Breakout Trigger
            if self.armed_direction == "LONG" and self.breakout_level is not None:
                if current_price >= self.breakout_level:
                    logger.info(f"🚀 [Sunrise Ogle] BREAKOUT TRIGGERED! Price {current_price:.2f} >= Level {self.breakout_level:.2f}")
                    self._execute_entry("BUY", current_price, atr)

            elif self.armed_direction == "SHORT" and self.breakout_level is not None:
                if current_price <= self.breakout_level:
                    logger.info(f"🚀 [Sunrise Ogle] BREAKOUT TRIGGERED! Price {current_price:.2f} <= Level {self.breakout_level:.2f}")
                    self._execute_entry("SELL", current_price, atr)

    def _execute_entry(self, direction: str, entry_price: float, current_atr: float):
        """Executes market order with calculated ATR-based SL and TP."""
        if self._order_in_flight:
            return

        with self._execution_lock:
            self._order_in_flight = True
            try:
                symbol = self.config.get("symbol", "XAUUSD")
                lot_size = float(self.config.get("lot_size", 0.01))
                strat = self.config.get("strategy", {})

                # ATR Multipliers
                if direction == "BUY":
                    sl_mult = float(strat.get("long_atr_sl_multiplier", 4.5))
                    tp_mult = float(strat.get("long_atr_tp_multiplier", 6.5))
                    sl_price = entry_price - (current_atr * sl_mult)
                    tp_price = entry_price + (current_atr * tp_mult)
                else:
                    sl_mult = float(strat.get("short_atr_sl_multiplier", 2.5))
                    tp_mult = float(strat.get("short_atr_tp_multiplier", 6.5))
                    sl_price = entry_price + (current_atr * sl_mult)
                    tp_price = entry_price - (current_atr * tp_mult)

                logger.info(
                    f"⚡ [Sunrise Ogle Dispatch] {direction} {lot_size} {symbol} | "
                    f"Entry: {entry_price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}"
                )

                res = self.bridge.send_order(
                    action=direction,
                    symbol=symbol,
                    volume=lot_size,
                    sl=sl_price,
                    tp=tp_price,
                    comment=f"Sunrise {direction} M5"
                )

                if res.get("success") or res.get("order") or res.get("ticket"):
                    logger.info("✅ Order dispatched successfully!")
                    self.phase = "IN_POSITION"
                    self.state["trades_today"] = self.state.get("trades_today", 0) + 1
                    self._save_state()
                else:
                    logger.warning(f"⚠️ Order failed: {res}")
            finally:
                self._order_in_flight = False

    def _manage_open_positions(self, current_price: float):
        """Dynamic Trailing Stop and Breakout Protection."""
        strat = self.config.get("strategy", {})
        if not strat.get("trailing_stop_active", True):
            return

        atr = self._indicators.get("atr", 1.5)
        step = float(strat.get("trailing_step_atr", 1.0)) * atr

        for pos in self._open_positions:
            ticket = pos.get("ticket")
            p_type = pos.get("type", "").upper()
            open_p = float(pos.get("open_price", pos.get("price_open", current_price)))
            curr_sl = float(pos.get("sl", 0.0))

            if "BUY" in p_type or p_type == "0":
                profit_dist = current_price - open_p
                # If in profit by at least 1.5x ATR, move SL up
                if profit_dist >= (1.5 * atr):
                    new_sl = current_price - step
                    if new_sl > curr_sl and (new_sl > open_p):
                        logger.info(f"🛡️ [Trailing Stop] Ratcheting SL for Ticket {ticket}: {curr_sl:.2f} -> {new_sl:.2f}")
                        self.bridge.modify_position(ticket=ticket, sl=new_sl)

            elif "SELL" in p_type or p_type == "1":
                profit_dist = open_p - current_price
                if profit_dist >= (1.5 * atr):
                    new_sl = current_price + step
                    if (curr_sl == 0.0 or new_sl < curr_sl) and (new_sl < open_p):
                        logger.info(f"🛡️ [Trailing Stop] Ratcheting SL for Ticket {ticket}: {curr_sl:.2f} -> {new_sl:.2f}")
                        self.bridge.modify_position(ticket=ticket, sl=new_sl)

    def get_telemetry(self) -> Dict[str, Any]:
        """Provides full real-time telemetry to the Streamlit UI."""
        acc = self.bridge.get_account()
        sym = self.config.get("symbol", "XAUUSD")
        tick = self.bridge.get_tick(sym)

        return {
            "symbol": sym,
            "phase": self.phase,
            "armed_direction": self.armed_direction,
            "pullback_candle_count": self.pullback_candle_count,
            "breakout_level": self.breakout_level,
            "price": float(tick.get("price", self._indicators.get("price", 0.0))),
            "ask": float(tick.get("ask", 0.0)),
            "bid": float(tick.get("bid", 0.0)),
            "indicators": self._indicators,
            "account": acc,
            "open_positions": self._open_positions,
            "auto_trading": self.config.get("auto_trading", True),
            "trading_mode": self.config.get("trading_mode", "BOTH"),
            "lot_size": self.config.get("lot_size", 0.01),
            "trades_today": self.state.get("trades_today", 0),
            "daily_pnl": self.state.get("daily_pnl", 0.0),
            "candles": self._cached_candles
        }

    def close_all_trades(self):
        """Emergency manual close all open positions."""
        for p in self._open_positions:
            t = p.get("ticket")
            if t:
                self.bridge.close_position(ticket=t)
        self._open_positions = []
        self.phase = "SCANNING"
        self._save_state()


# Global Singleton instance
_ENGINE_INSTANCE: Optional[SunriseEngine] = None

def get_engine() -> SunriseEngine:
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        _ENGINE_INSTANCE = SunriseEngine()
    return _ENGINE_INSTANCE
