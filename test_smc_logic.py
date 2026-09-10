"""
test_smc_logic.py — Unit Verification for Bot #4 SMC Liquidity Hunter Engine
"""

import os
import sys
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

    print("\n================================================================")
    print("      ALL UNIT TESTS PASSED FOR BOT #4 SMC HUNTER! 🚀          ")
    print("================================================================")


if __name__ == "__main__":
    test_smc_liquidity_and_fvg()
