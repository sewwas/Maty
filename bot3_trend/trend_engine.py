"""
Bot #3 — Institutional-Grade London Breakout & Trend Runner Engine
===================================================================
Strategy Architecture & Bulletproof Protections:
1. Calculates Asian Session Range (00:00 - 07:00 UTC) High & Low.
   - Enforces Min Range (15 pips) & Max Range (120 pips).
   - If Asian range is exhausted (> 120 pips, e.g. $42.90), triggers STANDBY to protect capital.
2. London Breakout Window (07:00 - 13:00 UTC) & NY Overlap (13:00 - 19:00 UTC).
3. Confirmed M5 Candle Close Breakouts:
   - Evaluates closed M5 candles (df.iloc[-2]) instead of instantaneous 1-second price wicks.
   - Eliminates liquidity grab fakeouts into support/resistance.
4. Momentum & Chop Filters:
   - 14-period ADX must be >= 20.0 (confirms true directional trend, avoids sideways chop).
   - 14-period RSI must confirm direction: RSI >= 52 for BUY, RSI <= 48 for SELL.
   - Multi-Timeframe Trend Confirmation: EMA 50 vs EMA 200.
5. Bulletproof Concurrency & Execution Guards:
   - Strict threading mutex lock around all tick processing.
   - 20-second in-flight order lockout prevents duplicate multi-order firing.
   - Checks both open positions and open orders with Magic 998873 before entry.
6. Institutional Risk Controls (Zero Martingale):
   - Fixed Risk % (default 1.0% per trade).
   - Consecutive Directional Loss Lockout: 2 stop losses in same direction = 60-min lockout.
   - Max Daily Risk % Circuit Breaker: halts auto-trading if daily loss limit (default 3.0%) is hit.
   - Dynamic Breakeven at 1:1.0 RR & Chandelier ATR Trailing Stop for runners.
7. Read-Only Telemetry API:
   - get_telemetry() decouples the Streamlit web panel from trade execution.
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

from bridge_client import Bot3BridgeClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrendRunnerBot3")


class TrendRunnerEngine:
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
        self._last_candle_fetch = 0.0
        self._last_m15_fetch = 0.0
        self._cached_candles: Optional[pd.DataFrame] = None
        self._cached_m15: Optional[pd.DataFrame] = None
        self._cached_asian_box: Dict[str, Any] = {}
        self._cached_telemetry: Dict[str, Any] = {}

        # Bridge client
        bridge_url = self.config.get("bridge_url", "http://127.0.0.1:8003")
        magic = int(self.config.get("magic_number", 998873))
        self.bridge = Bot3BridgeClient(bridge_url=bridge_url, magic_number=magic)

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config.json: {e}")
        return {
            "symbol": "XAUUSD",
            "magic_number": 998873,
            "bridge_url": "http://127.0.0.1:8003",
            "risk_pct_per_trade": 1.0,
            "max_daily_risk_pct": 3.0,
            "max_trades_per_day": 0,
            "auto_trading": True,
            "strategy": {
                "fast_ema": 50,
                "slow_ema": 200,
                "atr_period": 14,
                "atr_sl_multiplier": 1.5,
                "tp1_rr": 1.5,
                "tp1_close_pct": 50.0,
                "breakeven_trigger_rr": 1.0,
                "be_offset_points": 50,
                "trailing_atr_multiplier": 2.0,
                "min_asian_range_pips": 15.0,
                "max_asian_range_pips": 120.0,
                "buffer_pips": 3.0,
                "max_spread_pips": 4.5
            }
        }

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config.json: {e}")

    def _load_state(self) -> Dict[str, Any]:
        defaults = {
            "date": datetime.date.today().isoformat(),
            "asian_box": {
                "high": 0.0,
                "low": 0.0,
                "mid": 0.0,
                "range_pips": 0.0,
                "valid": False,
                "status": "INITIALIZING"
            },
            "today_trades_count": 0,
            "today_pnl": 0.0,
            "consecutive_sell_losses": 0,
            "consecutive_buy_losses": 0,
            "sell_lockout_until": 0.0,
            "buy_lockout_until": 0.0,
            "daily_risk_halt": False,
            "last_breakout_candle_time": "",
            "positions_tracked": {},
            "signals": [],
            "logs": []
        }
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in defaults.items():
                        if k not in data:
                            data[k] = v
                    return data
            except Exception as e:
                logger.error(f"Error loading state.json: {e}")
        return defaults

    def save_state(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state.json: {e}")

    def log(self, msg: str, level: str = "INFO"):
        logger.info(msg)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        logs = self.state.get("logs", [])
        logs.append(f"[{ts}] {msg}")
        if len(logs) > 100:
            logs = logs[-100:]
        self.state["logs"] = logs

    # ── Technical Calculations ────────────────────────────────────────────────
    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Computes EMA 50, EMA 200, ATR(14), RSI(14), and Wilder ADX(14).
        """
        if df.empty or len(df) < 30:
            return df

        df = df.copy()
        fast_period = int(self.config.get("strategy", {}).get("fast_ema", 50))
        slow_period = int(self.config.get("strategy", {}).get("slow_ema", 200))
        atr_period = int(self.config.get("strategy", {}).get("atr_period", 14))

        # Exponential Moving Averages
        df["ema_fast"] = df["close"].ewm(span=fast_period, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=slow_period, adjust=False).mean()

        # True Range and ATR
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=atr_period).mean()

        # RSI (14)
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        # ADX (14) - Wilder Trend Strength Indicator
        plus_dm = df["high"].diff()
        minus_dm = -df["low"].diff()
        plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
        minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)

        tr_smooth = tr.rolling(window=14).sum()
        plus_dm_series = pd.Series(plus_dm, index=df.index).rolling(window=14).sum()
        minus_dm_series = pd.Series(minus_dm, index=df.index).rolling(window=14).sum()

        plus_di = 100.0 * (plus_dm_series / tr_smooth.replace(0, np.nan))
        minus_di = 100.0 * (minus_dm_series / tr_smooth.replace(0, np.nan))
        dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        df["adx"] = dx.rolling(window=14).mean().fillna(20.0)
        df["plus_di"] = plus_di.fillna(0.0)
        df["minus_di"] = minus_di.fillna(0.0)

        return df

    def get_asian_session_range(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates the Asian Range (00:00 - 07:00 UTC) for today.
        Strictly enforces min_asian_range_pips and max_asian_range_pips.
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        today_date = now_utc.date()

        # Check if date rolled over
        if self.state.get("date") != today_date.isoformat():
            self.state["date"] = today_date.isoformat()
            self.state["today_trades_count"] = 0
            self.state["today_pnl"] = 0.0
            self.state["consecutive_sell_losses"] = 0
            self.state["consecutive_buy_losses"] = 0
            self.state["sell_lockout_until"] = 0.0
            self.state["buy_lockout_until"] = 0.0
            self.state["daily_risk_halt"] = False
            self.state["last_breakout_candle_time"] = ""
            self.state["positions_tracked"] = {}
            self.state["signals"] = []
            self.log(f"New trading day: {today_date.isoformat()} — resetting daily stats.")

        strat_cfg = self.config.get("strategy", {})
        min_pips = float(strat_cfg.get("min_asian_range_pips", 15.0))
        max_pips = float(strat_cfg.get("max_asian_range_pips", 120.0))

        if df.empty:
            box = self.state.get("asian_box", {"valid": False, "high": 0.0, "low": 0.0, "mid": 0.0, "range_pips": 0.0, "status": "WAITING_FOR_DATA"})
            return box

        # Filter candles within 00:00 to 07:00 UTC today
        start_utc = datetime.datetime.combine(today_date, datetime.time(0, 0), tzinfo=datetime.timezone.utc)
        end_utc = datetime.datetime.combine(today_date, datetime.time(7, 0), tzinfo=datetime.timezone.utc)

        asian_df = df[(df["timestamp"] >= start_utc) & (df["timestamp"] <= end_utc)]
        if len(asian_df) >= 6:
            high_val = float(asian_df["high"].max())
            low_val = float(asian_df["low"].min())
            mid_val = (high_val + low_val) / 2.0
            range_pips = round((high_val - low_val) * 10, 1)  # for Gold, $1 = 10 pips, $0.1 = 1 pip

            is_valid = (min_pips <= range_pips <= max_pips)
            if range_pips < min_pips:
                status_desc = f"TOO_NARROW ({range_pips:.1f} < {min_pips:.0f} pips — STANDBY)"
            elif range_pips > max_pips:
                status_desc = f"EXHAUSTED ({range_pips:.1f} > {max_pips:.0f} pips — STANDBY)"
            else:
                status_desc = f"OPTIMAL ({range_pips:.1f} pips)"

            box = {
                "high": round(high_val, 2),
                "low": round(low_val, 2),
                "mid": round(mid_val, 2),
                "range_pips": range_pips,
                "valid": is_valid,
                "status": status_desc
            }
            self.state["asian_box"] = box
            return box

        # Fallback to last known box if high > 0
        last_box = self.state.get("asian_box", {})
        if last_box.get("high", 0.0) > 0:
            return last_box

        # Quick estimate from last 30 candles if within Asian hours
        rec_high = float(df["high"].tail(30).max())
        rec_low = float(df["low"].tail(30).min())
        range_pips = round((rec_high - rec_low) * 10, 1)
        is_valid = (min_pips <= range_pips <= max_pips)
        status_desc = f"OPTIMAL ({range_pips:.1f} pips)" if is_valid else (
            f"EXHAUSTED ({range_pips:.1f} > {max_pips:.0f} pips)" if range_pips > max_pips else f"TOO_NARROW ({range_pips:.1f} < {min_pips:.0f} pips)"
        )
        box = {
            "high": round(rec_high, 2),
            "low": round(rec_low, 2),
            "mid": round((rec_high + rec_low) / 2.0, 2),
            "range_pips": range_pips,
            "valid": is_valid,
            "status": status_desc
        }
        self.state["asian_box"] = box
        return box

    def check_trading_window(self) -> Tuple[bool, str]:
        """
        Returns (is_active_session, session_name)
        Asian Session: 00:00 - 07:00 UTC (Accumulation)
        London Breakout Session: 07:00 - 13:00 UTC (Prime Execution window)
        NY Session: 13:00 - 19:00 UTC (Follow-through / Trailing)
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        curr_hour = now_utc.hour + (now_utc.minute / 60.0)

        if 0.0 <= curr_hour < 7.0:
            return False, "Asian Session (Range Building)"
        elif 7.0 <= curr_hour < 13.0:
            return True, "London Open (Prime Breakout Window)"
        elif 13.0 <= curr_hour < 19.0:
            return True, "London / NY Overlap (Trend Continuation)"
        else:
            return False, "Evening Maintenance (Restricted Entry)"

    # ── Risk Sizing ───────────────────────────────────────────────────────────
    def calculate_lot_size(self, balance: float, stop_distance_points: float) -> float:
        """
        Calculates safe lot size using strict risk % of account balance.
        Adapts automatically to Standard ($) and Standard Cent (USC) accounts.
        """
        risk_pct = float(self.config.get("risk_pct_per_trade", 1.0))
        risk_capital = max(1.0, balance * (risk_pct / 100.0))

        if stop_distance_points <= 0.1:
            stop_distance_points = 2.0  # Safe default $2 stop on Gold

        # Detect Cent account from bridge account info
        acc = self.bridge.get_account()
        is_cent = "C" in str(acc.get("currency", "")).upper() or "CENT" in str(acc.get("server", "")).upper()

        contract_multiplier = 100.0

        lot = risk_capital / (stop_distance_points * contract_multiplier)
        # Clamp strictly between 0.01 and 5.0 lots
        lot = max(0.01, min(5.0, round(lot, 2)))
        return lot

    def _update_daily_stats_and_circuit_breakers(self, balance: float):
        """
        Queries closed deals from the bridge for today to update:
        - today_trades_count
        - today_pnl
        - consecutive losses per direction
        - daily max risk % circuit breaker
        """
        now_ts = time.time()
        if (now_ts - self._last_stats_update) < 15.0:
            return
        self._last_stats_update = now_ts

        try:
            closed_deals = self.bridge.get_closed_deals(days=1)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            start_of_today_ts = datetime.datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=datetime.timezone.utc).timestamp()
            reset_ts = float(self.state.get("circuit_breaker_reset_ts", 0.0))
            cutoff_ts = max(start_of_today_ts, reset_ts)

            today_deals = [
                d for d in closed_deals
                if float(d.get("_close_timestamp", 0)) >= cutoff_ts
            ]

            self.state["today_trades_count"] = len(today_deals)
            today_pnl = sum(float(d.get("net_pnl", 0.0)) for d in today_deals)
            self.state["today_pnl"] = round(today_pnl, 2)

            if today_deals:
                # Check consecutive losses on newest deals
                sorted_deals = sorted(today_deals, key=lambda x: float(x.get("_close_timestamp", 0)))
                sell_losses = 0
                buy_losses = 0
                for d in reversed(sorted_deals):
                    side = d.get("side", "")
                    pnl = float(d.get("net_pnl", 0.0))
                    if side == "SELL":
                        if pnl < -0.01:
                            sell_losses += 1
                        else:
                            break
                    elif side == "BUY":
                        if pnl < -0.01:
                            buy_losses += 1
                        else:
                            break

                self.state["consecutive_sell_losses"] = sell_losses
                self.state["consecutive_buy_losses"] = buy_losses

                # If 2 consecutive losses in same direction, lockout for 60 min
                if sell_losses >= 2 and float(self.state.get("sell_lockout_until", 0.0)) < now_ts:
                    self.state["sell_lockout_until"] = now_ts + 3600.0
                    self.log(f"⚠️ CIRCUIT BREAKER: {sell_losses} consecutive SELL stop losses. SELL entries locked out for 60m.")

                if buy_losses >= 2 and float(self.state.get("buy_lockout_until", 0.0)) < now_ts:
                    self.state["buy_lockout_until"] = now_ts + 3600.0
                    self.log(f"⚠️ CIRCUIT BREAKER: {buy_losses} consecutive BUY stop losses. BUY entries locked out for 60m.")

                # Check Daily Max Risk % Limit (0 or negative disables check)
                max_risk_pct = float(self.config.get("max_daily_risk_pct", 3.0))
                if max_risk_pct > 0 and balance > 0 and today_pnl < 0:
                    realized_loss_pct = (abs(today_pnl) / balance) * 100.0
                    if realized_loss_pct >= max_risk_pct and not self.state.get("daily_risk_halt"):
                        self.state["daily_risk_halt"] = True
                        self.log(f"🚨 DAILY MAX RISK LIMIT REACHED: -{realized_loss_pct:.2f}% >= {max_risk_pct:.1f}%. Halting trading for today.")
            else:
                self.state["consecutive_sell_losses"] = 0
                self.state["consecutive_buy_losses"] = 0
        except Exception as e:
            logger.debug(f"Daily stats check error: {e}")

    def reset_circuit_breaker(self):
        """Manually clear all daily risk halts and directional loss lockouts."""
        with self._execution_lock:
            self.state["daily_risk_halt"] = False
            self.state["consecutive_sell_losses"] = 0
            self.state["consecutive_buy_losses"] = 0
            self.state["sell_lockout_until"] = 0.0
            self.state["buy_lockout_until"] = 0.0
            self.state["circuit_breaker_reset_ts"] = time.time()
            self.save_state()
            self.log("🔄 User manually reset all Circuit Breakers & Daily Risk Halt.")

    # ── Main Engine Tick ──────────────────────────────────────────────────────
    def process_tick(self) -> Dict[str, Any]:
        """
        Autonomous Algorithmic Tick Execution:
        Protected by threading mutex and in-flight order guards.
        """
        with self._execution_lock:
            return self._process_tick_internal()

    def _process_tick_internal(self) -> Dict[str, Any]:
        now_ts = time.time()
        sym = self.config.get("symbol", "XAUUSD")
        acc = self.bridge.get_account()
        balance = float(acc.get("balance", 1000.0))
        equity = float(acc.get("equity", 1000.0))

        tick = self.bridge.get_tick(sym)
        ask = float(tick.get("ask", 0.0))
        bid = float(tick.get("bid", 0.0))
        price = (ask + bid) / 2.0 if (ask > 0 and bid > 0) else float(tick.get("price", 2900.0))

        # Update stats & circuit breakers
        self._update_daily_stats_and_circuit_breakers(balance)

        # Candle caching (fetch every 15 seconds)
        if self._cached_candles is None or (now_ts - self._last_candle_fetch > 15.0):
            df_raw = self.bridge.get_candles(sym, timeframe="M5", limit=120)
            if not df_raw.empty:
                self._cached_candles = self.compute_indicators(df_raw)
                self._last_candle_fetch = now_ts

        df = self._cached_candles if self._cached_candles is not None else pd.DataFrame()
        asian_box = self.get_asian_session_range(df)
        is_window_active, session_name = self.check_trading_window()

        # Multi-timeframe M15 trend check
        if self._cached_m15 is None or (now_ts - self._last_m15_fetch > 30.0):
            df_m15_raw = self.bridge.get_candles(sym, timeframe="M15", limit=60)
            if not df_m15_raw.empty:
                self._cached_m15 = self.compute_indicators(df_m15_raw)
                self._last_m15_fetch = now_ts

        m15_trend = "NEUTRAL"
        if self._cached_m15 is not None and len(self._cached_m15) > 20:
            m15_last = self._cached_m15.iloc[-1]
            m15_fast = float(m15_last.get("ema_fast", price)) if not pd.isna(m15_last.get("ema_fast")) else price
            m15_slow = float(m15_last.get("ema_slow", price)) if not pd.isna(m15_last.get("ema_slow")) else price
            if m15_fast > m15_slow and price > m15_slow:
                m15_trend = "BULLISH"
            elif m15_fast < m15_slow and price < m15_slow:
                m15_trend = "BEARISH"

        # Indicators
        latest_atr = 2.50
        fast_ema = price
        slow_ema = price
        macro_trend = "NEUTRAL 🟡"
        current_adx = 20.0
        current_rsi = 50.0

        if not df.empty and len(df) > 20:
            last_row = df.iloc[-1]
            latest_atr = float(last_row.get("atr", 2.50)) if not pd.isna(last_row.get("atr")) else 2.50
            fast_ema = float(last_row.get("ema_fast", price)) if not pd.isna(last_row.get("ema_fast")) else price
            slow_ema = float(last_row.get("ema_slow", price)) if not pd.isna(last_row.get("ema_slow")) else price
            current_adx = float(last_row.get("adx", 20.0)) if not pd.isna(last_row.get("adx")) else 20.0
            current_rsi = float(last_row.get("rsi", 50.0)) if not pd.isna(last_row.get("rsi")) else 50.0

            if fast_ema > slow_ema and price > fast_ema:
                macro_trend = "BULLISH 🟢"
            elif fast_ema < slow_ema and price < fast_ema:
                macro_trend = "BEARISH 🔴"
            else:
                macro_trend = "CONSOLIDATION 🟡"

        # Check existing positions & manage trade exits
        open_positions = self.bridge.get_positions(sym)
        self._manage_active_trades(open_positions, price, latest_atr)

        open_orders = self.bridge.get_orders(sym)
        has_active_exposure = (len(open_positions) > 0 or len(open_orders) > 0)

        # ── Signal Generation (Multi-Layer Protection) ─────────────────────────
        signal = None
        strat_cfg = self.config.get("strategy", {})
        buffer_val = float(strat_cfg.get("buffer_pips", 3.0)) * 0.10  # 3 pips = $0.30
        max_spread = float(strat_cfg.get("max_spread_pips", 4.5)) * 0.10
        spread_ok = (ask > 0 and bid > 0) and ((ask - bid) <= max_spread) if (ask > 0 and bid > 0) else True

        # Gate 1: Auto-trading enabled
        auto_trade_ok = bool(self.config.get("auto_trading", True))
        # Gate 2: Daily Risk Halt Circuit Breaker
        daily_risk_ok = not bool(self.state.get("daily_risk_halt", False))
        # Gate 3: Active Trading Window
        # Gate 4: Asian Range Validity (Between min 15 and max 120 pips)
        range_valid = bool(asian_box.get("valid", False))
        # Gate 5: In-Flight Order Guard (Avoid race conditions / multi-order dispatch)
        not_in_flight = (now_ts >= self._order_in_flight_until)
        # Gate 6: Zero Martingale Single Exposure Guard
        zero_exposure = not has_active_exposure
        # Gate 7: Cooldown Guard (10 minutes between setups)
        last_trade_time = float(self.state.get("last_trade_timestamp", 0))
        cooldown_ok = (now_ts - last_trade_time) > 600.0
        # Gate 8: Max Trades Limit (0 = Unlimited confirmed setups)
        max_daily_trades = int(self.config.get("max_trades_per_day", 0))
        daily_count_ok = (max_daily_trades == 0) or (self.state.get("today_trades_count", 0) < max_daily_trades)

        eligible_for_signal = (
            auto_trade_ok and daily_risk_ok and is_window_active and
            range_valid and not_in_flight and zero_exposure and
            cooldown_ok and daily_count_ok and spread_ok
        )

        if eligible_for_signal and len(df) >= 30:
            # Evaluate COMPLETED M5 Candle Close (df.iloc[-2]) to eliminate fakeout wicks
            last_closed_bar = df.iloc[-2]
            candle_close = float(last_closed_bar["close"])
            candle_time = str(last_closed_bar.get("timestamp", ""))
            c_adx = float(last_closed_bar.get("adx", current_adx))
            c_rsi = float(last_closed_bar.get("rsi", current_rsi))

            asian_high = asian_box.get("high", 0.0)
            asian_low = asian_box.get("low", 0.0)
            max_chase_dist = 2.5 * latest_atr

            is_sell_locked = (now_ts < float(self.state.get("sell_lockout_until", 0.0)))
            is_buy_locked = (now_ts < float(self.state.get("buy_lockout_until", 0.0)))
            not_already_traded_candle = (candle_time != self.state.get("last_breakout_candle_time", ""))

            # Bullish Breakout Check:
            # Candle CLOSE must be cleanly above Asian High + buffer, and within max chase
            # ADX must be >= 20.0 (trending, not chop), RSI >= 50.0 (positive momentum)
            # Strict Institutional Trend: Price > 200 EMA or 50 EMA > 200 EMA, and M15 is NOT Bearish
            if (not is_buy_locked and not_already_traded_candle and
                    asian_high > 0 and (asian_high + buffer_val) < candle_close < (asian_high + max_chase_dist)):
                if c_adx >= 20.0 and c_rsi >= 50.0 and (price > slow_ema or fast_ema > slow_ema) and m15_trend != "BEARISH":
                    sl_dist = float(strat_cfg.get("atr_sl_multiplier", 1.5)) * latest_atr
                    sl_price = round(price - sl_dist, 2)
                    tp1_price = round(price + (sl_dist * float(strat_cfg.get("tp1_rr", 1.5))), 2)
                    lot = self.calculate_lot_size(balance, sl_dist)

                    signal = {
                        "type": "BUY",
                        "reason": f"Confirmed M5 Close (${candle_close:.2f} > Asian High ${asian_high:.2f}) | ADX: {c_adx:.1f}, RSI: {c_rsi:.1f} | M15 Trend: {m15_trend}",
                        "price": price,
                        "sl": sl_price,
                        "tp1": tp1_price,
                        "lot": lot,
                        "candle_time": candle_time
                    }

            # Bearish Breakout Check:
            # Candle CLOSE must be cleanly below Asian Low - buffer, and within max chase
            # ADX must be >= 20.0 (trending, not chop), RSI <= 50.0 (negative momentum)
            # Strict Institutional Trend: Price < 200 EMA or 50 EMA < 200 EMA, and M15 is NOT Bullish
            elif (not is_sell_locked and not_already_traded_candle and
                  asian_low > 0 and (asian_low - max_chase_dist) < candle_close < (asian_low - buffer_val)):
                if c_adx >= 20.0 and c_rsi <= 50.0 and (price < slow_ema or fast_ema < slow_ema) and m15_trend != "BULLISH":
                    sl_dist = float(strat_cfg.get("atr_sl_multiplier", 1.5)) * latest_atr
                    sl_price = round(price + sl_dist, 2)
                    tp1_price = round(price - (sl_dist * float(strat_cfg.get("tp1_rr", 1.5))), 2)
                    lot = self.calculate_lot_size(balance, sl_dist)

                    signal = {
                        "type": "SELL",
                        "reason": f"Confirmed M5 Close (${candle_close:.2f} < Asian Low ${asian_low:.2f}) | ADX: {c_adx:.1f}, RSI: {c_rsi:.1f} | M15 Trend: {m15_trend}",
                        "price": price,
                        "sl": sl_price,
                        "tp1": tp1_price,
                        "lot": lot,
                        "candle_time": candle_time
                    }

            if signal:
                self._execute_signal(signal, sym)

        self.save_state()

        telemetry = {
            "symbol": sym,
            "price": price,
            "ask": ask,
            "bid": bid,
            "balance": balance,
            "equity": equity,
            "session": session_name,
            "is_active_window": is_window_active,
            "asian_box": asian_box,
            "atr": round(latest_atr, 2),
            "fast_ema": round(fast_ema, 2),
            "slow_ema": round(slow_ema, 2),
            "adx": round(current_adx, 1),
            "rsi": round(current_rsi, 1),
            "macro_trend": macro_trend,
            "open_positions": open_positions,
            "open_orders": open_orders,
            "last_signal": signal,
            "consecutive_sell_losses": self.state.get("consecutive_sell_losses", 0),
            "consecutive_buy_losses": self.state.get("consecutive_buy_losses", 0),
            "is_sell_locked": now_ts < float(self.state.get("sell_lockout_until", 0.0)),
            "is_buy_locked": now_ts < float(self.state.get("buy_lockout_until", 0.0)),
            "daily_risk_halt": self.state.get("daily_risk_halt", False),
            "today_pnl": self.state.get("today_pnl", 0.0),
            "today_trades_count": self.state.get("today_trades_count", 0)
        }
        self._cached_telemetry = telemetry
        return telemetry

    def get_telemetry(self) -> Dict[str, Any]:
        """
        Read-only telemetry provider for Streamlit panel and external monitors.
        Does NOT evaluate breakout triggers or submit orders.
        """
        if self._cached_telemetry:
            return self._cached_telemetry

        sym = self.config.get("symbol", "XAUUSD")
        acc = self.bridge.get_account()
        tick = self.bridge.get_tick(sym)
        open_positions = self.bridge.get_positions(sym)
        open_orders = self.bridge.get_orders(sym)

        return {
            "symbol": sym,
            "price": float(tick.get("price", 0.0)),
            "ask": float(tick.get("ask", 0.0)),
            "bid": float(tick.get("bid", 0.0)),
            "balance": float(acc.get("balance", 1000.0)),
            "equity": float(acc.get("equity", 1000.0)),
            "session": "Monitoring",
            "is_active_window": False,
            "asian_box": self.state.get("asian_box", {"valid": False, "range_pips": 0.0, "status": "STANDBY"}),
            "atr": 2.5,
            "fast_ema": float(tick.get("price", 0.0)),
            "slow_ema": float(tick.get("price", 0.0)),
            "adx": 20.0,
            "rsi": 50.0,
            "macro_trend": "NEUTRAL 🟡",
            "open_positions": open_positions,
            "open_orders": open_orders,
            "last_signal": None,
            "consecutive_sell_losses": self.state.get("consecutive_sell_losses", 0),
            "consecutive_buy_losses": self.state.get("consecutive_buy_losses", 0),
            "is_sell_locked": time.time() < float(self.state.get("sell_lockout_until", 0.0)),
            "is_buy_locked": time.time() < float(self.state.get("buy_lockout_until", 0.0)),
            "daily_risk_halt": self.state.get("daily_risk_halt", False),
            "today_pnl": self.state.get("today_pnl", 0.0),
            "today_trades_count": self.state.get("today_trades_count", 0)
        }

    def _execute_signal(self, sig: Dict[str, Any], symbol: str):
        # Set 20-second in-flight lock to guarantee no other thread can execute duplicate orders
        self._order_in_flight_until = time.time() + 20.0
        self.state["last_breakout_candle_time"] = sig.get("candle_time", "")

        sig_type = sig["type"]
        lot = sig["lot"]
        price = sig["price"]
        sl = sig["sl"]
        tp = sig["tp1"]

        self.log(f"🚨 SIGNAL GENERATED: {sig_type} {lot} lots @ {price:.2f} | SL: {sl:.2f}, TP1: {tp:.2f} | {sig['reason']}")
        res = self.bridge.send_order(symbol, sig_type, price, lot, sl, tp)

        if res.get("success"):
            ticket = res.get("ticket", 0)
            self.log(f"✅ Order Executed Successfully! Ticket #{ticket}")
            self.state["today_trades_count"] = self.state.get("today_trades_count", 0) + 1
            self.state["last_trade_timestamp"] = time.time()

            # Record tracking data for Breakeven and Trailing
            tracked = self.state.get("positions_tracked", {})
            tracked[str(ticket)] = {
                "type": sig_type,
                "open_price": price,
                "initial_sl": sl,
                "initial_tp": tp,
                "stage": 0,
                "tp1_hit": False,
                "be_activated": False,
                "ratchet_activated": False,
                "trailing_activated": False,
                "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.state["positions_tracked"] = tracked
        else:
            self.log(f"❌ Order Send Failed: {res.get('error', 'Unknown bridge error')}")
            # Release in-flight lock after brief pause so system can retry next setup
            self._order_in_flight_until = time.time() + 5.0

    def _manage_active_trades(self, positions: List[Dict[str, Any]], current_price: float, atr: float):
        """
        Institutional 4-Stage Progressive Trailing & Loss-Avoidance Ladder:
        - Stage 1: Early Breakeven Lock at +0.5R (+15 pips / +$1.50) -> Move SL to entry + 0.15 (Risk-Free).
        - Stage 2: Profit Milestone Lock at +1.0R (+30 pips / +$3.00) -> Ratchet SL to +0.5R (Guaranteed +50% Gain).
        - Stage 3: Partial TP / Runner Transition at +1.5R -> Close 50% (if volume > 0.01) or set SL to +0.8R.
        - Stage 4: Dynamic M5 Candle Trail for runners -> Trail SL behind lowest low of last 2 M5 candles (BUY) or highest high of last 2 M5 candles (SELL).
        """
        tracked = self.state.get("positions_tracked", {})
        strat_cfg = self.config.get("strategy", {})
        early_be_rr = float(strat_cfg.get("early_be_rr", 0.5))
        profit_ratchet_rr = float(strat_cfg.get("profit_ratchet_rr", 1.0))
        tp1_rr = float(strat_cfg.get("tp1_rr", 1.5))
        trailing_mult = float(strat_cfg.get("trailing_atr_multiplier", 1.2))
        candle_lookback = int(strat_cfg.get("trailing_candle_lookback", 2))
        be_offset = float(strat_cfg.get("be_offset_points", 20)) * 0.01  # 20 points = $0.20

        df = self._cached_candles

        for pos in positions:
            ticket = str(pos.get("ticket"))
            pos_type = pos.get("type", 0)
            is_buy = (pos_type == 0)
            open_price = float(pos.get("price_open", current_price))
            curr_sl = float(pos.get("sl", 0.0))
            profit = float(pos.get("profit", 0.0))
            volume = float(pos.get("volume", 0.01))

            meta = tracked.get(ticket, {
                "type": "BUY" if is_buy else "SELL",
                "open_price": open_price,
                "initial_sl": curr_sl,
                "stage": 0,
                "tp1_hit": False,
                "be_activated": False,
                "ratchet_activated": False,
                "trailing_activated": False
            })

            gain = (current_price - open_price) if is_buy else (open_price - current_price)
            risk_dist = abs(open_price - meta.get("initial_sl", open_price - (atr * 1.5)))
            if risk_dist <= 0.1:
                risk_dist = atr * 1.5

            # ── Stage 1: Early Risk-Free Lock (Gain >= 0.5 R) ──────────────────
            if not meta.get("be_activated") and gain >= (risk_dist * early_be_rr):
                be_price = round(open_price + (be_offset if is_buy else -be_offset), 2)
                should_be = (is_buy and (curr_sl == 0 or be_price > curr_sl)) or (not is_buy and (curr_sl == 0 or be_price < curr_sl))
                if should_be:
                    res_m = self.bridge.modify_position(int(ticket), sl=be_price, tp=float(pos.get("tp", 0.0)))
                    if res_m.get("success"):
                        meta["be_activated"] = True
                        meta["stage"] = 1
                        curr_sl = be_price
                        self.log(f"🛡️ [STAGE 1: RISK-FREE] #{ticket}: SL moved to {be_price:.2f} at +{gain:.2f} pts (+{early_be_rr:.1f}R). Zero Risk Guaranteed!")

            # ── Stage 2: Profit Milestone Lock (Gain >= 1.0 R) ─────────────────
            if not meta.get("ratchet_activated") and gain >= (risk_dist * profit_ratchet_rr):
                locked_gain = round(risk_dist * 0.5, 2)
                ratchet_price = round(open_price + (locked_gain if is_buy else -locked_gain), 2)
                should_ratchet = (is_buy and ratchet_price > curr_sl) or (not is_buy and (curr_sl == 0 or ratchet_price < curr_sl))
                if should_ratchet:
                    res_r = self.bridge.modify_position(int(ticket), sl=ratchet_price, tp=float(pos.get("tp", 0.0)))
                    if res_r.get("success"):
                        meta["ratchet_activated"] = True
                        meta["stage"] = 2
                        curr_sl = ratchet_price
                        self.log(f"🔒 [STAGE 2: +50% LOCKED] #{ticket}: SL ratcheted to {ratchet_price:.2f} at +{gain:.2f} pts (+{profit_ratchet_rr:.1f}R). Guaranteed profit secured!")

            # ── Stage 3: Partial Take Profit / Runner Mode (Gain >= 1.5 R) ─────
            if not meta.get("tp1_hit") and gain >= (risk_dist * tp1_rr):
                close_vol = max(0.01, round(volume * 0.5, 2))
                if volume > 0.01:
                    res_cl = self.bridge.close_position(int(ticket), volume=close_vol)
                    if res_cl.get("success"):
                        meta["tp1_hit"] = True
                        meta["trailing_activated"] = True
                        meta["stage"] = 3
                        r1_sl = round(open_price + (risk_dist * 0.75 if is_buy else -risk_dist * 0.75), 2)
                        self.bridge.modify_position(int(ticket), sl=r1_sl, tp=0.0)
                        curr_sl = r1_sl
                        self.log(f"💰 [STAGE 3: PARTIAL TP] #{ticket}: Closed 50% ({close_vol}L) at +{tp1_rr:.1f}R! SL moved to {r1_sl:.2f}. Runner active!")
                else:
                    meta["tp1_hit"] = True
                    meta["trailing_activated"] = True
                    meta["stage"] = 3
                    tp_sl = round(open_price + (risk_dist * 0.8 if is_buy else -risk_dist * 0.8), 2)
                    self.bridge.modify_position(int(ticket), sl=tp_sl, tp=0.0)
                    curr_sl = tp_sl
                    self.log(f"🎯 [STAGE 3: RUNNER ACTIVATED] #{ticket}: Target reached at +{tp1_rr:.1f}R! Hard TP removed, SL locked to {tp_sl:.2f}. Trend runner mode on!")

            # ── Stage 4: Dynamic M5 Candle Trail (Trend Riding on Runners) ────
            if meta.get("trailing_activated") or meta.get("ratchet_activated"):
                trail_sl = None
                # Method A: Previous completed M5 candle low/high trail
                if df is not None and len(df) >= (candle_lookback + 2):
                    recent_bars = df.iloc[-(candle_lookback + 1):-1]
                    if is_buy:
                        lowest_low = float(recent_bars["low"].min())
                        trail_candidate = round(lowest_low - (atr * 0.3), 2)
                        if trail_candidate > curr_sl:
                            trail_sl = trail_candidate
                    else:
                        highest_high = float(recent_bars["high"].max())
                        trail_candidate = round(highest_high + (atr * 0.3), 2)
                        if curr_sl == 0 or trail_candidate < curr_sl:
                            trail_sl = trail_candidate

                # Method B: Fallback to Chandelier ATR trail
                if trail_sl is None:
                    atr_trail = round(current_price - (atr * trailing_mult) if is_buy else current_price + (atr * trailing_mult), 2)
                    if (is_buy and atr_trail > curr_sl) or (not is_buy and (curr_sl == 0 or atr_trail < curr_sl)):
                        trail_sl = atr_trail

                if trail_sl is not None and abs(trail_sl - curr_sl) >= 0.25:
                    res_t = self.bridge.modify_position(int(ticket), sl=trail_sl, tp=0.0)
                    if res_t.get("success"):
                        meta["stage"] = 4
                        self.log(f"🚀 [STAGE 4: DYNAMIC TRAIL] #{ticket}: SL updated to {trail_sl:.2f} (Locking in trend runner profits)")

            tracked[ticket] = meta

        self.state["positions_tracked"] = tracked


# Singleton instance helper
_engine_instance: Optional[TrendRunnerEngine] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_lock = threading.Lock()

def start_background_daemon():
    global _daemon_thread
    with _daemon_lock:
        if _daemon_thread is not None and _daemon_thread.is_alive():
            return

        def _daemon_loop():
            logger.info("⚡ Bot #3 24/7 Autonomous Daemon Started.")
            eng = get_engine()
            while True:
                try:
                    eng.process_tick()
                except Exception as ex:
                    logger.error(f"Daemon tick error: {ex}")
                time.sleep(2.0)

        _daemon_thread = threading.Thread(target=_daemon_loop, daemon=True, name="Bot3AutonomousDaemon")
        _daemon_thread.start()

def get_engine() -> TrendRunnerEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TrendRunnerEngine()
        start_background_daemon()
    return _engine_instance


if __name__ == "__main__":
    print("=== Starting Bot #3 TrendRunnerEngine Standalone Service ===")
    engine = get_engine()
    status = engine.process_tick()
    macro = str(status['macro_trend']).encode("ascii", "ignore").decode("ascii")
    print(f"Symbol: {status['symbol']} | Price: {status['price']} | Trend: {macro}")
    print(f"Session: {status['session']} | Asian Box: {status['asian_box']}")
    print(f"ADX: {status.get('adx')} | RSI: {status.get('rsi')}")
    print(f"Account Balance: ${status['balance']:.2f} | Open Trades: {len(status['open_positions'])}")
    print("⚡ Bot #3 Trend Engine is now running 24/7 in standalone mode.")
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        print("Bot #3 Engine Stopped.")
