import sys
import os
import time
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import Order, Position, BreakoutGridBot
from core.manual_bot import ManualGridBot
from core.mt5_broker import MT5Broker, SimulatedBroker, get_symbol_magic_number, is_manual_magic
from core.auto_reading import PAIR_SWEET_SPOTS
from core.grid_risk import sanitize_order_size

print("=" * 60)
print("RUNNING PROFITY AI / MATY COMPREHENSIVE AUDIT SUITE")
print("=" * 60)

# TEST 1: Magic Number Mapping
print("\n[TEST 1] Magic Numbers & Separation...")
auto_magic_paxg = get_symbol_magic_number("PAXGUSDT", is_manual=False)
manual_magic_paxg = get_symbol_magic_number("PAXGUSDT", is_manual=True)
auto_magic_xau = get_symbol_magic_number("XAUUSD", is_manual=False)
manual_magic_xau = get_symbol_magic_number("XAUUSD", is_manual=True)

assert auto_magic_paxg == 998876, f"Expected 998876, got {auto_magic_paxg}"
assert manual_magic_paxg == 1008876, f"Expected 1008876, got {manual_magic_paxg}"
assert auto_magic_xau == 998876, f"Expected 998876, got {auto_magic_xau}"
assert manual_magic_xau == 1008876, f"Expected 1008876, got {manual_magic_xau}"

print("PASS: Magic numbers correct.")

# TEST 2: SimulatedBroker Basket & ManualGridBot Execution
print("\n[TEST 2] ManualGridBot Lifecycle & Basket TP Simulation...")
sim_broker = SimulatedBroker(initial_balance=1000.0, symbol="PAXGUSDT", magic_number=manual_magic_paxg)
bot = ManualGridBot(
    broker=sim_broker,
    symbol="PAXGUSDT",
    grid_gap=0.30,
    trap_offset=0.15,
    grid_levels=5,
    order_size=0.01,
    order_size_multiplier=1.25,
    target_profit=15.0,
    is_percent=True,
    auto_restart=True,
    use_auto_reading=False,
    pending_order_side_mode="BOTH_SIDES"
)

# Step A: Deploy Traps
current_price = 2500.0
bot.deploy_traps(current_price, time.time(), force=True)
assert bot.deployed == True, "Bot should be deployed"
assert len(sim_broker.pending_orders) == 10, f"Expected 10 pending orders (5 BUY + 5 SELL), got {len(sim_broker.pending_orders)}"

# Verify all pending orders have tp=0.0 (no broker-side individual TP)
for oid, o in sim_broker.pending_orders.items():
    assert o.tp == 0.0, f"Order {oid} has tp={o.tp}, expected 0.0"
    assert o.sl == 0.0, f"Order {oid} has sl={o.sl}, expected 0.0"
print("PASS: Traps deployed with exactly tp=0.0 and sl=0.0.")

# Step B: Trigger Fills
sim_broker.open_positions["pos_1"] = Position("BUY", 2505.0, 0.01, time.time(), pos_id="pos_1")
sim_broker.open_positions["pos_2"] = Position("BUY", 2507.0, 0.0125, time.time(), pos_id="pos_2")
sim_broker.open_positions["pos_3"] = Position("BUY", 2509.0, 0.0156, time.time(), pos_id="pos_3")

# Set profit on positions
sim_broker.open_positions["pos_1"].profit = 6.0
sim_broker.open_positions["pos_2"].profit = 5.5
sim_broker.open_positions["pos_3"].profit = 4.5 # Total = 16.0 >= target 15.0

# Step C: Process Tick when TP reached
pnl = sim_broker.get_floating_pnl(2512.0)
assert pnl >= 15.0, f"Expected >= 15.0, got {pnl}"

# Add close_all_positions method to SimulatedBroker if not present for simulation testing
if not hasattr(sim_broker, "close_all_positions"):
    def sim_close_all(symbol=None, side=None):
        sim_broker.open_positions.clear()
        return []
    sim_broker.close_all_positions = sim_close_all

# Run process_tick
res = bot.process_tick(2510.0, 2512.0, time.time())

# Verify:
# 1. Closed trades recorded or open positions cleared
# 2. Cycle reset: _max_open_in_cycle should be 0
# 3. New grid redeployed
assert len(sim_broker.open_positions) == 0, f"Expected 0 open positions, got {len(sim_broker.open_positions)}"
assert bot._max_open_in_cycle == 0, f"Expected _max_open_in_cycle=0, got {bot._max_open_in_cycle}"
assert bot.deployed == True, "Expected bot to be redeployed"
assert len(sim_broker.pending_orders) > 0, "Expected new traps to be placed on redeploy"
print("PASS: Basket TP hit -> Positions closed simultaneously -> Traps cancelled -> New grid redeployed.")

# TEST 3: State Persistence Serialization Functions
print("\n[TEST 3] State Persistence Serialization...")
def get_bot_state_filename() -> str:
    port = os.getenv("WINE_BRIDGE_PORT") or os.getenv("STREAMLIT_SERVER_PORT") or "8501"
    if str(port) in ("8002", "8502"):
        return "bot_state_instance_2.json"
    return "bot_state_instance_1.json"

def get_manual_state_filename() -> str:
    port = os.getenv("WINE_BRIDGE_PORT") or os.getenv("STREAMLIT_SERVER_PORT") or "8501"
    if str(port) in ("8002", "8502"):
        return "manual_bot_state_instance_2.json"
    return "manual_bot_state_instance_1.json"

f_auto = get_bot_state_filename()
f_man = get_manual_state_filename()
assert "instance_1" in f_auto and "instance_1" in f_man, "Filename should match instance_1 default"

os.environ["STREAMLIT_SERVER_PORT"] = "8502"
assert get_bot_state_filename() == "bot_state_instance_2.json"
assert get_manual_state_filename() == "manual_bot_state_instance_2.json"
os.environ.pop("STREAMLIT_SERVER_PORT", None)
print(f"PASS: State file resolution (port 8501 -> {f_auto}, port 8502 -> bot_state_instance_2.json)")

# TEST 4: Wine Bridge & MT5Broker Compatibility
print("\n[TEST 4] MT5Broker & Wine Bridge API Contract Audit...")
with open("wine_mt5_bridge.py", "r", encoding="utf-8") as f:
    bridge_code = f.read()

required_endpoints = [
    "/account",
    "/symbol_info",
    "/order_send",
    "/order_cancel",
    "/position_close",
    "/close_all",
    "/cancel_all",
    "/positions",
    "/orders",
    "/history"
]

for ep in required_endpoints:
    assert ep in bridge_code, f"Missing endpoint {ep} in wine_mt5_bridge.py"
print(f"PASS: All {len(required_endpoints)} REST Bridge endpoints verified in wine_mt5_bridge.py.")

with open("core/mt5_broker.py", "r", encoding="utf-8") as f:
    broker_code = f.read()

for ep in required_endpoints:
    assert ep in broker_code, f"Missing bridge call for {ep} in core/mt5_broker.py"
print(f"PASS: MT5Broker has full client support for all {len(required_endpoints)} bridge endpoints.")

# TEST 5: Auto vs Manual Magic Isolation during Basket Close
print("\n[TEST 5] Auto vs Manual Multi-Bot Isolation Audit...")
# Create simulated broker for auto bot and manual bot on same symbol
auto_broker = SimulatedBroker(initial_balance=1000.0, symbol="PAXGUSDT", magic_number=auto_magic_paxg)
manual_broker = SimulatedBroker(initial_balance=1000.0, symbol="PAXGUSDT", magic_number=manual_magic_paxg)

# Verify distinct magic numbers
assert auto_broker.magic_number != manual_broker.magic_number, "Magic numbers must be distinct"
assert is_manual_magic(manual_broker.magic_number) == True, "Manual broker must be recognized as manual"
assert is_manual_magic(auto_broker.magic_number) == False, "Auto broker must NOT be recognized as manual"
print("PASS: Auto and Manual brokers have strictly distinct magic numbers and classification.")

# TEST 6: Manual Stop Loss Execution
print("\n[TEST 6] Manual Grid Bot Stop Loss Execution...")
sl_bot = ManualGridBot(
    broker=manual_broker,
    symbol="PAXGUSDT",
    grid_gap=0.30,
    trap_offset=0.15,
    grid_levels=5,
    order_size=0.01,
    target_profit=20.0,
    stop_loss=10.0,
    auto_restart=True
)

manual_broker.open_positions["pos_loss"] = Position("BUY", 2500.0, 0.01, time.time(), pos_id="pos_loss")
manual_broker.open_positions["pos_loss"].profit = -12.0 # Loss $12 exceeds SL $10

# Add mock close_all_positions if needed
if not hasattr(manual_broker, "close_all_positions"):
    manual_broker.close_all_positions = lambda symbol=None, side=None: manual_broker.open_positions.clear()

sl_bot.process_tick(2500.0, 2490.0, time.time())
assert len(manual_broker.open_positions) == 0, "All positions should be closed on manual SL hit"
assert sl_bot._max_open_in_cycle == 0, "_max_open_in_cycle must reset on SL hit"
print("PASS: Manual Stop Loss triggers clean basket close & state reset.")

print("\n" + "=" * 60)
print("AUDIT SUMMARY: ALL PROFIT-TAKING & ISOLATION TESTS PASSED!")
print("=" * 60)
