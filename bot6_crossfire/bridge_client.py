"""
Bot #6 Dedicated Bridge Client — FVG Crossfire
Communicates with MT5 Bridge on port 8006
"""
import time
import logging
import requests
import pandas as pd

logger = logging.getLogger("Bot6BridgeClient")

class Bot6BridgeClient:
    def __init__(self, bridge_url: str = "http://127.0.0.1:8006", magic_number: int = 60000, timeout: float = 3.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.magic_number = magic_number
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False

    def is_healthy(self) -> bool:
        try:
            r = self.session.get(f"{self.bridge_url}/health", timeout=2.5)
            return r.status_code == 200
        except Exception:
            return False

    def get_tick(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.bridge_url}/tick?symbol={symbol}", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                if "ask" in data and "bid" in data:
                    return {"ask": data["ask"], "bid": data["bid"], "price": data.get("price", data["ask"])}
        except Exception as e:
            logger.debug(f"Error fetching tick from bridge: {e}")
        return {}

    def get_candles(self, symbol: str, timeframe: str = "1m", limit: int = 200) -> pd.DataFrame:
        try:
            url = f"{self.bridge_url}/rates?symbol={symbol}&timeframe={timeframe}&count={limit}"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                if "rates" in data and data["rates"]:
                    df = pd.DataFrame(data["rates"])
                    if "time" in df.columns:
                        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                    return df
        except Exception as e:
            logger.debug(f"Bridge rates fetch failed: {e}")
        return pd.DataFrame()

    def open_trade(self, symbol: str, action: str, volume: float, stop_loss: float = 0.0, take_profit: float = 0.0, comment: str = "Bot6") -> dict:
        params = {
            "symbol": symbol,
            "type": action.upper(),
            "price": 0.0,
            "volume": round(float(volume), 2),
            "sl": round(float(stop_loss), 5) if stop_loss > 0 else 0.0,
            "tp": round(float(take_profit), 5) if take_profit > 0 else 0.0,
            "magic": self.magic_number,
            "comment": comment
        }
        try:
            r = self.session.get(f"{self.bridge_url}/order_send", params=params, timeout=self.timeout)
            if r.status_code == 200:
                res = r.json()
                if res.get("success", False) or res.get("ticket"):
                    logger.info(f"🚀 Bot #6 Order Executed: {action} {volume} {symbol} @ SL={stop_loss}, TP={take_profit} | Ticket: {res.get('ticket')}")
                else:
                    logger.error(f"❌ Bot #6 Order Failed: {res.get('error')}")
                return res
            return {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            logger.error(f"❌ Exception sending order: {e}")
            return {"success": False, "error": str(e)}
