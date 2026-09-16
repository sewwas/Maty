"""
Bot #1 — Sunrise 4-Phase State Engine
=====================================
Institutional quantitative implementation of the Sunrise Ogle Trading System:
1. Phase 1 — SCANNING: Multi-EMA Crossover (14/24/100) on closed 5-minute candles
2. Phase 2 — ARMED: Pullback validation (1-3 opposing candles) on closed candles
3. Phase 3 — WINDOW_OPEN: Breakout level calculation & channel breakout monitoring (live ticks)
4. Phase 4 — IN_POSITION: Dynamic ATR SL/TP, Trailing Stop Ratchet, and Position Management
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
    def __init__(self, config_path: Optional[str] = None, start_daemon: bool = True):
        if not config_path:
            config_path = os.path.join(_CURRENT_DIR, "config.json")
        self.config_path = config_path
        self.state_path = os.path.join(_CURRENT_DIR, "state.json")
        self.config = self._load_config()
        self.state = self._load_state()

        # Synchronization & timing
        self._execution_lock = threading.Lock()
        self._order_in_flight = False
        self._last_m5_fetch = 0.0
        self._last_tick_time = 0.0
        self._last_heartbeat = 0.0
        self._last_closed_candle_time: Optional[str] = self.state.get("last_closed_candle_time", None)

        # Market data cache
        self._cached_candles: Optional[pd.DataFrame] = None
        self._indicators: Dict[str, float] = {}
        self._open_positions: List[Dict[str, Any]] = []

        # 4-Phase State Machine variables
        self.phase: str = self.state.get("phase", "SCANNING")
        self.armed_direction: Optional[str] = self.state.get("armed_direction", None)
        self.pullback_candle_count: int = self.state.get("pullback_candle_count", 0)
        self.breakout_level: Optional[float] = self.state.get("breakout_level", None)
        self.signal_candle_time: Optional[str] = self.state.get("signal_candle_time", None)
        self.window_open_candle_time: Optional[str] = self.state.get("window_open_candle_time", None)
        self.signal_atr: float = float(self.state.get("signal_atr", 0.0))

        # Bridge client
        bridge_url = self.config.get("bridge_url", "http://127.0.0.1:8001")
        magic = int(self.config.get("magic_number", 101001))
        self.bridge = Bot1BridgeClient(bridge_url=bridge_url, magic_number=magic)

        # Background daemon thread
        self._running = False
        self._thread: Optional[threading.Thread] = None
        if start_daemon:
            self.start()

        logger.info(f"🌅 Bot #1 Sunrise initialized | Magic: {magic} | Bridge: {bridge_url}")

    def start(self):
        """Starts background monitoring and execution loop."""
        with self._execution_lock:
            if not self._running:
                self._running = True
                self._thread = threading.Thread(target=self._run_loop, daemon=True, name="Bot1_Engine_Loop")
                self._thread.start()
                logger.info("Bot #1 Engine background thread started.")

    def stop(self):
        """Signals background execution loop to terminate cleanly."""
        self._running = False

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
            "signal_candle_time": None,
            "window_open_candle_time": None,
            "signal_atr": 0.0,
            "last_closed_candle_time": None,
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
            "signal_candle_time": self.signal_candle_time,
            "window_open_candle_time": self.window_open_candle_time,
            "signal_atr": self.signal_atr,
            "last_closed_candle_time": self._last_closed_candle_time,
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
        """
        Calculates Multi-EMA (14/24/100), ATR, and RSI metrics.
        Computes on closed candles (df[:-1]) to prevent flickering noise.
        """
        strat = self.config.get("strategy", {})
        fast_len = int(strat.get("ema_fast", 14))
        slow_len = int(strat.get("ema_slow", 24))
        filter_len = int(strat.get("ema_filter", 100))
        atr_len = int(strat.get("atr_period", 10))

        # We compute series across all available bars
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # EMAs
        df["ema_fast"] = close.ewm(span=fast_len, adjust=False).mean()
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

        # Use the last CLOSED candle (df.iloc[-2]) for stable signal processing
        # and df.iloc[-1] for current live bar visualization
        last_closed = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        prev_closed = df.iloc[-3] if len(df) >= 3 else last_closed
        live_forming = df.iloc[-1]

        return {
            # Current forming bar metrics (for display)
            "price": float(live_forming["close"]),
            "live_ema_fast": float(live_forming["ema_fast"]),
            "live_ema_slow": float(live_forming["ema_slow"]),
            "live_ema_filter": float(live_forming["ema_filter"]),
            "atr": float(last_closed["atr"]) if not np.isnan(last_closed["atr"]) else 2.0,
            "rsi": float(last_closed["rsi"]) if not np.isnan(last_closed["rsi"]) else 50.0,

            # Last CLOSED candle metrics (for signal evaluation)
            "closed_time": str(last_closed["timestamp"]),
            "closed_close": float(last_closed["close"]),
            "closed_open": float(last_closed["open"]),
            "closed_high": float(last_closed["high"]),
            "closed_low": float(last_closed["low"]),
            "closed_ema_fast": float(last_closed["ema_fast"]),
            "closed_ema_slow": float(last_closed["ema_slow"]),
            "closed_ema_filter": float(last_closed["ema_filter"]),

            # Prior CLOSED candle metrics (for crossover detection)
            "prev_closed_close": float(prev_closed["close"]),
            "prev_closed_fast": float(prev_closed["ema_fast"]),
            "prev_closed_slow": float(prev_closed["ema_slow"])
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

                # 2. Fetch M5 candles periodically (every 5s)
                if now - self._last_m5_fetch > 5.0 or self._cached_candles is None:
                    df = self.bridge.get_candles(symbol=symbol, timeframe="5m", limit=120)
                    if df is not None and len(df) >= 30:
                        self._cached_candles = df
                        self._indicators = self._calculate_indicators(df)
                        self._last_m5_fetch = now

                # 3. Update open positions from bridge
                self._open_positions = self.bridge.get_positions(symbol)

                # Position state transition
                if len(self._open_positions) > 0:
                    if self.phase != "IN_POSITION":
                        self.phase = "IN_POSITION"
                        self._save_state()
                    if curr_price > 0:
                        self._manage_open_positions(curr_price)
                else:
                    if self.phase == "IN_POSITION":
                        logger.info("🏁 Active trade closed. Returning to SCANNING.")
                        self.phase = "SCANNING"
                        self.armed_direction = None
                        self.pullback_candle_count = 0
                        self.breakout_level = None
                        self.signal_candle_time = None
                        self.window_open_candle_time = None
                        self._save_state()

                # 4. If auto_trading enabled and not in position, evaluate state machine
                if self.config.get("auto_trading", True) and len(self._open_positions) == 0:
                    if curr_price > 0:
                        self._evaluate_state_machine(curr_price)

                # Periodic heartbeat log
                if now - self._last_heartbeat > 60.0:
                    self._last_heartbeat = now
                    logger.info(
                        f"📊 [Bot #1 Sunrise] Phase: {self.phase} | Price: {curr_price:.2f} | "
                        f"Fast EMA: {self._indicators.get('closed_ema_fast', 0):.2f} | "
                        f"Slow EMA: {self._indicators.get('closed_ema_slow', 0):.2f} | "
                        f"ATR: {self._indicators.get('atr', 0):.2f}"
                    )

            except Exception as e:
                logger.error(f"Error in Bot 1 engine loop: {e}", exc_info=True)

            time.sleep(2.5)

    def _evaluate_state_machine(self, current_price: float):
        """Core 4-phase state machine logic driven by closed candles and live breakout ticks."""
        if not self._indicators or self._cached_candles is None or current_price <= 0:
            return

        ind = self._indicators
        strat = self.config.get("strategy", {})
        mode = self.config.get("trading_mode", "BOTH")
        use_filter = strat.get("use_price_filter", True)
        atr = max(ind.get("atr", 2.0), 0.5)

        closed_time = ind["closed_time"]
        is_new_closed_candle = (closed_time != self._last_closed_candle_time)

        # ── PHASE 1: SCANNING (Evaluated ONLY on newly closed candles) ─────────────
        if self.phase == "SCANNING":
            if not is_new_closed_candle:
                return

            c_close = ind["closed_close"]
            c_fast = ind["closed_ema_fast"]
            c_slow = ind["closed_ema_slow"]
            c_filter = ind["closed_ema_filter"]

            p_close = ind["prev_closed_close"]
            p_fast = ind["prev_closed_fast"]

            # Bullish Crossover: fast EMA > slow EMA and price crossed above fast EMA
            bull_cross = (p_close <= p_fast) and (c_close > c_fast) and (c_fast > c_slow)
            long_filter_ok = (c_close > c_filter) if use_filter else True

            if bull_cross and long_filter_ok and mode in ["BOTH", "LONG_ONLY"]:
                logger.info(f"🎯 [Bot #1] Bullish Crossover! Closed Price {c_close:.2f} > Fast {c_fast:.2f}. Arming LONG.")
                self.phase = "ARMED"
                self.armed_direction = "LONG"
                self.pullback_candle_count = 0
                self.signal_candle_time = closed_time
                self.signal_atr = atr
                self._last_closed_candle_time = closed_time
                self._save_state()
                return

            # Bearish Crossunder: fast EMA < slow EMA and price crossed below fast EMA
            bear_cross = (p_close >= p_fast) and (c_close < c_fast) and (c_fast < c_slow)
            short_filter_ok = (c_close < c_filter) if use_filter else True

            if bear_cross and short_filter_ok and mode in ["BOTH", "SHORT_ONLY"]:
                logger.info(f"🎯 [Bot #1] Bearish Crossunder! Closed Price {c_close:.2f} < Fast {c_fast:.2f}. Arming SHORT.")
                self.phase = "ARMED"
                self.armed_direction = "SHORT"
                self.pullback_candle_count = 0
                self.signal_candle_time = closed_time
                self.signal_atr = atr
                self._last_closed_candle_time = closed_time
                self._save_state()
                return

            self._last_closed_candle_time = closed_time

        # ── PHASE 2: ARMED (Pullback Confirmation on closed candles) ───────────────
        elif self.phase == "ARMED":
            # Real-time invalidation: price violates slow EMA in opposite direction
            if self.armed_direction == "LONG" and (current_price < ind["closed_ema_slow"]):
                logger.info("⚠️ [Bot #1] Opposing trend invalidation. Resetting LONG arm to SCANNING.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self._save_state()
                return
            elif self.armed_direction == "SHORT" and (current_price > ind["closed_ema_slow"]):
                logger.info("⚠️ [Bot #1] Opposing trend invalidation. Resetting SHORT arm to SCANNING.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self._save_state()
                return

            # Only advance candle count on NEW closed candle
            if not is_new_closed_candle:
                return

            self._last_closed_candle_time = closed_time
            c_open = ind["closed_open"]
            c_close = ind["closed_close"]

            # Calculate closed candles since signal
            df_closed = self._cached_candles[:-1]
            if self.signal_candle_time:
                bars_since_signal = len(df_closed[df_closed["timestamp"].astype(str) >= self.signal_candle_time])
            else:
                bars_since_signal = 1

            if self.armed_direction == "LONG":
                # Red pullback candle: close < open
                if c_close < c_open:
                    self.pullback_candle_count += 1
                    logger.info(f"🔄 [Bot #1] Pullback candle #{self.pullback_candle_count} confirmed (Red candle).")

                if self.pullback_candle_count >= 1:
                    # Breakout level is the high of the pullback sequence + 0.10
                    recent_highs = df_closed["high"].tail(self.pullback_candle_count + 1).max()
                    self.breakout_level = float(recent_highs) + 0.10
                    self.phase = "WINDOW_OPEN"
                    self.window_open_candle_time = closed_time
                    logger.info(f"🚪 [Bot #1] Breakout Window OPEN (LONG). Trigger High: {self.breakout_level:.2f}")
                    self._save_state()
                    return

            elif self.armed_direction == "SHORT":
                # Green pullback candle: close > open
                if c_close > c_open:
                    self.pullback_candle_count += 1
                    logger.info(f"🔄 [Bot #1] Pullback candle #{self.pullback_candle_count} confirmed (Green candle).")

                if self.pullback_candle_count >= 1:
                    # Breakout level is the low of the pullback sequence - 0.10
                    recent_lows = df_closed["low"].tail(self.pullback_candle_count + 1).min()
                    self.breakout_level = float(recent_lows) - 0.10
                    self.phase = "WINDOW_OPEN"
                    self.window_open_candle_time = closed_time
                    logger.info(f"🚪 [Bot #1] Breakout Window OPEN (SHORT). Trigger Low: {self.breakout_level:.2f}")
                    self._save_state()
                    return

            # Invalidation: if too many bars pass without pullback
            if bars_since_signal > 12:
                logger.info("⏱️ [Bot #1] Armed state expired after 12 bars without pullback. Resetting.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self._save_state()

        # ── PHASE 3: WINDOW_OPEN (Breakout Monitoring on live ticks) ───────────────
        elif self.phase == "WINDOW_OPEN":
            # Window Expiry calculation using elapsed closed bars
            df_closed = self._cached_candles[:-1]
            if self.window_open_candle_time:
                bars_since_window = len(df_closed[df_closed["timestamp"].astype(str) > self.window_open_candle_time])
            else:
                bars_since_window = 0

            window_periods = int(
                strat.get("long_entry_window_periods", 5)
                if self.armed_direction == "LONG"
                else strat.get("short_entry_window_periods", 7)
            )

            if bars_since_window > window_periods:
                logger.info(f"⏱️ [Bot #1] Breakout window expired after {bars_since_window} bars. Resetting to SCANNING.")
                self.phase = "SCANNING"
                self.armed_direction = None
                self.breakout_level = None
                self._save_state()
                return

            # Live Tick Breakout Check
            if self.armed_direction == "LONG" and self.breakout_level is not None:
                if current_price >= self.breakout_level and current_price > 0:
                    logger.info(f"🚀 [Bot #1] LONG BREAKOUT TRIGGERED! Price {current_price:.2f} >= {self.breakout_level:.2f}")
                    self._execute_entry("BUY", current_price, atr)

            elif self.armed_direction == "SHORT" and self.breakout_level is not None:
                if current_price <= self.breakout_level and current_price > 0:
                    logger.info(f"🚀 [Bot #1] SHORT BREAKOUT TRIGGERED! Price {current_price:.2f} <= {self.breakout_level:.2f}")
                    self._execute_entry("SELL", current_price, atr)

    def _execute_entry(self, direction: str, entry_price: float, current_atr: float):
        """Dispatches order via bridge with calculated ATR SL and TP."""
        if self._order_in_flight or entry_price <= 0:
            return

        with self._execution_lock:
            self._order_in_flight = True
            try:
                symbol = self.config.get("symbol", "XAUUSD")
                lot_size = float(self.config.get("lot_size", 0.01))
                strat = self.config.get("strategy", {})
                atr = max(current_atr, 1.0)

                if direction == "BUY":
                    sl_mult = float(strat.get("long_atr_sl_multiplier", 4.5))
                    tp_mult = float(strat.get("long_atr_tp_multiplier", 6.5))
                    sl_price = round(entry_price - (atr * sl_mult), 2)
                    tp_price = round(entry_price + (atr * tp_mult), 2)
                else:
                    sl_mult = float(strat.get("short_atr_sl_multiplier", 2.5))
                    tp_mult = float(strat.get("short_atr_tp_multiplier", 6.5))
                    sl_price = round(entry_price + (atr * sl_mult), 2)
                    tp_price = round(entry_price - (atr * tp_mult), 2)
                    if tp_price <= 0:
                        tp_price = round(entry_price * 0.95, 2)

                logger.info(
                    f"⚡ [Bot #1 Order] {direction} {lot_size} {symbol} | "
                    f"Price: {entry_price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}"
                )

                res = self.bridge.send_order(
                    action=direction,
                    symbol=symbol,
                    volume=lot_size,
                    price=entry_price,
                    sl=sl_price,
                    tp=tp_price,
                    comment=f"Auto Grid {direction} M5"
                )

                if res.get("success") or res.get("retcode") in (0, 10009, 10008, 10004) or res.get("order"):
                    logger.info("✅ Order dispatched successfully to MT5!")
                    self.phase = "IN_POSITION"
                    self.state["trades_today"] = self.state.get("trades_today", 0) + 1
                    self._save_state()
                else:
                    logger.warning(f"⚠️ Order dispatch response: {res}")
            finally:
                self._order_in_flight = False

    def _manage_open_positions(self, current_price: float):
        """Dynamic Trailing Stop Ratchet for active trades."""
        strat = self.config.get("strategy", {})
        if not strat.get("trailing_stop_active", True) or current_price <= 0:
            return

        atr = max(self._indicators.get("atr", 2.0), 1.0)
        step = float(strat.get("trailing_step_atr", 1.0)) * atr

        for pos in self._open_positions:
            ticket = pos.get("ticket")
            p_type = str(pos.get("type", "")).upper()
            open_p = float(pos.get("open_price", pos.get("price_open", current_price)))
            curr_sl = float(pos.get("sl", 0.0))

            if "BUY" in p_type or p_type == "0":
                profit_dist = current_price - open_p
                # Ratchet SL once in profit by 1.5x ATR
                if profit_dist >= (1.5 * atr):
                    new_sl = round(current_price - step, 2)
                    if new_sl > curr_sl and (new_sl > open_p):
                        logger.info(f"🛡️ [Trailing Stop] Ratcheting SL for Ticket #{ticket}: {curr_sl:.2f} -> {new_sl:.2f}")
                        self.bridge.modify_position(ticket=ticket, sl=new_sl)

            elif "SELL" in p_type or p_type == "1":
                profit_dist = open_p - current_price
                if profit_dist >= (1.5 * atr):
                    new_sl = round(current_price + step, 2)
                    if (curr_sl == 0.0 or new_sl < curr_sl) and (new_sl < open_p):
                        logger.info(f"🛡️ [Trailing Stop] Ratcheting SL for Ticket #{ticket}: {curr_sl:.2f} -> {new_sl:.2f}")
                        self.bridge.modify_position(ticket=ticket, sl=new_sl)

    def close_all_trades(self) -> Dict[str, Any]:
        """Emergency manual kill switch closing all open positions immediately."""
        symbol = self.config.get("symbol", "XAUUSD")
        res = self.bridge.close_all_positions(symbol)
        self._open_positions = []
        self.phase = "SCANNING"
        self.armed_direction = None
        self.pullback_candle_count = 0
        self.breakout_level = None
        self.signal_candle_time = None
        self.window_open_candle_time = None
        self._save_state()
        logger.info("🚨 [Emergency Kill Switch] All Bot #1 positions closed, state reset to SCANNING.")
        return res

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


# Global Singleton instance
_ENGINE_INSTANCE: Optional[SunriseEngine] = None
_INSTANCE_LOCK = threading.Lock()


def get_engine(start_daemon: bool = True) -> SunriseEngine:
    global _ENGINE_INSTANCE
    with _INSTANCE_LOCK:
        if _ENGINE_INSTANCE is None:
            _ENGINE_INSTANCE = SunriseEngine(start_daemon=start_daemon)
        elif start_daemon and not _ENGINE_INSTANCE._running:
            _ENGINE_INSTANCE.start()
        return _ENGINE_INSTANCE


if __name__ == "__main__":
    logger.info("Starting Bot #1 Sunrise directly in CLI daemon mode...")
    engine = get_engine(start_daemon=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Bot #1 Engine shutting down cleanly.")
        engine.stop()
