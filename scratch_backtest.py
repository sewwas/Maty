import os
import sys
import time
import datetime
import MetaTrader5 as mt5

if not mt5.initialize():
    print("MT5 initialization failed:", mt5.last_error())
    sys.exit(1)

from core.mt5_broker import MT5Broker
from core.engine import BreakoutGridBot, Order, Position

print("=" * 70)
print("     MATY BOT MULTI-SYMBOL QUANTITATIVE BACKTEST ENGINE")
print("=" * 70)

# Backtest Simulation Harness Broker
class BacktestBroker:
    def __init__(self, initial_balance=4800.0, symbol="XAUUSD"):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.balance_usd = initial_balance
        self.account_equity = initial_balance
        self.is_cent_account = False
        self.pending_orders = {}
        self.open_positions = {}
        self.closed_trades = []
        self.realized_pnl = 0.0
        self.last_ask = 0.0
        self.last_bid = 0.0
        self.magic_number = 8888

    def ensure_connected(self):
        return True

    def get_min_stop_distance(self):
        return 2.50 if "XAU" in self.symbol.upper() else 0.05

    def place_order(self, order_type: str, price: float, size: float, timestamp: float, tp: float = 0.0, sl: float = 0.0):
        order_id = f"ord_{len(self.pending_orders)+1}_{int(timestamp)}"
        order = Order(type=order_type, trigger_price=price, size=size, timestamp=timestamp)
        order.order_id = order_id
        order.tp = tp
        order.sl = sl
        self.pending_orders[order_id] = order
        return order

    def cancel_order(self, order_id: str):
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
            return True
        return False

    def cancel_all_orders(self):
        cnt = len(self.pending_orders)
        self.pending_orders.clear()
        return cnt

    def close_position(self, position_id: str, exit_price: float, timestamp: float):
        if position_id in self.open_positions:
            pos = self.open_positions[position_id]
            pnl = pos.get_pnl(exit_price)
            self.realized_pnl += pnl
            self.balance_usd += pnl
            record = {
                "position_id": position_id,
                "type": pos.type,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "size": pos.size,
                "pnl": pnl,
                "entry_time": pos.entry_time,
                "exit_time": timestamp
            }
            self.closed_trades.append(record)
            del self.open_positions[position_id]
            return record
        return None

    def close_all_positions(self, exit_price: float, timestamp: float):
        closed = []
        for pid in list(self.open_positions.keys()):
            res = self.close_position(pid, exit_price, timestamp)
            if res:
                closed.append(res)
        return closed

    def get_floating_pnl(self, current_price: float) -> float:
        return sum(pos.get_pnl(current_price) for pos in self.open_positions.values())

    def update_tick(self, ask: float, bid: float, timestamp: float):
        self.last_ask = ask
        self.last_bid = bid
        triggered = []
        
        # Check pending order activations
        for oid, o in list(self.pending_orders.items()):
            if o.type == "BUY_STOP" and ask >= o.trigger_price:
                pid = f"pos_{len(self.open_positions)+1}_{int(timestamp)}"
                pos = Position(type="BUY", entry_price=o.trigger_price, size=o.size, entry_time=timestamp)
                pos.position_id = pid
                pos.tp = getattr(o, 'tp', 0.0)
                pos.sl = getattr(o, 'sl', 0.0)
                self.open_positions[pid] = pos
                del self.pending_orders[oid]
                triggered.append(pos)
            elif o.type == "SELL_STOP" and bid <= o.trigger_price:
                pid = f"pos_{len(self.open_positions)+1}_{int(timestamp)}"
                pos = Position(type="SELL", entry_price=o.trigger_price, size=o.size, entry_time=timestamp)
                pos.position_id = pid
                pos.tp = getattr(o, 'tp', 0.0)
                pos.sl = getattr(o, 'sl', 0.0)
                self.open_positions[pid] = pos
                del self.pending_orders[oid]
                triggered.append(pos)

        # Check Hardware Broker TPs
        for pid, pos in list(self.open_positions.items()):
            tp_px = getattr(pos, 'tp', 0.0)
            if pos.type == "BUY" and tp_px > 0 and ask >= tp_px:
                self.close_position(pid, tp_px, timestamp)
            elif pos.type == "SELL" and tp_px > 0 and bid <= tp_px:
                self.close_position(pid, tp_px, timestamp)

        float_pnl = self.get_floating_pnl(ask)
        self.account_equity = self.balance_usd + float_pnl
        return triggered

    def process_tick(self, prev_px: float, cur_px: float, ts: float):
        spread = 0.20 if "XAU" in self.symbol.upper() else 0.50
        ask = cur_px + spread
        bid = cur_px
        return self.update_tick(ask, bid, ts)


def run_backtest_for_symbol(target_sym: str, num_bars: int = 5000):
    sym_info = mt5.symbol_info(target_sym)
    if not sym_info:
        for suffix in ["c", "m", "USDT"]:
            sym_info = mt5.symbol_info(target_sym + suffix)
            if sym_info: break
    
    if not sym_info:
        print(f"Symbol {target_sym} not available.")
        return

    rates = mt5.copy_rates_from_pos(sym_info.name, mt5.TIMEFRAME_M1, 0, num_bars)
    if rates is None or len(rates) == 0:
        print(f"No rates found for {sym_info.name}.")
        return

    broker = BacktestBroker(initial_balance=4800.0, symbol=sym_info.name)
    bot = BreakoutGridBot(
        broker=broker,
        symbol=sym_info.name,
        grid_levels=5,
        grid_gap=3.0 if "XAU" in sym_info.name.upper() else 10.0,
        trap_offset=3.0,
        order_size=0.01,
        order_size_multiplier=1.20,
        target_profit=6.50,
        auto_restart=True,
        use_breakeven=True,
        breakeven_trigger=0.50
    )

    prev_px = rates[0]['close']
    max_dd = 0.0
    cycles = 0

    for r in rates:
        ts = float(r['time'])
        h_px = float(r['high'])
        l_px = float(r['low'])
        c_px = float(r['close'])
        
        for px in [h_px, l_px, c_px]:
            broker.update_tick(px + 0.20, px, ts)
            fpnl = broker.get_floating_pnl(px)
            if fpnl < max_dd: max_dd = fpnl
            res = bot.process_tick(prev_px, px, ts)
            if res: cycles += 1
            prev_px = px

    winning_trades = [t for t in broker.closed_trades if t['pnl'] > 0]
    win_rate = (len(winning_trades) / len(broker.closed_trades) * 100.0) if broker.closed_trades else 100.0

    print(f"\n--- BACKTEST RESULTS: {sym_info.name} ({len(rates)} M1 Bars) ---")
    print(f"Data Range          : {datetime.datetime.fromtimestamp(rates[0]['time'])} to {datetime.datetime.fromtimestamp(rates[-1]['time'])}")
    print(f"Initial Balance     : ${broker.initial_balance:.2f} USD")
    print(f"Final Balance       : ${broker.balance_usd:.2f} USD")
    print(f"Net Realized Profit : +${broker.realized_pnl:.2f} USD (+{(broker.realized_pnl / broker.initial_balance * 100.0):.2f}%)")
    print(f"Total Closed Trades : {len(broker.closed_trades)}")
    print(f"Win Rate            : {win_rate:.2f}%")
    print(f"Max Drawdown        : -${abs(max_dd):.2f} USD ({abs(max_dd)/broker.initial_balance*100.0:.2f}%)")

run_backtest_for_symbol("XAUUSD", 5000)
run_backtest_for_symbol("BTCUSD", 5000)
print("\n" + "=" * 70)
