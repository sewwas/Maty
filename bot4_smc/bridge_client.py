"""
Bot #4 Dedicated Bridge Client — SMC Liquidity Hunter
Communicates with MT5 Bridge on port 8004 (or configurable port)
Provides seamless multi-feed price streaming, position tracking, and order management.
"""

import time
import json
import logging
import datetime
from typing import Dict, List, Optional, Any
import requests
import pandas as pd

logger = logging.getLogger("Bot4BridgeClient")


class Bot4BridgeClient:
    def __init__(self, bridge_url: str = "http://127.0.0.1:8004", magic_number: int = 998874, timeout: float = 3.0):
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

    def get_candles(self, symbol: str = "XAUUSD", timeframe: str = "5m", limit: int = 150) -> pd.DataFrame:
        """
        Fetches historical candles for SMC structure, liquidity pools, and FVG detection.
        Primary: Binance / Coinbase PAXGUSDT for Gold; or native MT5 rates if available.
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
        b_interval = binance_tf_map.get(timeframe.upper(), "5m")
        pair = "PAXGUSDT" if any(x in symbol.upper() for x in ["XAU", "GOLD", "PAXG"]) else symbol.upper()

        # 1. Binance public API
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
                return df
        except Exception as e:
            logger.debug(f"Binance kline fetch failed: {e}")

        # 2. Coinbase fallback for Gold
        try:
            granularity = 300 if "5" in b_interval else (900 if "15" in b_interval else 3600)
            cb_url = f"https://api.exchange.coinbase.com/products/PAXG-USD/candles?granularity={granularity}"
            r = requests.get(cb_url, timeout=2.5)
            if r.status_code == 200:
                raw = r.json()
                rows = []
                for item in reversed(raw[:limit]):
                    rows.append({
                        "timestamp": pd.to_datetime(float(item[0]), unit="s", utc=True),
                        "open": float(item[3]),
                        "high": float(item[2]),
                        "low": float(item[1]),
                        "close": float(item[4]),
                        "volume": float(item[5])
                    })
                df = pd.DataFrame(rows)
                return df
        except Exception as e:
            logger.debug(f"Coinbase candle fetch failed: {e}")

        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def get_positions(self, symbol: str = "XAUUSD") -> List[Dict[str, Any]]:
        """Returns open positions filtered by Bot #4 magic number."""
        try:
            r = self.session.get(f"{self.bridge_url}/positions?symbol={symbol}", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json().get("positions", [])
                filtered = [p for p in data if int(p.get("magic", 0)) == self.magic_number]
                return filtered
        except Exception as e:
            logger.debug(f"Positions fetch error: {e}")
        return []

    def get_orders(self, symbol: str = "XAUUSD") -> List[Dict[str, Any]]:
        """Returns pending orders filtered by Bot #4 magic number."""
        try:
            r = self.session.get(f"{self.bridge_url}/orders?symbol={symbol}", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json().get("orders", [])
                filtered = [o for o in data if int(o.get("magic", 0)) == self.magic_number]
                return filtered
        except Exception as e:
            logger.debug(f"Orders fetch error: {e}")
        return []

    def send_order(
        self,
        symbol: str,
        order_type: str,
        price: float,
        volume: float,
        sl: float = 0.0,
        tp: float = 0.0
    ) -> Dict[str, Any]:
        """
        Sends BUY, SELL, BUY_LIMIT, SELL_LIMIT to the MT5 Bridge.
        Includes 15-second duplicate suppression guard.
        """
        now_ts = time.time()
        dispatch_key = f"{symbol}_{order_type.upper()}_{round(price, 1)}_{round(volume, 2)}"
        last_dispatch = self._recent_dispatches.get(dispatch_key, 0.0)
        if (now_ts - last_dispatch) < 15.0:
            logger.warning(f"⚠️ Duplicate order attempt blocked: {dispatch_key}")
            return {"success": False, "error": "Duplicate order blocked by safety guard (within 15s window)"}

        try:
            params = {
                "symbol": symbol,
                "type": order_type.upper(),
                "price": round(price, 2),
                "volume": round(volume, 2),
                "sl": round(sl, 2) if sl > 0 else 0.0,
                "tp": round(tp, 2) if tp > 0 else 0.0,
                "magic": self.magic_number
            }
            url = f"{self.bridge_url}/order_send"
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                self._recent_dispatches[dispatch_key] = now_ts
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def modify_position(self, ticket: int, sl: float, tp: float = 0.0) -> Dict[str, Any]:
        """Modifies Stop Loss and Take Profit of an open position."""
        try:
            params = {
                "ticket": ticket,
                "sl": round(sl, 2) if sl > 0 else 0.0,
                "tp": round(tp, 2) if tp > 0 else 0.0
            }
            url = f"{self.bridge_url}/modify_sl_tp"
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_position(self, ticket: int, volume: float = 0.0) -> Dict[str, Any]:
        """Closes a position (full or partial)."""
        try:
            params = {"ticket": ticket}
            if volume > 0:
                params["volume"] = round(volume, 2)
            url = f"{self.bridge_url}/position_close"
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, ticket: int) -> Dict[str, Any]:
        """Cancels a pending order."""
        try:
            url = f"{self.bridge_url}/order_cancel?ticket={ticket}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close_all_positions(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Emergency Kill Switch: Closes all Bot #4 open positions."""
        try:
            url = f"{self.bridge_url}/close_all?symbol={symbol}&magic={self.magic_number}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
