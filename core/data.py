import requests
import pandas as pd
import numpy as np
import time
from typing import Optional, Tuple, List

def get_live_price(symbol: str = "BTCUSDT") -> Optional[float]:
    """
    Fetch the current price of a cryptocurrency from public REST APIs.
    Tries Binance -> Coinbase -> OKX -> Bybit to ensure price availability across all regions/networks.
    """
    sym = symbol.upper()
    # 1. Try Binance API
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        response = requests.get(url, params={"symbol": sym}, timeout=1.5)
        if response.status_code == 200:
            data = response.json()
            if "price" in data:
                return float(data["price"])
    except Exception:
        pass

    # 2. Fallback to Coinbase API
    base = sym.replace("USDT", "").replace("USD", "")
    try:
        coinbase_url = f"https://api.coinbase.com/v2/prices/{base}-USD/spot"
        response = requests.get(coinbase_url, timeout=1.5)
        if response.status_code == 200:
            data = response.json()
            if "data" in data and "amount" in data["data"]:
                return float(data["data"]["amount"])
    except Exception:
        pass

    # 3. Fallback to OKX API
    try:
        okx_symbol = f"{base}-USDT"
        okx_url = f"https://www.okx.com/api/v5/market/ticker?instId={okx_symbol}"
        response = requests.get(okx_url, timeout=1.5)
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0 and "last" in data["data"][0]:
                return float(data["data"][0]["last"])
    except Exception:
        pass

    # 4. Fallback to Bybit API
    try:
        bybit_url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym}"
        response = requests.get(bybit_url, timeout=1.5)
        if response.status_code == 200:
            data = response.json()
            if "result" in data and "list" in data["result"] and len(data["result"]["list"]) > 0:
                return float(data["result"]["list"][0]["lastPrice"])
    except Exception:
        pass

    print(f"Error fetching live price for {symbol} across all exchange APIs.")
    return None

def get_historical_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 500) -> Optional[pd.DataFrame]:
    """
    Fetch historical candlestick data from REST APIs.
    Tries Binance -> Coinbase -> OKX -> Bybit fallback chain.
    """
    sym = symbol.upper()
    # 1. Try Binance API
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": sym, "interval": interval, "limit": limit}
        response = requests.get(url, params=params, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            parsed_data = []
            for item in data:
                parsed_data.append([
                    float(item[0]) / 1000.0,
                    float(item[1]),
                    float(item[2]),
                    float(item[3]),
                    float(item[4]),
                    float(item[5])
                ])
            return pd.DataFrame(parsed_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    except Exception:
        pass

    # 2. Fallback to Coinbase API
    base = sym.replace("USDT", "").replace("USD", "")
    try:
        cb_url = f"https://api.exchange.coinbase.com/products/{base}-USD/candles"
        response = requests.get(cb_url, params={"granularity": 60}, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                parsed_data = []
                for item in reversed(data[:limit]):
                    parsed_data.append([
                        float(item[0]), # timestamp in seconds
                        float(item[3]), # open
                        float(item[2]), # high
                        float(item[1]), # low
                        float(item[4]), # close
                        float(item[5])  # volume
                    ])
                return pd.DataFrame(parsed_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    except Exception:
        pass

    # 3. Fallback to OKX API
    try:
        okx_symbol = f"{base}-USDT"
        okx_url = f"https://www.okx.com/api/v5/market/candles?instId={okx_symbol}&limit={limit}"
        response = requests.get(okx_url, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                parsed_data = []
                for item in reversed(data["data"]):
                    parsed_data.append([
                        float(item[0]) / 1000.0,
                        float(item[1]), # open
                        float(item[2]), # high
                        float(item[3]), # low
                        float(item[4]), # close
                        float(item[5])  # volume
                    ])
                return pd.DataFrame(parsed_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    except Exception:
        pass

    print(f"Error fetching historical data for {symbol} across all exchange APIs.")
    return None

def interpolate_ticks(df: pd.DataFrame, bar_seconds: float = 60.0) -> pd.DataFrame:
    """
    Interpolates 4 ticks (Open -> High/Low -> Low/High -> Close) for each bar.
    This simulates inner-candle price movements, crucial for breakout grid order triggering.
    
    If it's a green bar (Close >= Open):
        Open -> Low -> High -> Close
    If it's a red bar (Close < Open):
        Open -> High -> Low -> Close

    bar_seconds: duration of each candle in seconds (default 60 for 1m bars).
    """
    ticks = []
    
    for idx, row in df.iterrows():
        t = row["timestamp"]
        o = row["open"]
        h = row["high"]
        l = row["low"]
        c = row["close"]
        v = row["volume"] / 4.0 # distribute volume
        
        if c >= o:
            # Green candle: Open -> Low -> High -> Close
            path = [o, l, h, c]
        else:
            # Red candle: Open -> High -> Low -> Close
            path = [o, h, l, c]
            
        # Distribute timestamp evenly across the bar
        dt = bar_seconds / 4.0
        for i, val in enumerate(path):
            ticks.append({
                "timestamp": t + (i * dt),
                "price": val,
                "volume": v
            })
            
    return pd.DataFrame(ticks)

