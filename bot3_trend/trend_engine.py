"""
Bot #3 - Smart Martingale Trend Strategy
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

from bridge_client import Bot3BridgeClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SmartMartingaleBot3")

class TrendRunnerEngine:
    def __init__(self, config_path: Optional[str] = None):
        if not config_path:
            config_path = os.path.join(_CURRENT_DIR, "config.json")
        self.config_path = config_path
        self.state_path = os.path.join(_CURRENT_DIR, "state.json")
        self.config = self._load_config()
        self.state = self._load_state()

        self._execution_lock = threading.Lock()
        self._last_tick_time = 0.0
        self._last_candle_fetch = 0.0
        self._cached_candles: Optional[pd.DataFrame] = None
        self._cached_telemetry: Dict[str, Any] = {}

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
        return {}

    def _load_state(self) -> Dict[str, Any]:
        defaults = {
            "date": datetime.date.today().isoformat(),
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

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 30:
            return df
        df = df.copy()
        strat_cfg = self.config.get("strategy", {})
        fast_period = int(strat_cfg.get("fast_ema", 50))
        slow_period = int(strat_cfg.get("slow_ema", 200))
        atr_period = int(strat_cfg.get("atr_period", 14))

        df["ema_fast"] = df["close"].ewm(span=fast_period, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=slow_period, adjust=False).mean()

        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=atr_period).mean()

        return df

    def get_telemetry(self) -> Dict[str, Any]:
        self.state = self._load_state()
        return self.state.get("telemetry", self._cached_telemetry)

    def process_tick(self) -> Dict[str, Any]:
        with self._execution_lock:
            now = time.time()
            if now - self._last_tick_time < 1.0:
                return self._cached_telemetry
            self._last_tick_time = now

            symbol = self.config.get("symbol", "XAUUSD")
            
            try:
                acc_info = self.bridge.get_account()
                balance = float(acc_info.get("balance", 0.0))
                equity = float(acc_info.get("equity", 0.0))
                
                tick = self.bridge.get_tick(symbol)
                current_price = float(tick.get("ask", 0.0)) if tick else 0.0
                
                positions = self.bridge.get_positions(symbol)
            except Exception as e:
                logger.error(f"Bridge error: {e}")
                return self._cached_telemetry

            if current_price == 0.0:
                return self._cached_telemetry

            # Fetch candles periodically
            if now - self._last_candle_fetch > 60.0 or self._cached_candles is None:
                try:
                    strat_cfg = self.config.get("strategy", {})
                    tf = strat_cfg.get("timeframe", "M5")
                    df = self.bridge.get_candles(symbol, timeframe=tf, limit=250)
                    if not df.empty:
                        self._cached_candles = self.compute_indicators(df)
                    self._last_candle_fetch = now
                except Exception as e:
                    logger.error(f"Error fetching candles: {e}")

            df = self._cached_candles
            atr = 0.0
            trend = "NEUTRAL"
            if df is not None and not df.empty:
                last_closed = df.iloc[-2]
                atr = float(last_closed.get("atr", 0.0))
                if float(last_closed.get("ema_fast", 0.0)) > float(last_closed.get("ema_slow", 0.0)):
                    trend = "UP"
                elif float(last_closed.get("ema_fast", 0.0)) < float(last_closed.get("ema_slow", 0.0)):
                    trend = "DOWN"

            strat_cfg = self.config.get("strategy", {})
            base_lot = float(strat_cfg.get("base_lot_size", 0.01))
            grid_mult = float(strat_cfg.get("grid_multiplier", 1.3))
            max_levels = int(strat_cfg.get("max_grid_levels", 6))
            atr_mult = float(strat_cfg.get("atr_spacing_multiplier", 1.5))
            target_profit = float(strat_cfg.get("basket_take_profit_usd", 5.0))
            protect_pct = float(strat_cfg.get("account_protection_pct", 15.0))

            my_positions = [p for p in positions if str(p.get("symbol")) == symbol and int(p.get("magic")) == int(self.config.get("magic_number", 998873))]
            
            total_profit = sum(float(p.get("profit", 0.0)) for p in my_positions)
            grid_level = len(my_positions)
            
            # Circuit Breaker Protection
            if grid_level > 0 and balance > 0:
                drawdown_pct = abs(total_profit) / balance * 100.0 if total_profit < 0 else 0.0
                if drawdown_pct >= protect_pct:
                    self.log(f"🚨 CIRCUIT BREAKER TRIPPED! Drawdown {drawdown_pct:.2f}% >= {protect_pct}%. Closing all positions.")
                    for p in my_positions:
                        self.bridge.close_position(int(p["ticket"]), volume=float(p["volume"]))
                    return self._cached_telemetry

            # Basket Take Profit
            if grid_level > 0 and total_profit >= target_profit:
                self.log(f"✅ BASKET PROFIT HIT! Total Profit: ${total_profit:.2f}. Closing {grid_level} trades.")
                for p in my_positions:
                    self.bridge.close_position(int(p["ticket"]), volume=float(p["volume"]))
                return self._cached_telemetry

            # Grid Logic
            auto_trade = self.config.get("auto_trading", True)
            if auto_trade:
                if grid_level == 0:
                    # First trade entry
                    if trend == "UP":
                        self.log(f"📈 Trend is UP. Opening initial BUY {base_lot} lots.")
                        self.bridge.send_order(symbol, "BUY", current_price, base_lot)
                    elif trend == "DOWN":
                        self.log(f"📉 Trend is DOWN. Opening initial SELL {base_lot} lots.")
                        self.bridge.send_order(symbol, "SELL", current_price, base_lot)
                elif grid_level > 0 and grid_level < max_levels:
                    # Martingale spacing
                    is_buy = my_positions[0].get("type", 0) == 0
                    last_pos = sorted(my_positions, key=lambda x: x.get("time_setup", 0), reverse=True)[0]
                    last_price = float(last_pos.get("price_open", current_price))
                    
                    spacing = atr * atr_mult if atr > 0 else 20.0
                    
                    should_add = False
                    if is_buy and current_price < (last_price - spacing):
                        should_add = True
                    elif not is_buy and current_price > (last_price + spacing):
                        should_add = True
                        
                    if should_add:
                        next_lot = round(base_lot * (grid_mult ** grid_level), 2)
                        side = "BUY" if is_buy else "SELL"
                        self.log(f"🔄 Grid Level {grid_level+1}: Price moved {spacing:.2f} pts against us. Adding {side} {next_lot} lots.")
                        self.bridge.send_order(symbol, side, current_price, next_lot)

            self._cached_telemetry = {
                "symbol": symbol,
                "price": current_price,
                "balance": balance,
                "equity": equity,
                "trend": trend,
                "grid_level": grid_level,
                "total_profit": total_profit,
                "atr": atr,
                "auto_trading": auto_trade,
                "target_profit": target_profit,
                "protect_pct": protect_pct,
                "drawdown_pct": abs(total_profit) / balance * 100.0 if total_profit < 0 and balance > 0 else 0.0
            }
            self.state["telemetry"] = self._cached_telemetry
            self.save_state()
            return self._cached_telemetry

_engine_instance = None
_daemon_thread = None
_daemon_lock = threading.Lock()

def start_background_daemon():
    global _daemon_thread
    with _daemon_lock:
        if _daemon_thread is not None and _daemon_thread.is_alive():
            return
        def _daemon_loop():
            logger.info("⚡ Bot #3 Smart Martingale Daemon Started.")
            eng = get_engine(start_daemon=False)
            while True:
                try:
                    eng.process_tick()
                except Exception as ex:
                    logger.error(f"Daemon tick error: {ex}")
                time.sleep(2.0)
        _daemon_thread = threading.Thread(target=_daemon_loop, daemon=True, name="Bot3Martingale")
        _daemon_thread.start()

def get_engine(start_daemon: bool = False) -> TrendRunnerEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TrendRunnerEngine()
    if start_daemon:
        start_background_daemon()
    return _engine_instance

if __name__ == "__main__":
    print("=== Starting Bot #3 Smart Martingale Engine ===")
    engine = get_engine(start_daemon=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Stopped.")
