import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")

import time
import math
import random
import datetime

print("======================================================================")
print("     MATY BOT HIGH-PRECISION INTRABAR QUANTITATIVE BACKTEST ENGINE")
print("======================================================================")

from core.engine import BreakoutGridBot, Order, Position
import core.data as cd
import pandas as pd

# High-speed in-memory klines provider for instantaneous backtesting
def mock_get_historical_klines(symbol, interval="1m", limit=30):
    curr_i = getattr(mock_get_historical_klines, "current_idx", 100)
    rates_src = getattr(mock_get_historical_klines, "all_rates", [])
    if not rates_src:
        return None
    sub = rates_src[max(0, curr_i - limit):curr_i]
    if not sub:
        sub = rates_src[:min(limit, len(rates_src))]
    df = pd.DataFrame(sub)
    if not df.empty and "time" in df.columns:
        df["timestamp"] = df["time"]
    return df

cd.get_historical_klines = mock_get_historical_klines

def mock_get_order_book_depth(symbol):
    return {"asks": [[2000.5, 1.0]], "bids": [[1999.5, 1.0]], "buy_pressure_pct": 50.0}
cd.get_order_book_depth = mock_get_order_book_depth

def mock_get_economic_calendar():
    return []
cd.get_economic_calendar = mock_get_economic_calendar

def mock_calculate_technical_indicators(symbol):
    return {"ema_trend_bias": 0.0, "rsi": 50.0, "atr_pct": 0.30, "bb_width_pct": 2.0}
cd.calculate_technical_indicators = mock_calculate_technical_indicators

def mock_detect_fvg(df): return {}
cd.detect_fvg = mock_detect_fvg

def mock_detect_liquidity_sweep(df): return {}
cd.detect_liquidity_sweep = mock_detect_liquidity_sweep

def mock_detect_order_blocks(df): return {}
cd.detect_order_blocks = mock_detect_order_blocks

def mock_calculate_smc_elliott(df): return {}
cd.calculate_smc_elliott = mock_calculate_smc_elliott
class BacktestBroker:
    def __init__(self, initial_balance=5000.0, symbol="PAXGUSDT"):
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
        sym_u = self.symbol.upper()
        if "XAU" in sym_u or "GOLD" in sym_u or "PAXG" in sym_u:
            return 0.50
        return 0.50

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

    def close_all_positions(self, exit_price: float = 0.0, timestamp: float = 0.0, symbol=None, side=None, exclude_ids=None):
        closed = []
        exclude_ids = exclude_ids or set()
        px = exit_price if exit_price > 0 else (self.last_bid if side == "BUY" else self.last_ask)
        for pid in list(self.open_positions.keys()):
            if pid in exclude_ids:
                continue
            pos = self.open_positions.get(pid)
            if pos and side and str(pos.type).upper() != str(side).upper():
                continue
            res = self.close_position(pid, px if px > 0 else getattr(pos, 'entry_price', 2000.0), timestamp)
            if res:
                closed.append(res)
        return closed

    def close_buy_positions(self, symbol=None):
        return self.close_all_positions(side="BUY")

    def close_sell_positions(self, symbol=None):
        return self.close_all_positions(side="SELL")

    def get_floating_pnl(self, current_price: float) -> float:
        total_pnl = 0.0
        for pid, pos in self.open_positions.items():
            if pid in getattr(self, "runner_ids", set()):
                continue
            total_pnl += pos.get_pnl(current_price)
        return total_pnl

    def update_tick(self, ask: float, bid: float, timestamp: float):
        self.last_ask = ask
        self.last_bid = bid
        triggered = []
        
        # Check pending order activations (LIMIT + STOP) with execution slippage simulation
        pip_unit = 0.10
        for oid, o in list(self.pending_orders.items()):
            is_triggered = False
            fill_price = o.trigger_price
            pos_type = "BUY"
            
            if o.type == "BUY_STOP" and ask >= o.trigger_price:
                slippage = random.uniform(0.0, 1.0) * pip_unit
                fill_price = o.trigger_price + slippage
                is_triggered = True
                pos_type = "BUY"
            elif o.type == "SELL_STOP" and bid <= o.trigger_price:
                slippage = random.uniform(0.0, 1.0) * pip_unit
                fill_price = o.trigger_price - slippage
                is_triggered = True
                pos_type = "SELL"
            elif o.type == "BUY_LIMIT" and ask <= o.trigger_price:
                slippage = random.uniform(0.0, 0.5) * pip_unit
                fill_price = o.trigger_price - slippage
                is_triggered = True
                pos_type = "BUY"
            elif o.type == "SELL_LIMIT" and bid >= o.trigger_price:
                slippage = random.uniform(0.0, 0.5) * pip_unit
                fill_price = o.trigger_price + slippage
                is_triggered = True
                pos_type = "SELL"
                
            if is_triggered:
                pid = f"pos_{len(self.open_positions)+1}_{int(timestamp)}"
                pos = Position(type=pos_type, entry_price=fill_price, size=o.size, entry_time=timestamp)
                pos.position_id = pid
                pos.tp = getattr(o, 'tp', 0.0)
                pos.sl = getattr(o, 'sl', 0.0)
                self.open_positions[pid] = pos
                del self.pending_orders[oid]
                triggered.append(pos)

        # Check Hardware Broker TPs & SLs
        for pid, pos in list(self.open_positions.items()):
            tp_px = getattr(pos, 'tp', 0.0)
            sl_px = getattr(pos, 'sl', 0.0)
            if pos.type == "BUY":
                if tp_px > 0 and ask >= tp_px:
                    self.close_position(pid, tp_px, timestamp)
                elif sl_px > 0 and bid <= sl_px:
                    self.close_position(pid, sl_px, timestamp)
            elif pos.type == "SELL":
                if tp_px > 0 and bid <= tp_px:
                    self.close_position(pid, tp_px, timestamp)
                elif sl_px > 0 and ask >= sl_px:
                    self.close_position(pid, sl_px, timestamp)

        float_pnl = self.get_floating_pnl(ask)
        self.account_equity = self.balance_usd + float_pnl
        return triggered

    def process_tick(self, prev_px: float, cur_px: float, ts: float):
        sym_u = self.symbol.upper()
        if "BTC" in sym_u:
            spread = 20.00
        elif "ETH" in sym_u:
            spread = 1.50
        elif "EURUSD" in sym_u:
            spread = 0.00015
        elif "USDJPY" in sym_u:
            spread = 0.015
        else:
            spread = 0.25  # Gold default
        ask = cur_px + spread
        bid = cur_px
        return self.update_tick(ask, bid, ts)


def generate_high_precision_candles(symbol: str, num_bars: int = 50000):
    sym_u = symbol.upper()
    random.seed(303)
    
    if "XAU" in sym_u or "GOLD" in sym_u or "PAXG" in sym_u:
        base_price = 2000.0
        volatility = 0.0008
    else:
        base_price = 2000.0
        volatility = 0.0008
    
    start_ts = time.time() - (num_bars * 60)
    rates = []
    current_price = base_price
    
    trend_bias = 0.0
    for i in range(num_bars):
        if i % 1440 == 0:  # Daily trend shift
            trend_bias = random.choice([-0.00008, -0.00002, 0.00002, 0.00008])
            
        ts = start_ts + (i * 60)
        # Heavy-tail fat shock simulation: 0.5% chance of 3x volatility spike
        fat_shock = random.choice([1.0, 1.0, 1.0, 1.0, 2.5]) if random.random() < 0.005 else 1.0
        ret = trend_bias + (random.gauss(0, volatility) * fat_shock)
        open_p = current_price
        close_p = open_p * (1.0 + ret)
        high_p = max(open_p, close_p) * (1.0 + abs(random.gauss(0, volatility * 0.4 * fat_shock)))
        low_p = min(open_p, close_p) * (1.0 - abs(random.gauss(0, volatility * 0.4 * fat_shock)))
        current_price = max(base_price * 0.5, close_p)
        
        rates.append({
            'time': ts,
            'open': open_p,
            'high': high_p,
            'low': low_p,
            'close': close_p
        })
    return rates


def run_high_precision_backtest(sym_name: str, num_bars: int = 43200):
    rates = generate_high_precision_candles(sym_name, num_bars)
    
    total_bars = len(rates)
    first_time = datetime.datetime.fromtimestamp(rates[0]['time'])
    last_time = datetime.datetime.fromtimestamp(rates[-1]['time'])
    days_covered = (last_time - first_time).total_seconds() / 86400.0

    print(f"[OK] Loaded {total_bars:,} Intrabar M1 Candles ({days_covered:.1f} Days)")

    broker = BacktestBroker(initial_balance=5000.0, symbol=sym_name)
    sym_u = sym_name.upper()
    
    if "XAU" in sym_u or "GOLD" in sym_u or "PAXG" in sym_u:
        base_order_size = 0.020
        g_gap = 0.050
        t_off = 0.050
        t_prof = 18.50
    else:
        base_order_size = 0.020
        g_gap = 0.050
        t_off = 0.050
        t_prof = 18.50

    bot = BreakoutGridBot(
        broker=broker,
        symbol=sym_name,
        grid_levels=10,
        grid_gap=g_gap,
        trap_offset=t_off,
        order_size=base_order_size,
        order_size_multiplier=1.25,
        target_profit=t_prof,
        auto_restart=True,
        use_auto_reading=True  # Enable auto reading to use hybrid logic
    )
    bot.spacing_mode = "Percentage (%)"

    prev_px = rates[0]['close']
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    peak_equity = broker.initial_balance

    start_perf = time.time()

    mock_get_historical_klines.all_rates = rates
    for i, r in enumerate(rates):
        mock_get_historical_klines.current_idx = i + 1
        ts = float(r['time'])
        h_px = float(r['high'])
        l_px = float(r['low'])
        c_px = float(r['close'])
        
        # Intrabar tick sequence: High -> Low -> Close to simulate real candle wicks
        for px in [h_px, l_px, c_px]:
            spread = 0.25

            broker.update_tick(px + spread, px, ts)
            
            eq = broker.account_equity
            if eq > peak_equity:
                peak_equity = eq
            dd_val = peak_equity - eq
            dd_pct_val = (dd_val / peak_equity * 100.0) if peak_equity > 0 else 0.0
            
            if dd_val > max_dd_usd: max_dd_usd = dd_val
            if dd_pct_val > max_dd_pct: max_dd_pct = dd_pct_val
            
            bot.process_tick(prev_px, px, ts)
            prev_px = px

    elapsed_sec = time.time() - start_perf
    closed = broker.closed_trades
    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] < 0]
    
    win_rate = (len(wins) / len(closed) * 100.0) if closed else 100.0
    net_pnl = broker.realized_pnl
    roi_pct = (net_pnl / broker.initial_balance) * 100.0
    
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0.0
    profit_factor = (sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses))) if losses and sum(t['pnl'] for t in losses) != 0 else float("inf")

    print("\n" + "=" * 70)
    print(f"HIGH-PRECISION INTRABAR BACKTEST REPORT: {sym_name}")
    print("=" * 70)
    print(f"Bars Tested         : {total_bars:,} M1 Candles ({days_covered:.1f} Days)")
    print(f"Execution Speed     : {elapsed_sec:.2f} seconds ({total_bars/elapsed_sec:,.0f} bars/sec)")
    print(f"Initial Capital     : ${broker.initial_balance:,.2f} USD")
    print(f"Final Account Eq    : ${broker.balance_usd:,.2f} USD")
    print(f"Net Realized PnL    : +${net_pnl:,.2f} USD (+{roi_pct:.2f}% ROI)")
    print(f"Total Completed Trades: {len(closed):,}")
    print(f"Winning Trades      : {len(wins):,} ({win_rate:.2f}%)")
    print(f"Losing Trades       : {len(losses):,}")
    print(f"Average Win Trade   : +${avg_win:.2f} USD")
    print(f"Average Loss Trade  : -${abs(avg_loss):.2f} USD")
    print(f"Profit Factor       : {profit_factor:.2f}")
    print(f"Max Equity Drawdown : -${max_dd_usd:,.2f} USD ({max_dd_pct:.2f}%)")
    print("=" * 70)

if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target_symbols = args if args else ["PAXGUSDT"]
    for sym in target_symbols:
        run_high_precision_backtest(sym)
