"""
Profity AI — Bot #2 Dedicated Bridge & Market Data Client
=========================================================
Standalone REST bridge client & market data feeder for Bot #2 Manual Grid Desk.
Eliminates any external dependencies on the root `core` package.
Connects directly to Wine MT5 REST Bridge on Port 8002.
"""

import os
import time
import json
import logging
from typing import Dict, List, Optional, Any
import requests
import pandas as pd

logger = logging.getLogger("Bot2BridgeClient")

MT5_AVAILABLE = False
mt5 = None

_DEFAULT_PRICE_TABLE = {
    "PAXGUSDT": 3280.0,
    "XAUUSD": 3280.0,
    "GOLD": 3280.0,
    "BTCUSDT": 90000.0,
    "EURUSD": 1.0850,
}

_LIVE_PRICE_CACHE = {}          # {sym: (price, timestamp)}
_HISTORICAL_KLINES_CACHE = {}   # {key: (df, timestamp)}

_FAST_SESSION = requests.Session()
_FAST_SESSION.trust_env = False
_adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=50, max_retries=0)
_FAST_SESSION.mount("http://", _adapter)


def get_default_price(symbol: str = "XAUUSD") -> float:
    """Returns a sensible fallback price for gold or crypto."""
    sym = str(symbol).upper().strip()
    if sym in _DEFAULT_PRICE_TABLE:
        return _DEFAULT_PRICE_TABLE[sym]
    if any(k in sym for k in ("PAXG", "XAU", "GOLD")):
        return 3280.0
    return 100.0


def get_live_price(symbol: str = "PAXGUSDT") -> float:
    """
    Fetches real-time price with sub-second RAM cache.
    Tries MT5 Bridge (port 8002) first, falls back to Binance/Coinbase public APIs.
    """
    sym = str(symbol).upper().strip()
    now = time.time()

    if sym in _LIVE_PRICE_CACHE:
        cached_price, cached_t = _LIVE_PRICE_CACHE[sym]
        if now - cached_t < 1.0 and cached_price > 0:
            return cached_price

    # 1. Try MT5 Bridge on port 8002
    bridge_port = os.environ.get("WINE_BRIDGE_PORT", "8002")
    bridge_sym = "XAUUSD" if any(x in sym for x in ("XAU", "GOLD", "PAXG")) else sym
    try:
        r = _FAST_SESSION.get(f"http://127.0.0.1:{bridge_port}/symbol_info?symbol={bridge_sym}", timeout=1.5)
        if r.status_code == 200:
            d = r.json()
            ask = float(d.get("ask", 0.0) or 0.0)
            bid = float(d.get("bid", 0.0) or 0.0)
            if ask > 0 and bid > 0:
                mid = round((ask + bid) / 2.0, 2)
                _LIVE_PRICE_CACHE[sym] = (mid, now)
                return mid
    except Exception:
        pass

    # 2. Try Binance Public API
    binance_sym = "PAXGUSDT" if any(x in sym for x in ("XAU", "GOLD", "PAXG")) else sym
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={binance_sym}", timeout=1.5)
        if r.status_code == 200:
            p = float(r.json().get("price", 0.0))
            if p > 0:
                _LIVE_PRICE_CACHE[sym] = (p, now)
                return p
    except Exception:
        pass

    # 3. Try Coinbase Public API
    try:
        r = requests.get("https://api.exchange.coinbase.com/products/PAXG-USD/ticker", timeout=1.5)
        if r.status_code == 200:
            p = float(r.json().get("price", 0.0))
            if p > 0:
                _LIVE_PRICE_CACHE[sym] = (p, now)
                return p
    except Exception:
        pass

    # 4. Fallback to cached or default
    if sym in _LIVE_PRICE_CACHE:
        return _LIVE_PRICE_CACHE[sym][0]

    def_p = get_default_price(sym)
    _LIVE_PRICE_CACHE[sym] = (def_p, now)
    return def_p


def get_historical_klines(symbol: str = "PAXGUSDT", interval: str = "15m", limit: int = 120) -> pd.DataFrame:
    """
    Fetches historical candlestick dataframe with 15-second RAM cache.
    Returns DataFrame with columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume'].
    """
    sym = str(symbol).upper().strip()
    pair = "PAXGUSDT" if any(x in sym for x in ("XAU", "GOLD", "PAXG")) else sym
    cache_key = f"{pair}_{interval}_{limit}"
    now = time.time()

    if cache_key in _HISTORICAL_KLINES_CACHE:
        cached_df, cached_t = _HISTORICAL_KLINES_CACHE[cache_key]
        if now - cached_t < 15.0 and len(cached_df) > 0:
            return cached_df

    # 1. Binance Public API
    binance_tf_map = {
        "1M": "1m", "1m": "1m", "M1": "1m",
        "5M": "5m", "5m": "5m", "M5": "5m",
        "15M": "15m", "15m": "15m", "M15": "15m",
        "30M": "30m", "30m": "30m", "M30": "30m",
        "1H": "1h", "1h": "1h", "H1": "1h",
        "4H": "4h", "4h": "4h", "H4": "4h",
        "1D": "1d", "1d": "1d", "D1": "1d"
    }
    b_interval = binance_tf_map.get(str(interval).upper(), "15m")

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
            _HISTORICAL_KLINES_CACHE[cache_key] = (df, now)
            return df
    except Exception as e:
        logger.debug(f"Binance klines failed: {e}")

    # 2. Coinbase Public API fallback
    try:
        granularity = 900 if "15" in b_interval else (300 if "5" in b_interval else 3600)
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
            _HISTORICAL_KLINES_CACHE[cache_key] = (df, now)
            return df
    except Exception as e:
        logger.debug(f"Coinbase klines failed: {e}")

    # Fallback to cached or empty
    if cache_key in _HISTORICAL_KLINES_CACHE:
        return _HISTORICAL_KLINES_CACHE[cache_key][0]
    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


class BridgeOrder:
    """Lightweight order data carrier matching MT5Broker/MT5 API schema."""
    def __init__(self, order_type="BUY_STOP", price=0.0, size=0.01, timestamp=0.0):
        self.order_id = f"ord_{int(time.time() * 1000)}"
        self.type = order_type
        self.price = float(price)
        self.trigger_price = float(price)
        self.price_open = float(price)
        self.size = float(size)
        self.volume = float(size)
        self.volume_initial = float(size)
        self.timestamp = timestamp or time.time()
        self.ticket = 0
        self.magic = 777001
        self.sl = 0.0
        self.tp = 0.0
        self.symbol = "XAUUSD"


class BridgePos:
    """Lightweight position data carrier matching MT5Broker/MT5 API schema."""
    def __init__(self, d: dict = None):
        if not d: d = {}
        self.ticket = int(d.get("ticket", 0))
        self.position_id = f"live_{self.ticket}"
        self.symbol = str(d.get("symbol", "XAUUSD"))
        self.type = int(d.get("type", 0))  # 0 = BUY, 1 = SELL
        self.price_open = float(d.get("price_open", 0.0))
        self.price_current = float(d.get("price_current", 0.0))
        self.volume = float(d.get("volume", 0.01))
        self.sl = float(d.get("sl", 0.0))
        self.tp = float(d.get("tp", 0.0))
        self.profit = float(d.get("profit", 0.0))
        self.magic = int(d.get("magic", 777001))
        self.comment = str(d.get("comment", ""))


class MT5Broker:
    """
    Dedicated REST Bridge Broker for Bot #2 Manual Grid Desk.
    Fully isolated from Bot #1 and local Windows MT5 DLLs.
    Communicates directly with Wine MT5 REST Bridge on Port 8002.
    """
    def __init__(
        self,
        symbol: str = "PAXGUSDT",
        login: Optional[int] = None,
        password: str = "",
        server: str = "",
        magic_number: int = 777001
    ):
        self.symbol = symbol
        self.magic_number = magic_number
        self.login = login
        self.password = password
        self.server = server
        self.pending_orders: Dict[str, Any] = {}
        self.ticket_to_order_id: Dict[int, str] = {}
        self.open_positions: Dict[str, Any] = {}
        self.session = _FAST_SESSION
        self.bridge_port = os.environ.get("WINE_BRIDGE_PORT", "8002")

    @property
    def bridge_url(self) -> str:
        port = os.environ.get("WINE_BRIDGE_PORT", self.bridge_port)
        return f"http://127.0.0.1:{port}"

    def ensure_connected(self) -> bool:
        """Verifies connection to MT5 REST bridge."""
        try:
            r = self.session.get(f"{self.bridge_url}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        try:
            r = self.session.get(f"{self.bridge_url}/account", timeout=2.0)
            if r.status_code == 200:
                return bool(r.json().get("connected", False))
        except Exception:
            pass
        return False

    def get_min_stop_distance(self) -> float:
        """Minimum stop distance in points/USD for XAUUSD stop orders."""
        return 0.50

    def get_account_info(self) -> dict:
        """Queries account telemetry from bridge."""
        try:
            r = self.session.get(f"{self.bridge_url}/account", timeout=3.0)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {"connected": False, "login": 0, "balance": 0.0, "equity": 0.0, "currency": "USD"}

    def _fetch_live_positions(self, symbol: Optional[str] = None) -> List[BridgePos]:
        """Fetches active open positions from bridge."""
        try:
            sym_param = f"?symbol={symbol}" if symbol else ""
            r = self.session.get(f"{self.bridge_url}/positions{sym_param}", timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                res = []
                for d in data.get("positions", []):
                    p = BridgePos(d)
                    self.open_positions[p.position_id] = p
                    res.append(p)
                return res
        except Exception as e:
            logger.debug(f"fetch positions error: {e}")
        return list(self.open_positions.values())

    def _fetch_live_orders(self, symbol: Optional[str] = None) -> List[BridgeOrder]:
        """Fetches pending orders from bridge."""
        try:
            sym_param = f"?symbol={symbol}" if symbol else ""
            r = self.session.get(f"{self.bridge_url}/orders{sym_param}", timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                res = []
                for d in data.get("orders", []):
                    o = BridgeOrder(
                        order_type="BUY_STOP" if int(d.get("type", 4)) in (2, 4) else "SELL_STOP",
                        price=float(d.get("price_open", 0.0)),
                        size=float(d.get("volume_initial", 0.01)),
                        timestamp=float(d.get("time_setup", time.time()))
                    )
                    o.ticket = int(d.get("ticket", 0))
                    o.type = int(d.get("type", 4))
                    o.price_open = float(d.get("price_open", 0.0))
                    o.volume_initial = float(d.get("volume_initial", 0.01))
                    o.sl = float(d.get("sl", 0.0))
                    o.tp = float(d.get("tp", 0.0))
                    o.magic = int(d.get("magic", self.magic_number))
                    o.symbol = str(d.get("symbol", "XAUUSD"))
                    res.append(o)
                return res
        except Exception as e:
            logger.debug(f"fetch orders error: {e}")
        return []

    def place_order(
        self,
        order_type: str,
        price: float,
        size: float,
        timestamp: float,
        tp: float = 0.0,
        sl: float = 0.0
    ) -> Optional[BridgeOrder]:
        """
        Dispatches a pending stop order or market order to the MT5 bridge.
        """
        sym = "XAUUSD"
        try:
            url = (
                f"{self.bridge_url}/order_send"
                f"?symbol={sym}&type={order_type}&price={price:.2f}&volume={size:.2f}"
                f"&sl={sl:.2f}&tp={tp:.2f}&magic={self.magic_number}"
            )
            r = self.session.get(url, timeout=4.0)
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    ticket = int(data.get("ticket", 0) or 0)
                    ord_obj = BridgeOrder(order_type, price, size, timestamp)
                    ord_obj.ticket = ticket
                    ord_obj.order_id = f"mt5_{ticket}"
                    ord_obj.magic = self.magic_number
                    self.pending_orders[ord_obj.order_id] = ord_obj
                    if ticket > 0:
                        self.ticket_to_order_id[ticket] = ord_obj.order_id
                    return ord_obj
                else:
                    err = data.get("error", "Unknown rejection")
                    logger.warning(f"Bridge order rejected: {err}")
        except Exception as e:
            logger.error(f"place_order exception: {e}")
        return None
