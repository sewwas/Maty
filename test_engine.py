import sys
import os
# Add current directory to path to import core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.engine import SimulatedBroker, BreakoutGridBot

def run_tests():
    print("====================================")
    print("RUNNING ENGINE TESTS")
    print("====================================")
    
    # 1. Test Broker Initialization
    broker = SimulatedBroker(initial_balance=10000.0, commission_pct=0.001, slippage_pct=0.0005)
    assert broker.balance == 10000.0
    assert broker.get_equity(100.0) == 10000.0
    print("[PASS] Broker initialization")

    # 2. Test Grid Deployment
    bot = BreakoutGridBot(
        broker=broker,
        grid_levels=3,
        grid_gap=10.0,
        trap_offset=5.0,
        order_size=0.1,
        target_profit=20.0,
        auto_restart=False,
        is_percent=False
    )
    
    start_price = 1000.0
    timestamp = 1718000000.0
    bot.deploy_traps(start_price, timestamp)
    
    assert bot.deployed is True
    assert len(broker.pending_orders) == 6 # 3 buy stops, 3 sell stops
    
    # Verify trap prices
    # Buy stops: 1005, 1015, 1025
    # Sell stops: 995, 985, 975
    buy_stops = sorted([o.trigger_price for o in broker.pending_orders.values() if o.type == "BUY_STOP"])
    sell_stops = sorted([o.trigger_price for o in broker.pending_orders.values() if o.type == "SELL_STOP"], reverse=True)
    
    assert buy_stops == [1005.0, 1015.0, 1025.0]
    assert sell_stops == [995.0, 985.0, 975.0]
    print("[PASS] Grid trap price calculations and placement")

    # 3. Test Order Triggering (Tick Upwards)
    # Price rises to 1008
    bot.process_tick(start_price, 1008.0, timestamp + 10)
    
    # Buy stop at 1005 should be triggered
    assert len(broker.open_positions) == 1
    assert len(broker.pending_orders) == 5 # 5 remaining
    
    pos = list(broker.open_positions.values())[0]
    assert pos.type == "BUY"
    # Entry price with 0.05% slippage on 1005 -> 1005 * 1.0005 = 1005.5025
    assert abs(pos.entry_price - 1005.5025) < 0.0001
    
    # Commission on entry = 0.1 * 1005.5025 * 0.001 = 0.10055 USD
    # New balance = 10000 - 0.10055 = 9999.89945
    assert abs(broker.balance - 9999.89945) < 0.001
    print("[PASS] Pending order triggers and executes with commission/slippage")

    # 4. Test Target Profit Exit
    # Price climbs to 1250 (massive breakout!)
    # Buy position value = (1250 - 1005.5025) * 0.1 = 24.44975 USD
    # This exceeds target_profit = 20.0, so the bot should exit.
    
    summary = bot.process_tick(1008.0, 1250.0, timestamp + 20)
    
    assert summary is not None
    print(f"DEBUG: Summary = {summary}")
    print(f"DEBUG: Balance = {broker.balance}")
    assert summary["cycle_id"] == 1
    assert summary["trades_count"] == 3
    assert bot.deployed is False # auto_restart is False
    assert len(broker.open_positions) == 0
    assert len(broker.pending_orders) == 0
    
    # Expected balance calculation with 3 triggered trades:
    # Starting balance: 10000.0
    # Three entry commissions:
    #   Pos 1: 0.1 * 1005.5025 * 0.001 = 0.10055025
    #   Pos 2: 0.1 * 1015.5075 * 0.001 = 0.10155075
    #   Pos 3: 0.1 * 1025.5125 * 0.001 = 0.10255125
    # Exit price (after slippage): 1250 * (1 - 0.0005) = 1249.375
    # Three exit commissions: 3 * (0.1 * 1249.375 * 0.001) = 0.3748125
    # Realized trade profits (gross):
    #   Pos 1: (1249.375 - 1005.5025) * 0.1 = 24.38725
    #   Pos 2: (1249.375 - 1015.5075) * 0.1 = 23.38675
    #   Pos 3: (1249.375 - 1025.5125) * 0.1 = 22.38625
    # Net balance change = Gross Profits - Entry Comms - Exit Comms
    # = 70.16025 - 0.30465225 - 0.3748125 = 69.48078525
    # Final Balance = 10069.48078525
    assert abs(broker.balance - 10069.48078) < 0.001

    print("[PASS] Target profit exit closes positions, cancels orders, and realizes PnL")
    
    # 5. Test Percent-based Placement
    broker.reset()
    pct_bot = BreakoutGridBot(
        broker=broker,
        grid_levels=2,
        grid_gap=1.0,      # 1% gap
        trap_offset=0.5,   # 0.5% offset
        order_size=1.0,
        target_profit=50.0,
        auto_restart=True,
        is_percent=True
    )
    
    pct_bot.deploy_traps(100.0, timestamp)
    # Buy stops: 100 + 0.5% = 100.5, and 100.5 + 1% of 100 = 101.5
    # Sell stops: 100 - 0.5% = 99.5, and 99.5 - 1% of 100 = 98.5
    buy_stops_pct = sorted([o.trigger_price for o in broker.pending_orders.values() if o.type == "BUY_STOP"])
    sell_stops_pct = sorted([o.trigger_price for o in broker.pending_orders.values() if o.type == "SELL_STOP"], reverse=True)
    
    assert buy_stops_pct == [100.5, 101.5]
    assert sell_stops_pct == [99.5, 98.5]
    print("[PASS] Percent-based trap spacing and offset")
    
    # 6. Test Stop Loss Exit
    broker.reset()
    sl_bot = BreakoutGridBot(
        broker=broker, grid_levels=1, grid_gap=10.0, trap_offset=5.0, 
        order_size=1.0, target_profit=100.0, stop_loss=20.0, auto_restart=False,
        cancel_opposite_on_trigger=True
    )
    sl_bot.deploy_traps(1000.0, timestamp)
    sl_bot.process_tick(1000.0, 1006.0, timestamp + 10)
    summary_sl = sl_bot.process_tick(1006.0, 980.0, timestamp + 20)
    assert summary_sl is not None
    assert summary_sl["exit_reason"] == "STOP_LOSS"
    assert len(broker.open_positions) == 0
    print("[PASS] Global Stop Loss triggers correctly")

    # 7. Test Time-based Exit
    broker.reset()
    to_bot = BreakoutGridBot(
        broker=broker, grid_levels=1, grid_gap=10.0, trap_offset=5.0, 
        order_size=1.0, target_profit=100.0, max_cycle_duration=3600.0, auto_restart=False
    )
    to_bot.deploy_traps(1000.0, timestamp)
    to_bot.process_tick(1000.0, 1006.0, timestamp + 10)
    summary_to = to_bot.process_tick(1006.0, 1007.0, timestamp + 4000)
    assert summary_to is not None
    assert summary_to["exit_reason"] == "TIMEOUT"
    assert len(broker.open_positions) == 0
    print("[PASS] Cycle Timeout triggers correctly")

    # 8. Test OCO Trap Cancellation
    broker.reset()
    oco_bot = BreakoutGridBot(
        broker=broker, grid_levels=2, grid_gap=10.0, trap_offset=5.0, 
        order_size=1.0, target_profit=100.0, cancel_opposite_on_trigger=True, auto_restart=False
    )
    oco_bot.deploy_traps(1000.0, timestamp)
    assert len(broker.pending_orders) == 4
    oco_bot.process_tick(1000.0, 1006.0, timestamp + 10)
    assert len(broker.open_positions) == 1
    assert len(broker.pending_orders) == 1
    assert list(broker.pending_orders.values())[0].type == "BUY_STOP"
    print("[PASS] OCO (One-Cancels-Other) traps trigger correctly")

    # 9. Test Trailing Stop Exit
    broker.reset()
    ts_bot = BreakoutGridBot(
        broker=broker, grid_levels=1, grid_gap=10.0, trap_offset=5.0, 
        order_size=1.0, target_profit=1000.0, use_trailing_stop=True, trailing_stop_distance=20.0, auto_restart=False
    )
    ts_bot.deploy_traps(1000.0, timestamp)
    # Trigger buy stop at 1005. Fill price with 0.05% commission & 0.02% slippage
    ts_bot.process_tick(1000.0, 1006.0, timestamp + 10)
    # Price surges to 1206.0 (Massive PnL)
    ts_bot.process_tick(1006.0, 1206.0, timestamp + 20)
    # Price drops slightly, but not enough to trigger 20.0 distance
    res = ts_bot.process_tick(1206.0, 1196.0, timestamp + 30)
    assert res is None
    # Price drops further, triggering trailing stop!
    summary_ts = ts_bot.process_tick(1196.0, 1180.0, timestamp + 40)
    assert summary_ts is not None
    assert summary_ts["exit_reason"] == "TRAILING_STOP"
    assert summary_ts["pnl"] > 100.0  # Successfully rode the breakout
    print("[PASS] Trailing Stop Exit triggers correctly")

    # 10. Test Bollinger Band Squeeze Filter
    broker.reset()
    bb_bot = BreakoutGridBot(
        broker=broker, grid_levels=1, grid_gap=10.0, trap_offset=5.0, 
        order_size=1.0, target_profit=15.0, auto_restart=False,
        use_bb_filter=True, bb_squeeze_threshold=0.02
    )
    # Attempt to deploy with high volatility (0.05 > 0.02 threshold)
    bb_bot.deploy_traps(1000.0, timestamp, bb_width=0.05)
    assert not bb_bot.deployed
    assert len(broker.pending_orders) == 0

    # Attempt to deploy with squeezed volatility (0.01 < 0.02 threshold)
    bb_bot.deploy_traps(1000.0, timestamp, bb_width=0.01)
    assert bb_bot.deployed
    assert len(broker.pending_orders) > 0
    print("[PASS] BB Squeeze Filter blocks traps in high volatility")

    # 11. Test Martingale/Size Multiplier Progression
    broker.reset()
    m_bot = BreakoutGridBot(
        broker=broker,
        grid_levels=3,
        grid_gap=10.0,
        trap_offset=5.0,
        order_size=0.01,
        order_size_multiplier=2.0,
        auto_restart=False,
        is_percent=False
    )
    m_bot.deploy_traps(1000.0, timestamp)
    # Sizes should progress exponentially: 0.01, 0.02, 0.04
    orders = sorted(list(broker.pending_orders.values()), key=lambda o: o.trigger_price)
    buy_orders = [o for o in orders if o.type == "BUY_STOP"]
    assert abs(buy_orders[0].size - 0.01) < 0.0001
    assert abs(buy_orders[1].size - 0.02) < 0.0001
    assert abs(buy_orders[2].size - 0.04) < 0.0001
    print("[PASS] Martingale/Size Multiplier progression")

    print("\nALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
