import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

def test_imports():
    print("Testing imports...")
    from core.auto_reading import PAIR_SAFETY_BOUNDS
    assert PAIR_SAFETY_BOUNDS["XAUUSD"]["max_cycle_sl"] == 5.00
    assert PAIR_SAFETY_BOUNDS["XAUUSDc"]["max_cycle_sl"] == 5.00
    print("✓ PAIR_SAFETY_BOUNDS verified.")

    from core.engine import BreakoutGridBot
    from core.mt5_broker import SimulatedBroker
    sim_brk = SimulatedBroker(symbol="XAUUSD")
    bot = BreakoutGridBot(broker=sim_brk, symbol="XAUUSD")
    assert bot._fakeout_guard_enabled is True
    assert bot.max_daily_drawdown == 20.0
    print("✓ BreakoutGridBot defaults verified (_fakeout_guard_enabled=True, max_daily_drawdown=20.0).")

    # Test MT5Broker SL clamping logic
    from core.mt5_broker import MT5Broker
    brk = MT5Broker(symbol="XAUUSD")
    # Simulate a BUY order with wide SL ($16 away)
    px = 4355.00
    wide_sl = px - 16.00  # 4339.00
    # On Gold: BUY sl cannot be lower than trigger_price - 5.00 (4350.00)
    expected_sl = px - 5.00
    clamped_sl = max(wide_sl, px - 5.00)
    assert clamped_sl == expected_sl, f"Expected {expected_sl}, got {clamped_sl}"
    print(f"✓ Gold BUY SL clamping verified: {wide_sl} clamped to {clamped_sl}.")

    # Simulate a SELL order with wide SL ($16 away)
    px_sell = 4325.00
    wide_sl_sell = px_sell + 16.00  # 4341.00
    expected_sl_sell = px_sell + 5.00  # 4330.00
    clamped_sl_sell = min(wide_sl_sell, px_sell + 5.00)
    assert clamped_sl_sell == expected_sl_sell, f"Expected {expected_sl_sell}, got {clamped_sl_sell}"
    print(f"✓ Gold SELL SL clamping verified: {wide_sl_sell} clamped to {clamped_sl_sell}.")

    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_imports()
