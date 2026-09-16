import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("bot6.strategy")

class BaseFVG:
    def __init__(self, direction: int, top: float, bottom: float, start_idx: int):
        self.direction = direction  # 1 for Bullish, -1 for Bearish
        self.top = top
        self.bottom = bottom
        self.lag_top = top
        self.lag_bottom = bottom
        self.start_idx = start_idx

class CrossfireSegment:
    def __init__(self, direction: int, top: float, bottom: float, create_idx: int, chain_id: int):
        self.direction = direction
        self.top = top
        self.bottom = bottom
        self.create_idx = create_idx
        self.active = True
        self.done = False
        self.touching = False
        self.chain_id = chain_id
        self.retest_count = 0

class CrossfireTracker:
    def __init__(self, min_gap_percent: float):
        self.min_gap = min_gap_percent
        self.snap_bars = 3
        self.fvgs = []
        self.segs = []
        self.chain_seq = 0
        self.events = {}

    def lag_mitigate(self, df: pd.DataFrame, current_idx: int, fvg_mitig_close: bool = True):
        for f in self.fvgs:
            if f.start_idx < current_idx - self.snap_bars:
                lag_idx = current_idx - self.snap_bars
                if lag_idx >= 0:
                    row = df.iloc[lag_idx]
                    if f.direction == 1:
                        sl = row['close'] if fvg_mitig_close else row['low']
                        if sl < f.lag_top:
                            f.lag_top = max(sl, f.lag_bottom)
                    else:
                        sh = row['close'] if fvg_mitig_close else row['high']
                        if sh > f.lag_bottom:
                            f.lag_bottom = min(sh, f.lag_top)

    def merge_zone(self, direction: int, top: float, bot: float) -> bool:
        for s in self.segs:
            if s.active and not s.done and s.direction == direction and bot <= s.top and s.bottom <= top:
                s.top = max(s.top, top)
                s.bottom = min(s.bottom, bot)
                return True
        return False

    def new_segment(self, direction: int, top: float, bot: float, chain_id: int, create_idx: int):
        s = CrossfireSegment(direction, top, bot, create_idx, chain_id)
        self.segs.append(s)
        return s

    def flip_segment(self, s: CrossfireSegment, new_fvg: BaseFVG, current_idx: int) -> bool:
        t = min(new_fvg.top, s.top)
        bot = max(new_fvg.bottom, s.bottom)
        if bot < t:
            s.active = False
            self.new_segment(new_fvg.direction, t, bot, s.chain_id, new_fvg.start_idx - 1)
            return True
        return False

    def make_chain(self, a: BaseFVG, b: BaseFVG, current_idx: int):
        t = min(a.lag_top, b.top)
        bot = max(a.lag_bottom, b.bottom)
        made = False
        created = False
        if bot < t:
            made = True
            if not self.merge_zone(b.direction, t, bot):
                created = True
                self.new_segment(b.direction, t, bot, self.chain_seq, b.start_idx - 1)
        return made, created

    def finish_chain(self, chain_id: int):
        for s in self.segs:
            if s.chain_id == chain_id and not s.done:
                s.done = True
                s.active = False

    def process_bar(self, df: pd.DataFrame, current_idx: int, fvg_mitig_close: bool, zone_mitig_close: bool):
        self.events = {"new": False, "flip": False, "retest": False, "mitig": False, "retested_seg": None}

        # 1. Delayed fill of base FVGs
        self.lag_mitigate(df, current_idx, fvg_mitig_close)
        self.fvgs = [f for f in self.fvgs if f.lag_top > f.lag_bottom]

        # 2. Check for new FVG
        new_fvg = None
        if current_idx >= 2:
            close_price = df.iloc[current_idx]['close']
            low_curr = df.iloc[current_idx]['low']
            high_curr = df.iloc[current_idx]['high']
            low_prev2 = df.iloc[current_idx-2]['low']
            high_prev2 = df.iloc[current_idx-2]['high']

            if low_curr > high_prev2:
                gap = low_curr - high_prev2
                if gap / close_price >= self.min_gap:
                    new_fvg = BaseFVG(1, low_curr, high_prev2, current_idx)
            elif high_curr < low_prev2:
                gap = low_prev2 - high_curr
                if gap / close_price >= self.min_gap:
                    new_fvg = BaseFVG(-1, low_prev2, high_curr, current_idx)

        # 3. Strike processing
        if new_fvg:
            consumed = False
            # Flip opposite live zones
            for s in self.segs:
                if s.active and not s.done and s.direction == -new_fvg.direction:
                    if self.flip_segment(s, new_fvg, current_idx):
                        consumed = True
                        self.events["flip"] = True
            
            # Strike remaining opposite base FVGs
            to_remove = []
            for f in self.fvgs:
                if f.direction == -new_fvg.direction:
                    made, created = self.make_chain(f, new_fvg, current_idx)
                    if created:
                        self.events["new"] = True
                        self.chain_seq += 1
                    if made:
                        consumed = True
                        to_remove.append(f)
            
            self.fvgs = [f for f in self.fvgs if f not in to_remove]

            if not consumed:
                self.fvgs.append(new_fvg)

        # 4. Retest + Mitigation of live zones
        row = df.iloc[current_idx]
        hi_src = row['high'] if not zone_mitig_close else row['close']
        lo_src = row['low'] if not zone_mitig_close else row['close']
        high_price = row['high']
        low_price = row['low']

        for s in self.segs:
            if s.active and not s.done and s.create_idx < current_idx:
                touch = high_price >= s.bottom and low_price <= s.top
                if touch and not s.touching:
                    self.events["retest"] = True
                    self.events["retested_seg"] = s
                    s.retest_count += 1
                s.touching = touch

                mitigated = lo_src <= s.bottom if s.direction == 1 else hi_src >= s.top
                if mitigated:
                    self.events["mitig"] = True
                    self.finish_chain(s.chain_id)

        # Clean up segments if they exceed some max count (for performance)
        if len(self.segs) > 100:
            active_segs = [s for s in self.segs if s.active]
            self.segs = active_segs[-50:]


class StrategyEngine:
    def __init__(self, config):
        self.config = config
        # Bug #2 FIX: Accept either full config or strategy_params sub-dict
        sp = config.get("strategy_params", config)  # works with both full config and sub-dict
        # Bug #1 FIX: fvg_min_gap_percent is already a decimal fraction (e.g. 0.002 = 0.2%), do NOT divide by 100
        self.fvg_min_gap = sp.get("fvg_min_gap_percent", 0.002)
        self.vp_lookback  = sp.get("volume_profile_lookback", 200)
        self.swing_length  = sp.get("swing_length", 10)
        self.atr_multiplier = sp.get("max_atr_multiplier", 3.5)
        # Bug #4 FIX: POC proximity factor — POC must be within N * zone_width of zone centre
        # (replaces strict exact-overlap check that caused 0 trades)
        self.poc_proximity_factor = sp.get("poc_proximity_factor", 3.0)
        self.fvg_mitig_close = True
        self.zone_mitig_close = True
        
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return 0.0
        
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean().iloc[-1]
        
        if pd.isna(atr):
            return 0.0
        return float(atr)
        
    def find_swing_extremes(self, df: pd.DataFrame, current_idx: int) -> tuple:
        start_idx = max(0, current_idx - self.swing_length)
        subset = df.iloc[start_idx:current_idx+1]
        
        lowest_low = subset['low'].min()
        highest_high = subset['high'].max()
        
        return lowest_low, highest_high

    def calculate_poc(self, df: pd.DataFrame, start_idx: int, end_idx: int, rows: int = 30) -> float:
        if start_idx >= end_idx or start_idx < 0:
            return 0.0
        
        subset = df.iloc[start_idx:end_idx]
        max_price = subset['high'].max()
        min_price = subset['low'].min()
        
        if max_price == min_price:
            return max_price
            
        step = (max_price - min_price) / rows
        if step == 0:
            return max_price
            
        profile = {i: 0.0 for i in range(rows)}
        
        for _, row in subset.iterrows():
            vol = row['tick_volume']
            high = row['high']
            low = row['low']
            
            for i in range(rows):
                bin_top = max_price - (i * step)
                bin_bot = bin_top - step
                
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
        """Runs full analysis and returns a signal if Retest + POC proximity filter meet."""
        if len(df) < self.vp_lookback:
            logger.debug(f"Not enough bars ({len(df)}) for vp_lookback={self.vp_lookback}. Skipping.")
            return {"signal": 0}
            
        tracker = CrossfireTracker(self.fvg_min_gap)
        
        for i in range(len(df)):
            tracker.process_bar(df, i, self.fvg_mitig_close, self.zone_mitig_close)
            
        # Inspect events of the VERY LAST bar
        last_events = tracker.events
        retested_seg = last_events.get("retested_seg")

        logger.debug(
            f"Last bar events — retest={last_events['retest']}, flip={last_events['flip']}, "
            f"new={last_events['new']}, mitig={last_events['mitig']}, "
            f"active_segs={sum(1 for s in tracker.segs if s.active)}, "
            f"base_fvgs={len(tracker.fvgs)}"
        )
        
        if last_events["retest"] and retested_seg:
            # Filter: Calculate Volume Profile POC over last vp_lookback bars
            poc_price = self.calculate_poc(df, len(df) - self.vp_lookback, len(df))
            
            # Bug #4 FIX: Proximity filter instead of exact overlap.
            # Old code: retested_seg.bottom <= poc_price <= retested_seg.top  ← near-impossible
            # New code: POC must be within poc_proximity_factor * zone_width of zone centre
            zone_width  = retested_seg.top - retested_seg.bottom
            zone_centre = (retested_seg.top + retested_seg.bottom) / 2.0
            max_distance = zone_width * self.poc_proximity_factor

            poc_near_zone = abs(poc_price - zone_centre) <= max_distance

            logger.debug(
                f"Retest detected on {'Bull' if retested_seg.direction == 1 else 'Bear'} zone "
                f"{retested_seg.bottom:.5f}-{retested_seg.top:.5f} | "
                f"POC={poc_price:.5f} | zone_centre={zone_centre:.5f} | "
                f"distance={abs(poc_price - zone_centre):.5f} | max_allowed={max_distance:.5f} | "
                f"poc_near_zone={poc_near_zone}"
            )

            if poc_near_zone:
                # Calculate Anti-Stop-Hunt variables
                atr = self.calculate_atr(df)
                atr_buffer = atr * self.atr_multiplier if atr > 0 else 0.0
                ll, hh = self.find_swing_extremes(df, len(df) - 1)
                
                if retested_seg.direction == 1:
                    # Bullish: SL is at the lowest of (Zone Bottom, Swing Low) minus ATR buffer
                    base_sl = min(retested_seg.bottom, ll)
                    safe_sl = base_sl - atr_buffer
                    logger.info(
                        f"✅ Bullish Crossfire Retest + POC Confluence! "
                        f"POC={poc_price:.5f} near Zone {retested_seg.bottom:.5f}-{retested_seg.top:.5f}. "
                        f"Safe SL={safe_sl:.5f}"
                    )
                    return {"signal": 1, "poc": poc_price, "sl": safe_sl}
                    
                elif retested_seg.direction == -1:
                    # Bearish: SL is at the highest of (Zone Top, Swing High) plus ATR buffer
                    base_sl = max(retested_seg.top, hh)
                    safe_sl = base_sl + atr_buffer
                    logger.info(
                        f"✅ Bearish Crossfire Retest + POC Confluence! "
                        f"POC={poc_price:.5f} near Zone {retested_seg.bottom:.5f}-{retested_seg.top:.5f}. "
                        f"Safe SL={safe_sl:.5f}"
                    )
                    return {"signal": -1, "poc": poc_price, "sl": safe_sl}

        return {"signal": 0}
