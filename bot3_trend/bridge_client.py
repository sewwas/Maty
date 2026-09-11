"""
Bot #3 Dedicated Bridge Client
Communicates with MT5 Bridge on port 8003 (or configurable port)
Provides seamless fallback, position tracking, and order management.
"""

import time
import json
import logging
import datetime
from typing import Dict, List, Optional, Any
import requests
import pandas as pd

logger = logging.getLogger("Bot3BridgeClient")


class Bot3BridgeClient:
    def __init__(self, bridge_url: str = "http://127.0.0.1:8003", magic_number: int = 998873, timeout: float = 3.0):
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

        # Fallback to public live price (Coinbase / Binance for PAXG / Gold)
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
        Fetches historical candles for trend calculation and Asian range.
        Primary: Binance / Coinbase PAXGUSDT for sub-second live streaming candles.
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
            r = requests.get(url, timeout=2.0)
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

        # 2. Coinbase fallback
        try:
            granularity = 300 if "5" in b_interval else (900 if "15" in b_interval else 3600)
            cb_url = f"https://api.exchange.coinbase.com/products/PAXG-USD/candles?granularity={granularity}"
            r = requests.get(cb_url, timeout=2.0)
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
        """Returns open positions filtered strictly by Bot #3 magic number."""
        try:
            url = f"{self.bridge_url}/positions?symbol={symbol}&magic={self.magic_number}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json().get("positions", [])
                filtered = [p for p in data if int(p.get("magic", 0)) == self.magic_number]
                if filtered:
                    return filtered
            # Fallback without symbol constraint to guarantee zero symbol naming mismatch (e.g. XAUUSD vs XAUUSDc)
            r_all = self.session.get(f"{self.bridge_url}/positions?magic={self.magic_number}", timeout=self.timeout)
            if r_all.status_code == 200:
                data = r_all.json().get("positions", [])
                return [p for p in data if int(p.get("magic", 0)) == self.magic_number]
        except Exception as e:
            logger.debug(f"Positions fetch error: {e}")
        return []

    def get_orders(self, symbol: str = "XAUUSD") -> List[Dict[str, Any]]:
        """Returns pending breakout orders filtered strictly by Bot #3 magic number."""
        try:
            url = f"{self.bridge_url}/orders?symbol={symbol}&magic={self.magic_number}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json().get("orders", [])
                filtered = [o for o in data if int(o.get("magic", 0)) == self.magic_number]
                if filtered:
                    return filtered
            # Fallback without symbol constraint to guarantee zero symbol naming mismatch
            r_all = self.session.get(f"{self.bridge_url}/orders?magic={self.magic_number}", timeout=self.timeout)
            if r_all.status_code == 200:
                data = r_all.json().get("orders", [])
                return [o for o in data if int(o.get("magic", 0)) == self.magic_number]
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
        Sends BUY, SELL, BUY_STOP, or SELL_STOP to the MT5 Bridge.
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
        """Emergency Kill Switch: Closes all Bot #3 open positions."""
        try:
            url = f"{self.bridge_url}/close_all?symbol={symbol}&magic={self.magic_number}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_all_orders(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Emergency Cancel: Cancels all Bot #3 pending orders."""
        try:
            url = f"{self.bridge_url}/cancel_all?symbol={symbol}&magic={self.magic_number}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Fetches raw closed trade deals from bridge for Bot #3 magic number."""
        try:
            url = f"{self.bridge_url}/history?days={days}&magic={self.magic_number}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                return r.json().get("deals", [])
        except Exception as e:
            logger.debug(f"History fetch error: {e}")
        return []

    def get_closed_deals(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Reconstructs round-trip closed trades by matching entry (IN) and exit (OUT) deals.
        Extracts: ticket, position_id, open_time, close_time, symbol, side, lots,
        entry_price, exit_price, gross_profit, swap, commission, net_pnl, comment.
        """
        raw_deals = self.get_history(days=days)
        if not raw_deals:
            return []

        # Filter strictly for Bot #3 magic number (zero leakage from other bots)
        bot_deals = [d for d in raw_deals if int(d.get("magic", 0)) == self.magic_number]
        if not bot_deals:
            return []

        in_deals = {d.get("position_id"): d for d in bot_deals if d.get("entry") == 0}
        out_deals = [d for d in bot_deals if d.get("entry") in (1, 2)]

        records = []
        for d in out_deals:
            pid = d.get("position_id")
            open_d = in_deals.get(pid)

            # Determine trade side
            if open_d:
                side = "BUY" if open_d.get("type") == 0 else "SELL"
                open_px = float(open_d.get("price", 0.0))
                open_time_sec = float(open_d.get("time", 0))
            else:
                # Type 1 (SELL) closes a BUY; Type 0 (BUY) closes a SELL
                side = "BUY" if d.get("type") == 1 else "SELL"
                open_px = 0.0
                open_time_sec = 0

            close_px = float(d.get("price", 0.0))
            vol = float(d.get("volume", 0.0))
            profit = float(d.get("profit", 0.0))
            swap = float(d.get("swap", 0.0))
            comm = float(d.get("commission", 0.0))
            net_pnl = profit + swap + comm

            # Estimate open price if missing
            if open_px <= 0.0 and vol > 0:
                pts_diff = profit / (vol * 100.0)
                open_px = close_px - pts_diff if side == "BUY" else close_px + pts_diff

            close_time_sec = float(d.get("time", 0))
            close_time_str = datetime.datetime.fromtimestamp(close_time_sec).strftime("%Y-%m-%d %H:%M:%S") if close_time_sec else "—"
            open_time_str = datetime.datetime.fromtimestamp(open_time_sec).strftime("%Y-%m-%d %H:%M:%S") if open_time_sec else "—"

            records.append({
                "ticket": d.get("ticket") or d.get("order") or pid,
                "position_id": pid,
                "symbol": d.get("symbol", "XAUUSD"),
                "side": side,
                "volume": vol,
                "open_time": open_time_str,
                "close_time": close_time_str,
                "open_price": round(open_px, 2),
                "close_price": round(close_px, 2),
                "profit": round(profit, 2),
                "swap": round(swap, 2),
                "commission": round(comm, 2),
                "net_pnl": round(net_pnl, 2),
                "comment": str(d.get("comment", "")).strip(),
                "_close_timestamp": close_time_sec
            })

        records.sort(key=lambda x: x["_close_timestamp"], reverse=True)
        return records
