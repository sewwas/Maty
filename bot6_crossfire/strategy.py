import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("bot6.strategy")

class FVG:
    def __init__(self, direction: int, top: float, bottom: float, start_idx: int):
        self.direction = direction  # 1 for Bullish, -1 for Bearish
        self.top = top
        self.bottom = bottom
        self.start_idx = start_idx
        self.active = True

class StrategyEngine:
    def __init__(self, config):
        self.config = config
        self.fvg_min_gap = config.get("fvg_min_gap_percent", 0.002) / 100
        self.vp_lookback = config.get("volume_profile_lookback", 200)
        
    def find_fvgs(self, df: pd.DataFrame) -> list:
        fvgs = []
        for i in range(2, len(df)):
            close_price = df.iloc[i]['close']
            low_curr = df.iloc[i]['low']
            high_curr = df.iloc[i]['high']
            high_prev2 = df.iloc[i-2]['high']
            low_prev2 = df.iloc[i-2]['low']
            
            # Bullish FVG: Current low > 2-bars-ago high
            if low_curr > high_prev2:
                gap = low_curr - high_prev2
                if gap / close_price >= self.fvg_min_gap:
                    fvgs.append(FVG(1, low_curr, high_prev2, i))
                    
            # Bearish FVG: Current high < 2-bars-ago low
            elif high_curr < low_prev2:
                gap = low_prev2 - high_curr
                if gap / close_price >= self.fvg_min_gap:
                    fvgs.append(FVG(-1, low_prev2, high_curr, i))
                    
        return fvgs

    def calculate_poc(self, df: pd.DataFrame, start_idx: int, end_idx: int, rows: int = 30) -> float:
        if start_idx >= end_idx or start_idx < 0:
            return 0.0
        
        subset = df.iloc[start_idx:end_idx]
        max_price = subset['high'].max()
        min_price = subset['low'].min()
        
        if max_price == min_price:
            return max_price
            
        step = (max_price - min_price) / rows
        profile = {i: 0.0 for i in range(rows)}
        
        for _, row in subset.iterrows():
            vol = row['tick_volume']
            high = row['high']
            low = row['low']
            
            for i in range(rows):
                bin_top = max_price - (i * step)
                bin_bot = bin_top - step
                
                # Check if candle intersects with this bin
                if not (low > bin_top or high < bin_bot):
                    profile[i] += vol
                    
        max_vol = 0
        poc_bin = 0
        for i, vol in profile.items():
            if vol > max_vol:
                max_vol = vol
                poc_bin = i
                
        poc_price = max_price - (poc_bin * step) - (step / 2)
        return poc_price

    def analyze(self, df: pd.DataFrame) -> dict:
        """Runs full analysis and returns a signal if 3-conditions meet."""
        if len(df) < self.vp_lookback:
            return {"signal": 0}
            
        fvgs = self.find_fvgs(df)
        
        if not fvgs:
            return {"signal": 0}
            
        last_fvg = fvgs[-1]
        
        # 1st Signal: FVG must be fresh (formed in the last 3 candles)
        if last_fvg.start_idx < len(df) - 3:
            return {"signal": 0}
            
        # 2nd Signal: Calculate POC for recent window
        poc_price = self.calculate_poc(df, len(df) - self.vp_lookback, len(df))
        
        # 3rd Signal: Alignment (POC must be inside the fresh FVG zone)
        if last_fvg.direction == 1:
            if last_fvg.bottom <= poc_price <= last_fvg.top:
                logger.info(f"Bullish 3-Signal Confluence Detected! POC at {poc_price:.5f} inside FVG {last_fvg.bottom:.5f}-{last_fvg.top:.5f}")
                return {"signal": 1, "poc": poc_price, "sl": last_fvg.bottom}
                
        elif last_fvg.direction == -1:
            if last_fvg.bottom <= poc_price <= last_fvg.top:
                logger.info(f"Bearish 3-Signal Confluence Detected! POC at {poc_price:.5f} inside FVG {last_fvg.bottom:.5f}-{last_fvg.top:.5f}")
                return {"signal": -1, "poc": poc_price, "sl": last_fvg.top}
                
        return {"signal": 0}
