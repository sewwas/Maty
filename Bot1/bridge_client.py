"""
Bot #1 Dedicated Bridge Client — Sunrise Ogle Trading System
Communicates with MT5 Bridge on port 8001 (or configurable port)
Provides live price streaming, candle feeds, position tracking, and order execution.
"""

import time
import json
import logging
import datetime
from typing import Dict, List, Optional, Any
import requests
import pandas as pd

logger = logging.getLogger("Bot1BridgeClient")


class Bot1BridgeClient:
    def __init__(self, bridge_url: str = "http://127.0.0.1:8001", magic_number: int = 101001, timeout: float = 3.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.magic_number = magic_number
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False  # Avoid proxy issues on localhost
        self._last_known_tick: Dict[str, Any] = {}
        self._last_account_info: Dict[str, Any] = {}
        self._resolved_symbol: Optional[str] = None

    def is_healthy(self) -> bool:
        try:
            r = self.session.get(f"{self.bridge_url}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
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

        if self._last_account_info:
            return self._last_account_info
        return {
            "connected": False,
            "login": 0,
            "server": "Offline / Waiting for Bridge 8001",
            "balance": 0.0,
            "equity": 0.0,
            "currency": "USD"
        }

    def get_tick(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        targets = [self._resolved_symbol, symbol, f"{symbol}c", f"{symbol}m"] if self._resolved_symbol else [symbol, f"{symbol}c", f"{symbol}m"]
        targets = [s for s in targets if s]
        
        for sym in targets:
            try:
                r = self.session.get(f"{self.bridge_url}/tick?symbol={sym}", timeout=self.timeout)
                if r.status_code == 200:
                    data = r.json()
                    if "ask" in data and "bid" in data and data["ask"] > 0:
                        self._resolved_symbol = data.get("symbol", sym)
                        self._last_known_tick = data
                        return data
            except Exception as e:
                logger.debug(f"Error fetching tick for {sym}: {e}")

        # Fallback to public live price (Binance for Gold PAXGUSDT)
        try:
            r_pub = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=1.5)
            if r_pub.status_code == 200:
                p = float(r_pub.json().get("price", 0.0))
                if p > 0:
                    return {
                        "symbol": symbol,
                        "ask": round(p + 0.25, 2),
                        "bid": round(p - 0.25, 2),
                        "price": round(p, 2),
                        "source": "binance_fallback"
                    }
        except Exception:
            pass

        if self._last_known_tick:
            return self._last_known_tick
        return {"symbol": symbol, "ask": 2900.0, "bid": 2899.5, "price": 2899.75, "source": "default"}

    def get_candles(self, symbol: str = "XAUUSD", timeframe: str = "5m", limit: int = 150) -> pd.DataFrame:
        """
        Fetches historical candles for Sunrise Ogle multi-EMA, ATR, and breakout calculations.
        Tries MT5 Bridge rates first, falls back to Binance public feed.
        """
        target_sym = self._resolved_symbol or symbol
        try:
            r = self.session.get(f"{self.bridge_url}/rates?symbol={target_sym}&timeframe={timeframe}&count={limit}", timeout=self.timeout)
            if r.status_code == 200:
                raw = r.json()
                if isinstance(raw, list) and len(raw) > 10:
                    rows = []
                    for item in raw:
                        rows.append({
                            "timestamp": pd.to_datetime(item.get("time", time.time()), unit="s", utc=True),
                            "open": float(item.get("open", 0.0)),
                            "high": float(item.get("high", 0.0)),
                            "low": float(item.get("low", 0.0)),
                            "close": float(item.get("close", 0.0)),
                            "volume": float(item.get("tick_volume", item.get("volume", 0.0)))
                        })
                    df = pd.DataFrame(rows)
                    if not df.empty and df["close"].iloc[-1] > 0:
                        return df
        except Exception as e:
            logger.debug(f"Bridge rates endpoint unavailable: {e}")

        # 2. Fallback to Binance public klines
        binance_tf_map = {
            "M1": "1m", "1m": "1m",
            "M5": "5m", "5m": "5m",
            "M15": "15m", "15m": "15m",
            "M30": "30m", "30m": "30m",
            "H1": "1h", "1h": "1h",
            "H4": "4h", "4h": "4h",
            "D1": "1d", "1d": "1d"
        }
        b_interval = binance_tf_map.get(timeframe.upper(), "5m")
        pair = "PAXGUSDT" if any(x in symbol.upper() for x in ["XAU", "GOLD", "PAXG"]) else symbol.upper()

        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={b_interval}&limit={limit}"
            r = requests.get(url, timeout=2.5)
            if r.status_code == 200:
                raw = r.json()
                rows = []
                for item in raw:
                    rows.append({
                        "timestamp": pd.to_datetime(float(item[0]) / 1000.0, unit="s", utc=True),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5])
                    })
                df = pd.DataFrame(rows)
                if not df.empty:
                    return df
        except Exception as e:
            logger.debug(f"Binance fallback rates error: {e}")

        # Synthetic fallback if all APIs unreachable
        now = datetime.datetime.now(datetime.timezone.utc)
        base_p = 2900.0
        rows = []
        for i in range(limit, 0, -1):
            t = now - datetime.timedelta(minutes=5 * i)
            rows.append({
                "timestamp": t,
                "open": base_p,
                "high": base_p + 1.0,
                "low": base_p - 1.0,
                "close": base_p + 0.2,
                "volume": 100.0
            })
        return pd.DataFrame(rows)

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch all open positions for Bot 1 matching magic number or all if not filtered."""
        try:
            r = self.session.get(f"{self.bridge_url}/positions", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    bot_positions = [
                        p for p in data 
                        if p.get("magic") == self.magic_number or p.get("magic") == 0 or "Sunrise" in str(p.get("comment", ""))
                    ]
                    return bot_positions if bot_positions else data
        except Exception as e:
            logger.debug(f"Error fetching positions from bridge: {e}")
        return []

    def send_order(
        self,
        action: str,
        symbol: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "Sunrise Bot 1"
    ) -> Dict[str, Any]:
        """Dispatch market order to Wine MT5 terminal 1."""
        target_sym = self._resolved_symbol or symbol
        payload = {
            "action": action.upper(),
            "symbol": target_sym,
            "volume": round(float(volume), 2),
            "magic": self.magic_number,
            "comment": comment
        }
        if sl is not None and sl > 0:
            payload["sl"] = round(float(sl), 3)
        if tp is not None and tp > 0:
            payload["tp"] = round(float(tp), 3)

        try:
            r = self.session.post(f"{self.bridge_url}/order_send", json=payload, timeout=5.0)
            if r.status_code == 200:
                res = r.json()
                logger.info(f"✅ Order dispatch result: {res}")
                return res
            else:
                logger.error(f"❌ Order dispatch failed HTTP {r.status_code}: {r.text}")
                return {"success": False, "error": r.text}
        except Exception as e:
            logger.error(f"❌ Order dispatch exception: {e}")
            return {"success": False, "error": str(e)}

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """Close an open position by ticket number."""
        try:
            payload = {"ticket": int(ticket)}
            r = self.session.post(f"{self.bridge_url}/close_position", json=payload, timeout=4.0)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.error(f"Error closing position {ticket}: {e}")
        return {"success": False, "error": "Close failed"}

    def modify_position(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """Modify SL and TP of an open position."""
        try:
            payload = {"ticket": int(ticket)}
            if sl is not None:
                payload["sl"] = round(float(sl), 3)
            if tp is not None:
                payload["tp"] = round(float(tp), 3)
            r = self.session.post(f"{self.bridge_url}/modify_position", json=payload, timeout=4.0)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.error(f"Error modifying position {ticket}: {e}")
        return {"success": False, "error": "Modify failed"}
