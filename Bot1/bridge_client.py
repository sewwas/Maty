"""
Bot #1 Dedicated Bridge Client — Sunrise Breakout Trading System
Communicates with Wine MT5 Bridge on port 8001 (or configurable port).
Provides live price streaming, broker candle feeds, position tracking, and order execution.
Aligned 100% with wine_mt5_bridge.py GET endpoints.
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
    def __init__(self, bridge_url: str = "http://127.0.0.1:8001", magic_number: int = 101001, timeout: float = 3.5):
        self.bridge_url = bridge_url.rstrip("/")
        self.magic_number = magic_number
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False  # Avoid proxy issues on localhost
        self._last_known_tick: Dict[str, Any] = {}
        self._last_account_info: Dict[str, Any] = {}
        self._resolved_symbol: Optional[str] = None
        self._recent_dispatches: Dict[str, float] = {}

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
        Fetches historical candles for Bot 1 multi-EMA, ATR, and breakout calculations.
        Tries MT5 Bridge rates first, falls back to Binance public feed.
        """
        target_sym = self._resolved_symbol or symbol
        tf_str = timeframe.lower()

        # 1. Fetch from Wine MT5 Bridge
        try:
            r = self.session.get(f"{self.bridge_url}/rates?symbol={target_sym}&timeframe={tf_str}&count={limit}", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                raw_rates = data.get("rates", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                if raw_rates and len(raw_rates) >= 5:
                    rows = []
                    for item in raw_rates:
                        t_val = item.get("time", time.time())
                        rows.append({
                            "timestamp": pd.to_datetime(int(t_val), unit="s", utc=True),
                            "open": float(item.get("open", 0.0)),
                            "high": float(item.get("high", 0.0)),
                            "low": float(item.get("low", 0.0)),
                            "close": float(item.get("close", 0.0)),
                            "volume": float(item.get("tick_volume", item.get("real_volume", 0.0)))
                        })
                    df = pd.DataFrame(rows)
                    if not df.empty and df["close"].iloc[-1] > 0:
                        return df
        except Exception as e:
            logger.debug(f"Bridge rates endpoint error: {e}")

        # 2. Fallback to Binance public klines
        binance_tf_map = {
            "m1": "1m", "1m": "1m",
            "m5": "5m", "5m": "5m",
            "m15": "15m", "15m": "15m",
            "m30": "30m", "30m": "30m",
            "h1": "1h", "1h": "1h",
            "h4": "4h", "4h": "4h",
            "d1": "1d", "1d": "1d"
        }
        b_interval = binance_tf_map.get(tf_str, "5m")
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

        # 3. Synthetic fallback if all APIs unreachable
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

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch open positions for Bot 1 matching magic number or Bot 1 comment.
        wine_mt5_bridge.py returns {'positions': [...]}
        """
        try:
            url = f"{self.bridge_url}/positions"
            if symbol:
                url += f"?symbol={symbol}"
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 200:
                raw = r.json()
                pos_list = raw.get("positions", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
                
                bot_positions = []
                for p in pos_list:
                    p_magic = int(p.get("magic", 0))
                    p_comment = str(p.get("comment", ""))
                    if p_magic == self.magic_number or "Sunrise" in p_comment or "Auto Grid" in p_comment or "Bot 1" in p_comment:
                        bot_positions.append(p)
                
                return bot_positions
        except Exception as e:
            logger.debug(f"Error fetching positions from bridge: {e}")
        return []

    def send_order(
        self,
        action: str,
        symbol: str,
        volume: float,
        price: float = 0.0,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "Sunrise Bot 1"
    ) -> Dict[str, Any]:
        """
        Dispatch market order to Wine MT5 terminal via GET /order_send.
        Includes duplicate order suppression guard (15s window).
        """
        target_sym = self._resolved_symbol or symbol
        order_type = action.upper()
        now_ts = time.time()
        
        dispatch_key = f"{target_sym}_{order_type}_{round(volume, 2)}"
        last_dispatch = self._recent_dispatches.get(dispatch_key, 0.0)
        if (now_ts - last_dispatch) < 15.0:
            logger.warning(f"⚠️ Duplicate order attempt blocked by safety guard: {dispatch_key}")
            return {"success": False, "error": f"Duplicate order suppressed (within 15s window)"}

        params: Dict[str, Any] = {
            "symbol": target_sym,
            "type": order_type,
            "volume": round(float(volume), 2),
            "price": round(float(price), 2) if price > 0 else 0.0,
            "magic": self.magic_number
        }
        if sl is not None and sl > 0:
            params["sl"] = round(float(sl), 2)
        if tp is not None and tp > 0:
            params["tp"] = round(float(tp), 2)

        try:
            url = f"{self.bridge_url}/order_send"
            r = self.session.get(url, params=params, timeout=5.0)
            if r.status_code == 200:
                res = r.json()
                if res.get("success") or res.get("retcode") in (0, 10009, 10008, 10004):
                    self._recent_dispatches[dispatch_key] = now_ts
                logger.info(f"✅ Order dispatch result: {res}")
                return res
            else:
                logger.error(f"❌ Order dispatch failed HTTP {r.status_code}: {r.text}")
                return {"success": False, "error": r.text}
        except Exception as e:
            logger.error(f"❌ Order dispatch exception: {e}")
            return {"success": False, "error": str(e)}

    def close_position(self, ticket: int, volume: float = 0.0) -> Dict[str, Any]:
        """Close an open position by ticket number via GET /position_close."""
        try:
            params: Dict[str, Any] = {"ticket": int(ticket)}
            if volume > 0:
                params["volume"] = round(float(volume), 2)
            url = f"{self.bridge_url}/position_close"
            r = self.session.get(url, params=params, timeout=4.0)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            logger.error(f"Error closing position {ticket}: {e}")
            return {"success": False, "error": str(e)}

    def modify_position(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """Modify SL and TP of an open position via GET /modify_sl_tp."""
        try:
            params: Dict[str, Any] = {"ticket": int(ticket)}
            if sl is not None and sl > 0:
                params["sl"] = round(float(sl), 2)
            if tp is not None and tp > 0:
                params["tp"] = round(float(tp), 2)
            url = f"{self.bridge_url}/modify_sl_tp"
            r = self.session.get(url, params=params, timeout=4.0)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            logger.error(f"Error modifying position {ticket}: {e}")
            return {"success": False, "error": str(e)}

    def close_all_positions(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """Emergency kill switch closing all open positions via GET /close_all."""
        target_sym = self._resolved_symbol or symbol
        try:
            url = f"{self.bridge_url}/close_all?symbol={target_sym}"
            r = self.session.get(url, timeout=5.0)
            if r.status_code == 200:
                return r.json()
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            logger.error(f"Error executing close_all: {e}")
            return {"success": False, "error": str(e)}
