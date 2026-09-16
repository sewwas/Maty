"""
test_smc_logic.py — Unit Verification for Bot #4 SMC Liquidity Hunter Engine
"""

import os
import sys

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import pandas as pd
import numpy as np
import datetime

# Point to bot4_smc
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot4_smc"))

from smc_engine import SMCEngine
from analytics import calculate_performance_metrics


def test_smc_liquidity_and_fvg():
    print("================================================================")
    print("      RUNNING UNIT TESTS: BOT #4 SMC LIQUIDITY HUNTER          ")
    print("================================================================")

    engine = SMCEngine()

    # 1. Test Synthetic Candle Data Generation
    # Create 35 candles of M15 data with an Asian Session range and previous day
    base_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    m15_rows = []
    p = 2900.0
    for i in range(50):
        t = base_time + datetime.timedelta(minutes=15 * i)
        high = p + 2.0
        low = p - 2.0
        close = p + 0.5
        m15_rows.append({
            "timestamp": t,
            "open": p,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0
        })
        p = close

    df_m15 = pd.DataFrame(m15_rows)
    df_m5 = df_m15.copy()

    # 2. Test Liquidity Pool Identification
    pools = engine._identify_liquidity_pools(df_m15, df_m5)
    assert isinstance(pools, dict), "Liquidity pools must be a dict"
    assert "pdh" in pools and "pdl" in pools, "Must include PDH/PDL"
    assert "swing_highs" in pools and "swing_lows" in pools, "Must include swing fractal levels"
    print(f"✅ Liquidity Pool Detection Passed: PDH={pools.get('pdh')}, PDL={pools.get('pdl')}, Swings={len(pools.get('swing_highs', []))}")

    # 3. Test Liquidity Sweep (Turtle Soup) Rejection Wick Math
    # Bearish Sweep: price spikes above 2910.0 to 2912.0, wicks down, closes at 2907.0
    sweep_candle = pd.Series({
        "timestamp": datetime.datetime.now(datetime.timezone.utc),
        "open": 2908.0,
        "high": 2912.0,   # Wick extreme
        "low": 2906.5,
        "close": 2907.0,  # Closes back below level
        "volume": 250.0
    })
    test_pools = {
        "pdh": 2910.0,
        "pdl": 2880.0,
        "asian_high": 2905.0,
        "asian_low": 2890.0,
        "swing_highs": [2910.0],
        "swing_lows": [2885.0],
        "eqh": [],
        "eql": []
    }

    sweep = engine._check_liquidity_sweep(sweep_candle, test_pools, min_wick_ratio=0.38)
    assert sweep is not None, "Should detect bearish liquidity sweep of PDH"
    assert sweep["direction"] == "BEARISH_SWEEP", "Direction must be BEARISH_SWEEP"
    assert sweep["sweep_extreme"] == 2912.0, "Sweep extreme must match candle high"
    assert sweep["wick_ratio"] >= 0.38, f"Wick ratio {sweep['wick_ratio']} must be >= 0.38"
    print(f"✅ Bearish Liquidity Sweep Detection Passed: Extreme={sweep['sweep_extreme']} | Wick Ratio={sweep['wick_ratio'] * 100:.1f}%")

    # Bullish Sweep: price spikes below 2880.0 to 2875.0, wicks up, closes at 2882.0
    bull_candle = pd.Series({
        "timestamp": datetime.datetime.now(datetime.timezone.utc),
        "open": 2881.0,
        "high": 2884.0,
        "low": 2875.0,   # Wick extreme
        "close": 2882.5, # Closes back above level
        "volume": 300.0
    })
    bull_sweep = engine._check_liquidity_sweep(bull_candle, test_pools, min_wick_ratio=0.38)
    assert bull_sweep is not None, "Should detect bullish liquidity sweep of PDL"
    assert bull_sweep["direction"] == "BULLISH_SWEEP", "Direction must be BULLISH_SWEEP"
    assert bull_sweep["sweep_extreme"] == 2875.0, "Sweep extreme must match candle low"
    print(f"✅ Bullish Liquidity Sweep Detection Passed: Extreme={bull_sweep['sweep_extreme']} | Wick Ratio={bull_sweep['wick_ratio'] * 100:.1f}%")

    # 4. Test Fair Value Gap (FVG) Detection
    # 3-candle sequence with a clean Bearish FVG:
    # Candle 1: High = 2910, Low = 2905
    # Candle 2 (Displacement): High = 2906, Low = 2895
    # Candle 3: High = 2898, Low = 2890
    # Bearish Gap between Candle 1 Low (2905) and Candle 3 High (2898) = 7.0 pips ($7)
    fvg_df = pd.DataFrame([
        {"timestamp": base_time + datetime.timedelta(minutes=5), "open": 2908, "high": 2910, "low": 2905, "close": 2906, "volume": 100},
        {"timestamp": base_time + datetime.timedelta(minutes=10), "open": 2906, "high": 2906, "low": 2895, "close": 2896, "volume": 500},
        {"timestamp": base_time + datetime.timedelta(minutes=15), "open": 2896, "high": 2898, "low": 2890, "close": 2892, "volume": 200},
        {"timestamp": base_time + datetime.timedelta(minutes=20), "open": 2892, "high": 2894, "low": 2889, "close": 2891, "volume": 150},
    ])
    fvgs = engine._detect_fvgs(fvg_df, min_pips=3.5)
    assert len(fvgs) >= 1, "Must detect at least 1 FVG"
    fvg = fvgs[0]
    assert fvg["type"] == "BEARISH_FVG", "Must be BEARISH_FVG"
    assert fvg["top"] == 2905.0, f"FVG top should be 2905.0, got {fvg['top']}"
    assert fvg["bottom"] == 2898.0, f"FVG bottom should be 2898.0, got {fvg['bottom']}"
    assert fvg["midpoint"] == 2901.5, f"FVG midpoint should be 2901.5, got {fvg['midpoint']}"
    print(f"✅ Fair Value Gap (FVG) Detection Passed: {fvg['type']} Zone [{fvg['bottom']} - {fvg['top']}] | Midpoint (50% CE) = {fvg['midpoint']}")

    # 5. Test Lot Sizing (1% risk)
    lot = engine._calculate_lot_size(equity=1000.0, sl_distance=2.0)
    # $1000 * 1% = $10 risk. Distance = $2.0. 10 / (2.0 * 100) = 0.05 lot
    assert lot == 0.05, f"Expected 0.05 lot, got {lot}"
    print(f"✅ Dynamic Lot Sizing Passed: 1.0% Equity Risk ($10) on $2.00 SL Distance -> {lot} Lots")

    # 6. Test Analytics Engine
    sample_trades = [
        {"pnl": 35.0, "rr": 3.5},
        {"pnl": 15.0, "rr": 1.5},
        {"pnl": -10.0, "rr": 0.0},
        {"pnl": 40.0, "rr": 4.0}
    ]
    perf = calculate_performance_metrics(sample_trades)
    assert perf["total_trades"] == 4
    assert perf["wins"] == 3
    assert perf["win_rate"] == 75.0
    assert perf["net_profit"] == 80.0
    assert perf["profit_factor"] == 9.0
    print(f"✅ Analytics Metrics Passed: Win Rate={perf['win_rate']}% | Profit Factor={perf['profit_factor']} | Net Profit=${perf['net_profit']}")

    # 7. Test Data-Driven Dynamic Stop Loss Calculation
    # Bearish Sweep: sweep extreme at 2915.0, entry at 2913.0, ATR=2.0, Spread=0.20
    sl_price, sl_dist, sl_info = engine._calculate_dynamic_sl(
        direction="BEARISH_SWEEP",
        sweep_extreme=2915.0,
        entry_price=2913.0,
        atr=2.0,
        spread=0.20
    )
    # Expected: buffer = max(0.20 * 1.5, 2.0 * 0.30) = max(0.30, 0.60) = 0.60
    # raw_sl = 2915.0 + 0.60 = 2915.60
    # min_sl_dist = max(1.60, 0.60, 1.00) = 1.60. raw_dist = 2.60 >= 1.60 -> sl_price = 2915.60
    assert sl_price > 2915.0, "SL must be above sweep extreme for SELL"
    assert sl_info["vol_buffer"] == 0.60, f"Expected 0.60 buffer, got {sl_info['vol_buffer']}"
    assert sl_price == 2915.60, f"Expected 2915.60, got {sl_price}"
    print(f"✅ Dynamic Stop Loss Passed (SELL): Extreme=2915.0 | ATR Buffer={sl_info['vol_buffer']} -> SL={sl_price} (Dist={sl_dist})")

    # Bullish Sweep: sweep extreme at 2885.0, entry at 2887.0, ATR=2.5, Spread=0.30
    sl_b_price, sl_b_dist, sl_b_info = engine._calculate_dynamic_sl(
        direction="BULLISH_SWEEP",
        sweep_extreme=2885.0,
        entry_price=2887.0,
        atr=2.5,
        spread=0.30
    )
    # buffer = max(0.45, 0.75) = 0.75 -> SL = 2885.0 - 0.75 = 2884.25
    assert sl_b_price < 2885.0, "SL must be below sweep extreme for BUY"
    assert sl_b_price == 2884.25, f"Expected 2884.25, got {sl_b_price}"
    print(f"✅ Dynamic Stop Loss Passed (BUY): Extreme=2885.0 | ATR Buffer={sl_b_info['vol_buffer']} -> SL={sl_b_price} (Dist={sl_b_dist})")

    # 8. Test Data-Driven Dynamic Take Profit (Opposing Liquidity Pool Targeting)
    # SELL Trade at 2910.0, SL Distance = 2.0 (SL at 2912.0)
    # Opposing Pools contain Asian Low at 2902.0 (Distance = 8.0 -> Implied R:R = 4.0)
    # Target should be 2902.0 + front_run (0.25) = 2902.25
    test_pools_tp = {
        "asian_low": 2902.0,
        "pdl": 2895.0,
        "asian_high": 2918.0,
        "pdh": 2925.0,
        "swing_highs": [2920.0],
        "swing_lows": [2905.0],
        "eqh": [],
        "eql": []
    }
    tp_price, tp_rr, tp_info = engine._calculate_dynamic_tp(
        direction="BEARISH_SWEEP",
        entry_price=2910.0,
        sl_distance=2.0,
        pools=test_pools_tp,
        atr=2.0
    )
    # Swing low is at 2905.0 (gain = 2910 - 2905.25 = 4.75 -> R:R = 2.38 >= 1.8)
    # Nearest opposing pool below entry with R:R >= 1.8 is SWING_LOW @ 2905.0 -> TP = 2905.25
    assert tp_price < 2910.0, "Take profit must be below entry for SELL"
    assert tp_rr >= 1.8, f"Implied R:R must be >= 1.8, got {tp_rr}"
    assert "2905.00" in tp_info["target_name"], f"Expected target to reference 2905.00, got {tp_info['target_name']}"
    print(f"✅ Dynamic Take Profit Passed (SELL Opposing Pool): Target={tp_info['target_name']} | TP={tp_price} | Implied R:R={tp_rr}")

    # BUY Trade at 2890.0, SL Distance = 2.0 (SL at 2888.0)
    # Targets upward liquidity: nearest is Asian High at 2918.0 (clamped to max_rr 5.0 = 2900.0) or PDH
    tp_b_price, tp_b_rr, tp_b_info = engine._calculate_dynamic_tp(
        direction="BULLISH_SWEEP",
        entry_price=2890.0,
        sl_distance=2.0,
        pools=test_pools_tp,
        atr=2.0
    )
    assert tp_b_price > 2890.0, "Take profit must be above entry for BUY"
    assert tp_b_rr >= 1.8, f"Implied R:R must be >= 1.8, got {tp_b_rr}"
    print(f"✅ Dynamic Take Profit Passed (BUY Opposing Pool): Target={tp_b_info['target_name']} | TP={tp_b_price} | Implied R:R={tp_b_rr}")

    # 9. Test Fallback when No Opposing Pools Exist
    empty_pools = {"asian_low": 0.0, "pdl": 0.0, "asian_high": 0.0, "pdh": 0.0, "swing_highs": [], "swing_lows": []}
    tp_fb_price, tp_fb_rr, tp_fb_info = engine._calculate_dynamic_tp(
        direction="BEARISH_SWEEP",
        entry_price=2910.0,
        sl_distance=2.0,
        pools=empty_pools,
        atr=2.0
    )
    # Expected fallback to 3.5 R:R: 2910 - (2.0 * 3.5) = 2903.0
    assert tp_fb_price == 2903.0, f"Expected 2903.0, got {tp_fb_price}"
    assert "DYNAMIC_RR" in tp_fb_info["target_name"]
    print(f"✅ Dynamic TP Graceful Fallback Passed: Target={tp_fb_info['target_name']} | TP={tp_fb_price} | R:R={tp_fb_rr}")

    print("\n================================================================")
    print("      ALL UNIT TESTS PASSED FOR BOT #4 SMC HUNTER! 🚀          ")
    print("================================================================")


if __name__ == "__main__":
    test_smc_liquidity_and_fvg()

