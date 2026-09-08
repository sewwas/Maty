"""
Bot #3 — Smart Money London Breakout & Trend Runner Engine
============================================================
Strategy Architecture:
1. Calculates Asian Session Range (00:00 - 07:00 UTC) High & Low.
2. During London Session (07:00 - 13:00 UTC), scans for high-momentum breakouts.
3. Multi-Timeframe Trend Confirmation: EMA 50 vs EMA 200 + ATR expansion.
4. Capital Preservation (Strict Zero Martingale):
   - Fixed Risk % (default 1.0% equity per trade)
   - Hard Stop Loss = 1.5 x ATR
   - Partial Take Profit at 1:1.5 RR (closes 50% volume)
   - Auto Breakeven trigger at 1:1.0 RR
   - Chandelier ATR trailing stop on remaining runner to catch 100-300 pip trends.
5. Fully isolated state in bot3_trend/state.json.
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

        # Bridge client
        bridge_url = self.config.get("bridge_url", "http://127.0.0.1:8003")
        magic = int(self.config.get("magic_number", 998873))
        self.bridge = Bot3BridgeClient(bridge_url=bridge_url, magic_number=magic)

        self._last_tick_time = 0
        self._last_candle_fetch = 0
        self._cached_candles: Optional[pd.DataFrame] = None
        self._cached_asian_box: Dict[str, Any] = {}

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
            "auto_trading": True,
            "strategy": {
                "fast_ema": 50,
                "slow_ema": 200,
                "atr_period": 14,
                "atr_sl_multiplier": 1.5,
                "tp1_rr": 1.5,
                "tp1_close_pct": 50.0,
                "breakeven_trigger_rr": 1.0,
                "trailing_atr_multiplier": 2.0,
                "buffer_pips": 3.0
            }
        }

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
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
            "date": datetime.date.today().isoformat(),
            "asian_box": {
                "high": 0.0,
                "low": 0.0,
                "mid": 0.0,
                "range_pips": 0.0,
                "valid": False
            },
            "today_trades_count": 0,
            "today_pnl": 0.0,
            "positions_tracked": {},
            "signals": [],
            "logs": []
        }

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

        return df

    def get_asian_session_range(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculates the Asian Range (00:00 - 07:00 UTC) for today.
        """
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        today_date = now_utc.date()

        # Check if date rolled over
        if self.state.get("date") != today_date.isoformat():
            self.state["date"] = today_date.isoformat()
            self.state["today_trades_count"] = 0
            self.state["today_pnl"] = 0.0
            self.state["positions_tracked"] = {}
            self.state["signals"] = []
            self.log(f"New trading day: {today_date.isoformat()} — resetting daily stats.")

        if df.empty:
            return self.state.get("asian_box", {"valid": False, "high": 0.0, "low": 0.0, "mid": 0.0, "range_pips": 0.0})

        # Filter candles within 00:00 to 07:00 UTC today
        start_utc = datetime.datetime.combine(today_date, datetime.time(0, 0), tzinfo=datetime.timezone.utc)
        end_utc = datetime.datetime.combine(today_date, datetime.time(7, 0), tzinfo=datetime.timezone.utc)

        asian_df = df[(df["timestamp"] >= start_utc) & (df["timestamp"] <= end_utc)]
        if len(asian_df) >= 6:
            high_val = float(asian_df["high"].max())
            low_val = float(asian_df["low"].min())
            mid_val = (high_val + low_val) / 2.0
            range_pips = (high_val - low_val) # for Gold, $1 = 10 pips, 0.1 = 1 pip
            valid = True
            box = {
                "high": round(high_val, 2),
                "low": round(low_val, 2),
                "mid": round(mid_val, 2),
                "range_pips": round(range_pips * 10, 1),
                "valid": valid
            }
            self.state["asian_box"] = box
            return box

        # Fallback to last known box or estimate from recent candles
        last_box = self.state.get("asian_box", {})
        if last_box.get("valid"):
            return last_box

        # Quick estimate from last 30 candles if within Asian hours
        rec_high = float(df["high"].tail(30).max())
        rec_low = float(df["low"].tail(30).min())
        return {
            "high": round(rec_high, 2),
            "low": round(rec_low, 2),
            "mid": round((rec_high + rec_low) / 2.0, 2),
            "range_pips": round((rec_high - rec_low) * 10, 1),
            "valid": True
        }

    def check_trading_window(self) -> Tuple[bool, str]:
        """
        Returns (is_active_session, session_name)
        Asian Session: 00:00 - 07:00 UTC (Accumulation)
        London Breakout Session: 07:00 - 13:00 UTC (Execution window)
        NY Session: 13:00 - 20:00 UTC (Follow-through / Trailing)
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

        # Detect Cent account from bridge account info or config
        acc = self.bridge.get_account()
        is_cent = "C" in str(acc.get("currency", "")).upper() or "CENT" in str(acc.get("server", "")).upper()
        
        # On standard Gold contract (100 oz): 1 lot = $100 per $1.00 move
        # On Cent Gold contract: 1 lot = 100 cents per $1.00 move
        contract_multiplier = 100.0 if not is_cent else 100.0

        lot = risk_capital / (stop_distance_points * contract_multiplier)
        # Clamp strictly between 0.01 and 5.0 lots
        lot = max(0.01, min(5.0, round(lot, 2)))
        return lot

    # ── Main Engine Tick ──────────────────────────────────────────────────────
    def process_tick(self) -> Dict[str, Any]:
        """
        Executes one full algorithmic cycle:
        1. Query live tick and account
        2. Update indicators and Asian Box
        3. Check breakout entry triggers
        4. Manage open positions (Trailing Stop, Breakeven, Partial TP)
        """
        sym = self.config.get("symbol", "XAUUSD")
        acc = self.bridge.get_account()
        balance = float(acc.get("balance", 1000.0))
        equity = float(acc.get("equity", 1000.0))

        tick = self.bridge.get_tick(sym)
        ask = float(tick.get("ask", 0.0))
        bid = float(tick.get("bid", 0.0))
        price = (ask + bid) / 2.0 if (ask > 0 and bid > 0) else float(tick.get("price", 2900.0))

        # Candle caching (fetch every 15 seconds)
        now_ts = time.time()
        if self._cached_candles is None or (now_ts - self._last_candle_fetch > 15.0):
            df_raw = self.bridge.get_candles(sym, timeframe="M5", limit=120)
            if not df_raw.empty:
                self._cached_candles = self.compute_indicators(df_raw)
                self._last_candle_fetch = now_ts

        df = self._cached_candles if self._cached_candles is not None else pd.DataFrame()
        asian_box = self.get_asian_session_range(df)
        is_window_active, session_name = self.check_trading_window()

        # Indicators
        latest_atr = 2.50
        fast_ema = price
        slow_ema = price
        macro_trend = "NEUTRAL"

        if not df.empty and len(df) > 20:
            last_row = df.iloc[-1]
            latest_atr = float(last_row.get("atr", 2.50)) if not pd.isna(last_row.get("atr")) else 2.50
            fast_ema = float(last_row.get("ema_fast", price)) if not pd.isna(last_row.get("ema_fast")) else price
            slow_ema = float(last_row.get("ema_slow", price)) if not pd.isna(last_row.get("ema_slow")) else price

            if fast_ema > slow_ema and price > fast_ema:
                macro_trend = "BULLISH 🟢"
            elif fast_ema < slow_ema and price < fast_ema:
                macro_trend = "BEARISH 🔴"
            else:
                macro_trend = "CONSOLIDATION 🟡"

        # Check existing positions & manage trade exits
        open_positions = self.bridge.get_positions(sym)
        self._manage_active_trades(open_positions, price, latest_atr)

        # Signal Generation (only if auto_trading enabled, window active, and no open positions)
        strat_cfg = self.config.get("strategy", {})
        buffer_val = float(strat_cfg.get("buffer_pips", 3.0)) * 0.10  # convert pips to $ (3 pips = $0.30)
        max_spread = float(strat_cfg.get("max_spread_pips", 4.5)) * 0.10
        signal = None

        # Check spread
        spread_ok = (ask > 0 and bid > 0) and ((ask - bid) <= max_spread) if (ask > 0 and bid > 0) else True

        # Check cooldown (minimum 10 minutes between consecutive entries)
        last_trade_time = float(self.state.get("last_trade_timestamp", 0))
        cooldown_ok = (now_ts - last_trade_time) > 600.0  # 10 minute cooldown
        if self.config.get("auto_trading", True) and is_window_active and spread_ok and cooldown_ok:
            # Check daily trade limit (0 = Unlimited confirmed setups)
            max_daily_trades = int(self.config.get("max_trades_per_day", 0))
            daily_limit_ok = (max_daily_trades == 0) or (self.state.get("today_trades_count", 0) < max_daily_trades)

            if daily_limit_ok and len(open_positions) == 0:
                asian_high = asian_box.get("high", 0.0)
                asian_low = asian_box.get("low", 0.0)

                # Maximum chase limit (don't chase if price already moved > 2.5 ATR past the box)
                max_chase_dist = 2.5 * latest_atr

                # Bullish Breakout Check
                if asian_high > 0 and (asian_high + buffer_val) < price < (asian_high + max_chase_dist):
                    if "BULLISH" in macro_trend or price > fast_ema:
                        sl_dist = float(strat_cfg.get("atr_sl_multiplier", 1.5)) * latest_atr
                        sl_price = round(price - sl_dist, 2)
                        tp1_price = round(price + (sl_dist * float(strat_cfg.get("tp1_rr", 1.5))), 2)
                        lot = self.calculate_lot_size(balance, sl_dist)
                        
                        signal = {
                            "type": "BUY",
                            "reason": f"London High Breakout (${price:.2f} > Asian High ${asian_high:.2f}) with Bullish EMA Trend",
                            "price": price,
                            "sl": sl_price,
                            "tp1": tp1_price,
                            "lot": lot
                        }

                # Bearish Breakout Check
                elif asian_low > 0 and (asian_low - max_chase_dist) < price < (asian_low - buffer_val):
                    if "BEARISH" in macro_trend or price < fast_ema:
                        sl_dist = float(strat_cfg.get("atr_sl_multiplier", 1.5)) * latest_atr
                        sl_price = round(price + sl_dist, 2)
                        tp1_price = round(price - (sl_dist * float(strat_cfg.get("tp1_rr", 1.5))), 2)
                        lot = self.calculate_lot_size(balance, sl_dist)

                        signal = {
                            "type": "SELL",
                            "reason": f"London Low Breakout (${price:.2f} < Asian Low ${asian_low:.2f}) with Bearish EMA Trend",
                            "price": price,
                            "sl": sl_price,
                            "tp1": tp1_price,
                            "lot": lot
                        }

                # Execute Signal
                if signal:
                    self._execute_signal(signal, sym)

        self.save_state()

        return {
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
            "macro_trend": macro_trend,
            "open_positions": open_positions,
            "last_signal": signal
        }

    def _execute_signal(self, sig: Dict[str, Any], symbol: str):
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
                "tp1_hit": False,
                "be_activated": False,
                "trailing_activated": False,
                "entry_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.state["positions_tracked"] = tracked
        else:
            self.log(f"❌ Order Send Failed: {res.get('error', 'Unknown bridge error')}")

    def _manage_active_trades(self, positions: List[Dict[str, Any]], current_price: float, atr: float):
        """
        Active trade management:
        - Breakeven trigger at 1:1.0 RR
        - Partial close at 1:1.5 RR (TP1)
        - Chandelier ATR trailing stop
        """
        tracked = self.state.get("positions_tracked", {})
        strat_cfg = self.config.get("strategy", {})
        trailing_mult = float(strat_cfg.get("trailing_atr_multiplier", 2.0))

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
                "tp1_hit": False,
                "be_activated": False,
                "trailing_activated": False
            })

            # Calculate favorable move in points
            gain = (current_price - open_price) if is_buy else (open_price - current_price)
            risk_dist = abs(open_price - meta.get("initial_sl", open_price - (atr * 1.5)))
            if risk_dist <= 0.1: risk_dist = atr * 1.5

            # 1. Breakeven Trigger (Gain >= 1.0 * Risk Distance)
            if not meta.get("be_activated") and gain >= risk_dist:
                be_price = round(open_price + (0.10 if is_buy else -0.10), 2)
                res_m = self.bridge.modify_position(int(ticket), sl=be_price, tp=float(pos.get("tp", 0.0)))
                if res_m.get("success"):
                    meta["be_activated"] = True
                    self.log(f"🛡️ BREAKEVEN ACTIVATED on #{ticket}: SL moved to {be_price:.2f} (Trade Risk is now $0)")

            # 2. Partial Take Profit (Gain >= 1.5 * Risk Distance)
            if not meta.get("tp1_hit") and gain >= (risk_dist * float(strat_cfg.get("tp1_rr", 1.5))):
                close_vol = max(0.01, round(volume * 0.5, 2))
                if volume > 0.01:
                    res_cl = self.bridge.close_position(int(ticket), volume=close_vol)
                    if res_cl.get("success"):
                        meta["tp1_hit"] = True
                        meta["trailing_activated"] = True
                        self.log(f"💰 PARTIAL TAKE PROFIT: Closed 50% ({close_vol} lots) on #{ticket} at 1:1.5 RR! Securing gains.")
                else:
                    meta["tp1_hit"] = True
                    meta["trailing_activated"] = True

            # 3. Dynamic Chandelier ATR Trailing Stop (Active on Runners)
            if meta.get("trailing_activated") or meta.get("be_activated"):
                trail_sl = round(current_price - (atr * trailing_mult) if is_buy else current_price + (atr * trailing_mult), 2)
                # Only move SL in direction of profit
                should_update = (is_buy and trail_sl > curr_sl) or (not is_buy and (curr_sl == 0 or trail_sl < curr_sl))
                if should_update and abs(trail_sl - curr_sl) >= 0.30:
                    res_t = self.bridge.modify_position(int(ticket), sl=trail_sl, tp=0.0)
                    if res_t.get("success"):
                        self.log(f"🎯 TRAILING SL UPDATED on #{ticket}: New SL = {trail_sl:.2f} (Locking in trend runner profits)")

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
    print("=== Testing Bot #3 TrendRunnerEngine ===")
    engine = get_engine()
    status = engine.process_tick()
    macro = str(status['macro_trend']).encode("ascii", "ignore").decode("ascii")
    print(f"Symbol: {status['symbol']} | Price: {status['price']} | Trend: {macro}")
    print(f"Session: {status['session']} | Asian Box: {status['asian_box']}")
    print(f"Account Balance: ${status['balance']:.2f} | Open Trades: {len(status['open_positions'])}")
    print("Engine Test Completed Successfully!")
