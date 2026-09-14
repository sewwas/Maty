"""
Bot #5 Dedicated Bridge Client — AI/ML Neural Trader
Communicates with MT5 Bridge on port 8005 (or configurable port)
Provides seamless multi-feed price streaming, position tracking, and AI order execution.
"""

import time
import json
import logging
import datetime
from typing import Dict, List, Optional, Any
import requests
import pandas as pd

logger = logging.getLogger("Bot5BridgeClient")


class Bot5BridgeClient:
    def __init__(self, bridge_url: str = "http://127.0.0.1:8005", magic_number: int = 998875, timeout: float = 3.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.magic_number = magic_number
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False  # Avoid proxy intercepting localhost calls
        self._last_known_tick: Dict[str, Any] = {}
        self._last_account_info: Dict[str, Any] = {}
        self._recent_dispatches: Dict[str, float] = {}

    def is_healthy(self) -> bool:
        try:
            r = self.session.get(f"{self.bridge_url}/health", timeout=2.5)
            return r.status_code == 200
        except Exception:
            try:
                acc = self.get_account()
                return bool(acc and acc.get("connected"))
            except Exception:
                return False

    def get_account(self) -> Dict[str, Any]:
        try:
            r = self.session.get(f"{self.bridge_url}/account", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                self._last_account_info = data
                return data
        except Exception as e:
            logger.debug(f"Error fetching account from bridge: {e}")

        # Fallback cache
        if self._last_account_info:
            return self._last_account_info
        return {
            "connected": False,
            "login": 0,
            "server": "Offline / Waiting for Bridge",
            "balance": 1000.0,
            "equity": 1000.0,
            "currency": "USD"
        }

    def get_tick(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        try:
            r = self.session.get(f"{self.bridge_url}/tick?symbol={symbol}", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                if "ask" in data and "bid" in data and data["ask"] > 0:
                    self._last_known_tick = data
                    return data
        except Exception as e:
            logger.debug(f"Error fetching tick from bridge: {e}")

        # Fallback to public live price (Binance for PAXGUSDT)
        try:
            r_pub = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=1.5)
            if r_pub.status_code == 200:
                p = float(r_pub.json().get("price", 0.0))
                if p > 0:
                    return {"symbol": symbol, "ask": round(p + 0.25, 2), "bid": round(p - 0.25, 2), "price": round(p, 2), "source": "binance_fallback"}
        except Exception:
            pass

        if self._last_known_tick:
            return self._last_known_tick
        return {"symbol": symbol, "ask": 2900.0, "bid": 2899.5, "price": 2899.75, "source": "default"}

    def get_candles(self, symbol: str = "XAUUSD", timeframe: str = "5m", limit: int = 200) -> pd.DataFrame:
        """
        Fetches historical candles for AI feature extraction, market regime detection, and indicators.
        Primary: Binance / Coinbase PAXGUSDT for Gold; fallback to bridge rates if available.
        """
        binance_tf_map = {
            "M1": "1m", "1m": "1m",
            "M5": "5m", "5m": "5m",
            "M15": "15m", "15m": "15m",
            "M30": "30m", "30m": "30m",
            "H1": "1h", "1h": "1h",
            "H4": "4h", "4h": "4h",
            "D1": "1d", "1d": "1d"
        }
        b_tf = binance_tf_map.get(timeframe, "5m")

        # 1. First try Binance for high-speed, accurate PAXGUSDT (Gold proxy)
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval={b_tf}&limit={limit}"
            resp = requests.get(url, timeout=2.5)
            if resp.status_code == 200:
                raw = resp.json()
                if raw and len(raw) > 10:
                    records = []
                    for k in raw:
                        records.append({
                            "time": pd.to_datetime(k[0], unit="ms", utc=True),
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5])
                        })
                    df = pd.DataFrame(records)
                    df.set_index("time", inplace=True)
                    return df
        except Exception as e:
            logger.debug(f"Binance candle fetch failed: {e}")

        # 2. Try MT5 Bridge endpoint
        try:
            url = f"{self.bridge_url}/rates?symbol={symbol}&timeframe={timeframe}&count={limit}"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                if "rates" in data and data["rates"]:
                    df = pd.DataFrame(data["rates"])
                    if "time" in df.columns:
                        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                        df.set_index("time", inplace=True)
                    return df
        except Exception as e:
            logger.debug(f"Bridge rates fetch failed: {e}")

        # 3. Synthetic fallback candles around current price to ensure engine never halts
        tick = self.get_tick(symbol)
        curr_price = tick.get("price", 2900.0)
        times = pd.date_range(end=pd.Timestamp.now(datetime.timezone.utc), periods=limit, freq=b_tf)
        synthetic_df = pd.DataFrame({
            "open": curr_price,
            "high": curr_price + 0.5,
            "low": curr_price - 0.5,
            "close": curr_price,
            "volume": 100.0
        }, index=times)
        return synthetic_df

    def get_positions(self, symbol: str = "XAUUSD") -> List[Dict[str, Any]]:
        """
        Retrieves all active positions filtered by Bot 5's magic number.
        """
        try:
            r = self.session.get(f"{self.bridge_url}/positions", timeout=self.timeout)
            if r.status_code == 200:
                raw_positions = r.json().get("positions", [])
                bot_positions = []
                for p in raw_positions:
                    pos_magic = p.get("magic", 0)
                    pos_sym = p.get("symbol", "").upper()
                    if pos_magic == self.magic_number and ("XAU" in pos_sym or "GOLD" in pos_sym or pos_sym == symbol):
                        bot_positions.append(p)
                return bot_positions
        except Exception as e:
            logger.debug(f"Error fetching positions: {e}")
        return []

    def get_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieves trade history filtered by Bot 5's magic number.
        """
        try:
            r = self.session.get(f"{self.bridge_url}/history?days={days}", timeout=self.timeout)
            if r.status_code == 200:
                raw_history = r.json().get("deals", [])
                return [d for d in raw_history if d.get("magic", 0) == self.magic_number]
        except Exception as e:
            logger.debug(f"Error fetching history: {e}")
        return []

    def open_trade(
        self,
        symbol: str,
        action: str,  # 'BUY' or 'SELL'
        volume: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        comment: str = "Bot5_AI"
    ) -> Dict[str, Any]:
        """
        Executes a live market order via the MT5 bridge with Bot 5 magic number using GET /order_send.
        """
        params = {
            "symbol": symbol,
            "type": action.upper(),
            "price": 0.0,
            "volume": round(float(volume), 2),
            "sl": round(float(stop_loss), 2) if stop_loss > 0 else 0.0,
            "tp": round(float(take_profit), 2) if take_profit > 0 else 0.0,
            "magic": self.magic_number
        }
        try:
            r = self.session.get(f"{self.bridge_url}/order_send", params=params, timeout=self.timeout)
            if r.status_code == 200:
                res = r.json()
                if res.get("success", False) or res.get("ticket"):
                    logger.info(f"🚀 Bot #5 Order Executed: {action} {volume} {symbol} @ SL={stop_loss}, TP={take_profit} | Ticket: {res.get('ticket')}")
                else:
                    logger.error(f"❌ Bot #5 Order Failed: {res.get('error')}")
                return res
            logger.error(f"❌ Order failed with HTTP {r.status_code}: {r.text}")
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Exception sending order to bridge: {e}")
            return {"success": False, "error": str(e)}

    def modify_position(self, ticket: int, sl: float = 0.0, tp: float = 0.0) -> bool:
        """
        Modifies Stop Loss and Take Profit of an existing position using GET /modify_sl_tp.
        """
        params = {
            "ticket": int(ticket),
            "sl": round(float(sl), 2),
            "tp": round(float(tp), 2)
        }
        try:
            r = self.session.get(f"{self.bridge_url}/modify_sl_tp", params=params, timeout=self.timeout)
            return r.status_code == 200 and r.json().get("success", False)
        except Exception as e:
            logger.debug(f"Error modifying position #{ticket}: {e}")
            return False

    def close_position(self, ticket: int) -> bool:
        """
        Closes an open position by ticket using GET /position_close.
        """
        params = {"ticket": int(ticket)}
        try:
            r = self.session.get(f"{self.bridge_url}/position_close", params=params, timeout=self.timeout)
            return r.status_code == 200 and r.json().get("success", False)
        except Exception as e:
            logger.error(f"Error closing position #{ticket}: {e}")
            return False

    def close_all_positions(self, symbol: str = "XAUUSD") -> int:
        """
        Emergency kill-switch: Closes all active positions belonging to Bot 5 using GET /close_all.
        """
        try:
            r = self.session.get(f"{self.bridge_url}/close_all?symbol={symbol}&magic={self.magic_number}", timeout=self.timeout)
            if r.status_code == 200:
                res = r.json()
                return int(res.get("closed_count", 0))
        except Exception as e:
            logger.error(f"Error in close_all_positions: {e}")
        return 0
