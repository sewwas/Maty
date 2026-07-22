import requests
import pandas as pd
import numpy as np
import time
from typing import Optional, Tuple, List

def get_live_price(symbol: str = "BTCUSDT") -> Optional[float]:
    """
    Fetch the current price of a cryptocurrency from the public Binance REST API.
    Does not require API keys.
    """
    url = f"https://api.binance.com/api/v3/ticker/price"
    params = {"symbol": symbol.upper()}
    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data["price"])
    except Exception as e:
        print(f"Error fetching live price for {symbol}: {e}")
        return None

def get_historical_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 500) -> Optional[pd.DataFrame]:
    """
    Fetch historical candlestick data from Binance API.
    interval: '1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d'
    limit: max 1000
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Parse fields
        parsed_data = []
        for item in data:
            parsed_data.append([
                float(item[0]) / 1000.0, # Convert open time ms to seconds Unix
                float(item[1]),          # Open
                float(item[2]),          # High
                float(item[3]),          # Low
                float(item[4]),          # Close
                float(item[5])           # Volume
            ])
            
        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(parsed_data, columns=columns)
        return df
    except Exception as e:
        print(f"Error fetching historical data for {symbol}: {e}")
        return None

def interpolate_ticks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Interpolates 4 ticks (Open -> High/Low -> Low/High -> Close) for each bar.
    This simulates inner-candle price movements, crucial for breakout grid order triggering.
    
    If it's a green bar (Close >= Open):
        Open -> Low -> High -> Close
    If it's a red bar (Close < Open):
        Open -> High -> Low -> Close
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
            
        # Distribute timestamp across the bar
        # Assuming 1-minute interval = 60 seconds
        dt = 15.0 # 60 / 4
        for i, val in enumerate(path):
            ticks.append({
                "timestamp": t + (i * dt),
                "price": val,
                "volume": v
            })
            
    return pd.DataFrame(ticks)

def generate_simulated_ticks(start_price: float, num_ticks: int = 100, volatility: float = 0.0005, drift: float = 0.0) -> List[Tuple[float, float]]:
    """
    Generates a simulated random walk price path.
    Returns a list of (timestamp, price) tuples.
    """
    ticks = []
    current_price = start_price
    current_time = time.time()
    
    for i in range(num_ticks):
        # Log-normal random walk step
        change = current_price * (np.random.normal(drift, volatility))
        current_price += change
        current_time += 1.0 # 1 second increments
        ticks.append((current_time, current_price))
        
    return ticks
