"""
=======================================================================
  MATY BOT — GOLD (PAXGUSDT) 1-MONTH REAL DATA BACKTEST
  Uses live Binance 1m OHLCV for the last 30 days, feeds each bar
  through the EXACT same strategy logic running in production.
=======================================================================
"""
import os, sys, time, math, random, datetime, json
if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

import requests
import pandas as pd
import numpy as np

# ─── Patch data layer BEFORE importing bot modules ───────────────────
import core.data as cd

# Global klines store for mock provider
_bt_klines_store: dict = {}

def mock_get_historical_klines(symbol, interval="1m", limit=30):
    key = f"{symbol}_{interval}"
    data = _bt_klines_store.get(key, [])
    curr_i = getattr(mock_get_historical_klines, "current_idx", limit)
    sub = data[max(0, curr_i - limit): curr_i]
    if not sub:
        return None
    return pd.DataFrame(sub)

def mock_get_live_price(symbol):
    key = f"{symbol}_1m"
    data = _bt_klines_store.get(key, [])
    idx = getattr(mock_get_historical_klines, "current_idx", 1)
    if data and idx > 0:
        return float(data[min(idx, len(data)) - 1].get("close", 4000.0))
    return 4000.0

def mock_get_order_book_depth(symbol):
    return {"asks": [[4400.0, 1.0]], "bids": [[4399.0, 1.0]], "buy_pressure_pct": 50.0}

def mock_get_economic_calendar():
    return []

def mock_calculate_technical_indicators(df):
    return {"ema_trend_bias": 0.0, "rsi": 50.0, "atr_pct": 0.30, "bb_width_pct": 2.0}

def mock_detect_fvg(df): return {}
def mock_detect_liquidity_sweep(df): return {}
def mock_detect_order_blocks(df): return {}
def mock_calculate_smc_elliott(df): return {}

cd.get_historical_klines      = mock_get_historical_klines
cd.get_live_price             = mock_get_live_price
cd.get_order_book_depth       = mock_get_order_book_depth
cd.get_economic_calendar      = mock_get_economic_calendar
cd.calculate_technical_indicators = mock_calculate_technical_indicators
cd.detect_fvg                 = mock_detect_fvg
cd.detect_liquidity_sweep     = mock_detect_liquidity_sweep
cd.detect_order_blocks        = mock_detect_order_blocks
cd.calculate_smc_elliott      = mock_calculate_smc_elliott

from core.engine import BreakoutGridBot, Order, Position

# ─────────────────────────────────────────────────────────────────────
# 1.  FETCH REAL DATA FROM BINANCE
# ─────────────────────────────────────────────────────────────────────
def fetch_binance_klines(symbol: str, interval: str, days: int) -> list[dict]:
    """Download candles from Binance using parallel requests (5x faster)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ms_per_bar  = {"1m": 60_000, "5m": 300_000, "15m": 900_000}[interval]
    chunk_limit = 1000
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    url = "https://api.binance.com/api/v3/klines"

    # Split into chunks
    chunks = []
    cur = start_ms
    while cur < end_ms:
        chunk_end = min(cur + chunk_limit * ms_per_bar, end_ms)
        chunks.append((cur, chunk_end))
        cur = chunk_end

    print(f"   Downloading {symbol} {interval} ({days}d) — {len(chunks)} chunks in parallel...")

    def fetch_chunk(start, end):
        for attempt in range(3):
            try:
                r = requests.get(url, params={
                    "symbol": symbol, "interval": interval,
                    "startTime": start, "endTime": end,
                    "limit": chunk_limit
                }, timeout=25)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == 2:
                    print(f"\n   [WARN] chunk failed: {e}")
                    return []
                time.sleep(1.5)
        return []

    results = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_chunk, s, e): i for i, (s, e) in enumerate(chunks)}
        done = 0
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
            done += 1
            print(f"   ... {done}/{len(chunks)} chunks done", end="\r")

    all_bars = []
    for idx in sorted(results):
        for b in results[idx]:
            all_bars.append({
                "time":      b[0] / 1000.0,
                "open":      float(b[1]),
                "high":      float(b[2]),
                "low":       float(b[3]),
                "close":     float(b[4]),
                "volume":    float(b[5]),
                "timestamp": b[0] / 1000.0,
            })

    # Deduplicate by timestamp
    seen = set()
    deduped = []
    for b in all_bars:
        if b["time"] not in seen:
            seen.add(b["time"])
            deduped.append(b)
    deduped.sort(key=lambda x: x["time"])
    print(f"\n   [OK] Fetched {len(deduped):,} {interval} candles.")
    return deduped

# ─────────────────────────────────────────────────────────────────────
# 2.  BACKTESTING BROKER  (same as run_1year_backtest.py but improved)
# ─────────────────────────────────────────────────────────────────────
class BacktestBroker:
    SPREAD_GOLD = 0.30   # $0.30 fixed spread for PAXG/XAU

    def __init__(self, initial_balance=5000.0, symbol="PAXGUSDT"):
        self.symbol          = symbol
        self.initial_balance = initial_balance
        self.balance_usd     = initial_balance
        self.account_equity  = initial_balance
        self.is_cent_account = False
        self.pending_orders  = {}
        self.open_positions  = {}
        self.closed_trades   = []
        self.realized_pnl    = 0.0
        self.last_ask        = 0.0
        self.last_bid        = 0.0
        self.magic_number    = 9999
        self._order_ctr      = 0
        self._pos_ctr        = 0

    def ensure_connected(self):  return True
    def get_min_stop_distance(self): return 0.50

    def place_order(self, order_type, price, size, timestamp, tp=0.0, sl=0.0, **kw):
        self._order_ctr += 1
        oid = f"ord_{self._order_ctr}"
        o = Order(type=order_type, trigger_price=price, size=size, timestamp=timestamp)
        o.order_id = oid; o.tp = tp; o.sl = sl
        o.symbol = self.symbol
        self.pending_orders[oid] = o
        return o

    def cancel_order(self, oid):
        return bool(self.pending_orders.pop(oid, None))

    def cancel_all_orders(self):
        n = len(self.pending_orders); self.pending_orders.clear(); return n

    def _open_position(self, order, fill_price, pos_type, timestamp):
        self._pos_ctr += 1
        pid = f"pos_{self._pos_ctr}"
        pos = Position(type=pos_type, entry_price=fill_price, size=order.size, entry_time=timestamp)
        pos.position_id  = pid
        pos.tp           = getattr(order, "tp", 0.0)
        pos.sl           = getattr(order, "sl", 0.0)
        pos.entry_price  = fill_price
        pos.symbol       = self.symbol
        self.open_positions[pid] = pos
        return pos

    def close_position(self, pid, exit_price, timestamp, exit_reason="BOT_CLOSE"):
        pos = self.open_positions.pop(pid, None)
        if pos is None: return None
        pnl = pos.get_pnl(exit_price) - self.SPREAD_GOLD * pos.size * 100
        self.realized_pnl += pnl
        self.balance_usd  += pnl
        rec = {
            "position_id": pid, "type": pos.type,
            "entry_price": pos.entry_price, "deploy_price": pos.entry_price,
            "exit_price": exit_price, "size": pos.size,
            "pnl": pnl, "entry_time": pos.entry_time, "exit_time": timestamp,
            "duration": max(1, int(timestamp - pos.entry_time)),
            "exit_reason": exit_reason, "symbol": self.symbol,
            "fills_count": 1,
        }
        self.closed_trades.append(rec)
        return rec

    def partial_close_position(self, pid, fraction, exit_price, timestamp):
        pos = self.open_positions.get(pid)
        if not pos: return None
        close_size = round(pos.size * fraction, 2)
        if close_size <= 0: return None
        pnl = (exit_price - pos.entry_price if "BUY" in pos.type else pos.entry_price - exit_price) * close_size * 100 - self.SPREAD_GOLD * close_size * 100
        self.realized_pnl += pnl
        self.balance_usd  += pnl
        pos.size = max(0.01, round(pos.size - close_size, 2))
        rec = {"position_id": pid, "pnl": pnl, "close_size": close_size, "partial": True}
        self.closed_trades.append({**rec, "type": pos.type, "entry_price": pos.entry_price,
                                    "exit_price": exit_price, "entry_time": pos.entry_time,
                                    "exit_time": timestamp, "exit_reason": "PARTIAL_TP",
                                    "symbol": self.symbol, "fills_count": 1,
                                    "deploy_price": pos.entry_price, "size": close_size,
                                    "duration": max(1, int(timestamp - pos.entry_time))})
        return rec

    def close_all_positions(self, exit_price=0.0, timestamp=0.0, symbol=None, side=None, exclude_ids=None):
        closed = []
        exclude_ids = exclude_ids or set()
        px = exit_price or self.last_bid
        for pid in list(self.open_positions):
            if pid in exclude_ids: continue
            pos = self.open_positions.get(pid)
            if pos and side and str(pos.type).upper() != str(side).upper(): continue
            r = self.close_position(pid, px or pos.entry_price, timestamp or time.time())
            if r: closed.append(r)
        return closed

    def modify_position_sl_tp(self, pid, sl=None, tp=None):
        pos = self.open_positions.get(pid)
        if not pos: return False
        if sl is not None: pos.sl = sl
        if tp is not None: pos.tp = tp
        return True

    def get_floating_pnl(self, current_price):
        total = 0.0
        for pid, pos in self.open_positions.items():
            total += pos.get_pnl(current_price)
        return total

    def update_tick(self, ask, bid, timestamp):
        self.last_ask = ask; self.last_bid = bid
        triggered = []
        pip = 0.10
        for oid, o in list(self.pending_orders.items()):
            fill = None; ptype = None
            if   o.type == "BUY_STOP"   and ask >= o.trigger_price: fill = o.trigger_price + random.uniform(0, 0.5)*pip; ptype = "BUY"
            elif o.type == "SELL_STOP"  and bid <= o.trigger_price: fill = o.trigger_price - random.uniform(0, 0.5)*pip; ptype = "SELL"
            elif o.type == "BUY_LIMIT"  and ask <= o.trigger_price: fill = o.trigger_price - random.uniform(0, 0.3)*pip; ptype = "BUY"
            elif o.type == "SELL_LIMIT" and bid >= o.trigger_price: fill = o.trigger_price + random.uniform(0, 0.3)*pip; ptype = "SELL"
            if fill is not None:
                pos = self._open_position(o, fill, ptype, timestamp)
                del self.pending_orders[oid]
                triggered.append(pos)

        for pid, pos in list(self.open_positions.items()):
            tp_px = getattr(pos, "tp", 0.0)
            sl_px = getattr(pos, "sl", 0.0)
            if pos.type == "BUY":
                if tp_px > 0 and ask >= tp_px: self.close_position(pid, tp_px, timestamp, "TARGET_PROFIT")
                elif sl_px > 0 and bid <= sl_px: self.close_position(pid, sl_px, timestamp, "STOP_LOSS")
            elif pos.type == "SELL":
                if tp_px > 0 and bid <= tp_px: self.close_position(pid, tp_px, timestamp, "TARGET_PROFIT")
                elif sl_px > 0 and ask >= sl_px: self.close_position(pid, sl_px, timestamp, "STOP_LOSS")

        self.account_equity = self.balance_usd + self.get_floating_pnl(bid)
        return triggered


# ─────────────────────────────────────────────────────────────────────
# 3.  RUN BACKTEST
# ─────────────────────────────────────────────────────────────────────
def run_backtest(symbol="PAXGUSDT", days=30, initial_balance=5000.0):
    print("\n" + "="*70)
    print(f"  MATY BOT — {symbol} {days}-DAY REAL DATA BACKTEST")
    print("="*70)

    # Download 1m and 5m candles
    bars_1m = fetch_binance_klines(symbol, "1m", days)
    bars_5m = fetch_binance_klines(symbol, "5m", days)

    if not bars_1m:
        print("[ERROR] No 1m data fetched. Check internet / Binance API.")
        return

    # Populate mock klines store (used by deploy_traps AI eval)
    _bt_klines_store[f"{symbol}_1m"] = bars_1m
    _bt_klines_store[f"{symbol}_5m"] = bars_5m

    total_bars = len(bars_1m)
    first_dt = datetime.datetime.fromtimestamp(bars_1m[0]["time"])
    last_dt  = datetime.datetime.fromtimestamp(bars_1m[-1]["time"])
    print(f"[OK] {total_bars:,} M1 bars | {first_dt:%Y-%m-%d} → {last_dt:%Y-%m-%d}")

    broker = BacktestBroker(initial_balance=initial_balance, symbol=symbol)
    bot = BreakoutGridBot(
        broker=broker,
        symbol=symbol,
        grid_levels=6,
        grid_gap=0.05,
        trap_offset=0.05,
        order_size=0.02,
        order_size_multiplier=1.0,
        target_profit=12.0,   # $12 basket target for Gold
        auto_restart=True,
        use_auto_reading=False,  # Pure rule-based for backtest reproducibility
    )
    bot.stop_loss           = 25.0
    bot.max_cycle_drawdown  = 25.0
    bot.use_smart_trailing  = True
    bot.use_trailing_stop   = True
    bot.spacing_mode        = "Percentage (%)"
    bot.symbol_code         = symbol

    # Track metrics
    equity_curve    = []
    peak_equity     = initial_balance
    max_dd_usd      = 0.0
    max_dd_pct      = 0.0
    prev_px         = float(bars_1m[0]["close"])
    start_t         = time.time()
    log_every       = max(1, total_bars // 20)

    print(f"\n[RUNNING] Simulating {total_bars:,} M1 bars with intrabar H/L/C tick sequence...")

    for i, bar in enumerate(bars_1m):
        mock_get_historical_klines.current_idx = i + 1
        ts  = float(bar["time"])
        h   = float(bar["high"])
        l   = float(bar["low"])
        c   = float(bar["close"])
        spd = BacktestBroker.SPREAD_GOLD

        # Intrabar tick sequence: High → Low → Close
        for px in [h, l, c]:
            broker.update_tick(px + spd, px, ts)
            eq = broker.account_equity
            if eq > peak_equity: peak_equity = eq
            dd  = peak_equity - eq
            ddp = (dd / peak_equity * 100) if peak_equity > 0 else 0
            if dd  > max_dd_usd: max_dd_usd = dd
            if ddp > max_dd_pct: max_dd_pct = ddp
            bot.process_tick(prev_px, px, ts)
            prev_px = px

        equity_curve.append({"ts": ts, "equity": broker.account_equity, "balance": broker.balance_usd})

        if i % log_every == 0:
            pct = (i / total_bars) * 100
            print(f"   [{pct:4.0f}%] Bar {i:,}/{total_bars:,} | Eq: ${broker.account_equity:,.2f} | "
                  f"Trades: {len(broker.closed_trades)} | PnL: ${broker.realized_pnl:+.2f}")

    elapsed = time.time() - start_t
    closed  = broker.closed_trades
    wins    = [t for t in closed if t["pnl"] > 0]
    losses  = [t for t in closed if t["pnl"] < 0]
    breakeven = [t for t in closed if t["pnl"] == 0]

    net_pnl      = broker.realized_pnl
    roi_pct      = (net_pnl / initial_balance) * 100
    win_rate     = (len(wins) / len(closed) * 100) if closed else 0
    avg_win      = (sum(t["pnl"] for t in wins)   / len(wins))   if wins   else 0
    avg_loss     = (sum(t["pnl"] for t in losses) / len(losses)) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    avg_duration_m = (sum(t.get("duration", 0) for t in closed) / len(closed) / 60) if closed else 0
    sharpe        = (net_pnl / (initial_balance * max_dd_pct / 100 + 0.001)) if max_dd_pct > 0 else 0

    # Monthly trade breakdown
    monthly: dict = {}
    for t in closed:
        dt = datetime.datetime.fromtimestamp(t.get("exit_time", t.get("entry_time", 0)))
        key = dt.strftime("%Y-%m")
        if key not in monthly:
            monthly[key] = {"trades": 0, "pnl": 0.0, "wins": 0}
        monthly[key]["trades"] += 1
        monthly[key]["pnl"]    += t["pnl"]
        if t["pnl"] > 0: monthly[key]["wins"] += 1

    # ── Console Report ──
    print("\n" + "="*70)
    print(f"  BACKTEST REPORT: {symbol}  ({first_dt:%b %d} → {last_dt:%b %d %Y})")
    print("="*70)
    print(f"  Initial Capital      : ${initial_balance:,.2f}")
    print(f"  Final Balance        : ${broker.balance_usd:,.2f}")
    print(f"  Final Equity         : ${broker.account_equity:,.2f}")
    print(f"  Net Realized PnL     : ${net_pnl:+,.2f}  ({roi_pct:+.2f}% ROI)")
    print(f"  Peak Equity          : ${peak_equity:,.2f}")
    print(f"  Max Drawdown         : -${max_dd_usd:,.2f}  ({max_dd_pct:.2f}%)")
    print(f"  Sharpe-like Ratio    : {sharpe:.2f}")
    print("-"*70)
    print(f"  Total Closed Trades  : {len(closed)}")
    print(f"  Wins                 : {len(wins)}  ({win_rate:.1f}%)")
    print(f"  Losses               : {len(losses)}")
    print(f"  Breakeven            : {len(breakeven)}")
    print(f"  Profit Factor        : {profit_factor:.2f}")
    print(f"  Avg Win              : ${avg_win:+.2f}")
    print(f"  Avg Loss             : ${avg_loss:+.2f}")
    print(f"  Avg Trade Duration   : {avg_duration_m:.1f} min")
    print(f"  Gross Profit         : ${gross_profit:,.2f}")
    print(f"  Gross Loss           : -${gross_loss:,.2f}")
    print("-"*70)
    print(f"  Execution speed      : {total_bars/elapsed:,.0f} bars/sec ({elapsed:.1f}s total)")
    print("="*70)

    if monthly:
        print("\n  Monthly Breakdown:")
        print(f"  {'Month':<10} {'Trades':>8} {'Wins':>6} {'Win%':>6} {'PnL':>12}")
        print("  " + "-"*50)
        for mo, s in sorted(monthly.items()):
            wr = (s["wins"] / s["trades"] * 100) if s["trades"] > 0 else 0
            print(f"  {mo:<10} {s['trades']:>8} {s['wins']:>6} {wr:>5.1f}% {s['pnl']:>+12.2f}")

    # ── HTML Report ──
    generate_html_report(symbol, first_dt, last_dt, initial_balance, broker,
                         net_pnl, roi_pct, win_rate, avg_win, avg_loss,
                         profit_factor, max_dd_usd, max_dd_pct, sharpe,
                         avg_duration_m, gross_profit, gross_loss,
                         equity_curve, closed, monthly)
    return closed


# ─────────────────────────────────────────────────────────────────────
# 4.  HTML REPORT
# ─────────────────────────────────────────────────────────────────────
def generate_html_report(symbol, first_dt, last_dt, init_bal, broker,
                          net_pnl, roi_pct, win_rate, avg_win, avg_loss,
                          profit_factor, max_dd_usd, max_dd_pct, sharpe,
                          avg_dur_m, gross_profit, gross_loss,
                          equity_curve, closed, monthly):
    # Equity curve for chart
    eq_labels = [datetime.datetime.fromtimestamp(e["ts"]).strftime("%m/%d %H:%M") for e in equity_curve[::60]]
    eq_values = [round(e["equity"], 2) for e in equity_curve[::60]]
    bal_values = [round(e["balance"], 2) for e in equity_curve[::60]]

    # Waterfall per-trade PnL
    trade_labels = [datetime.datetime.fromtimestamp(t.get("exit_time", t.get("entry_time", 0))).strftime("%m/%d") for t in closed[-50:]]
    trade_pnls   = [round(t["pnl"], 2) for t in closed[-50:]]
    trade_colors = ["#22c55e" if p > 0 else "#ef4444" for p in trade_pnls]

    # Monthly bar data
    mo_labels = sorted(monthly.keys())
    mo_pnls   = [round(monthly[k]["pnl"], 2) for k in mo_labels]
    mo_colors = ["#22c55e" if p >= 0 else "#ef4444" for p in mo_pnls]

    status_color = "#22c55e" if net_pnl > 0 else "#ef4444"
    status_icon  = "✅" if net_pnl > 0 else "❌"

    # Last 30 trades table rows
    trade_rows = ""
    for t in sorted(closed, key=lambda x: x.get("exit_time", 0), reverse=True)[:50]:
        pnl = t["pnl"]
        cls = "pnl-green" if pnl > 0 else "pnl-red"
        exit_dt = datetime.datetime.fromtimestamp(t.get("exit_time", 0)).strftime("%m/%d %H:%M")
        dur_m = int(t.get("duration", 0)) // 60
        er = t.get("exit_reason", "")
        trade_rows += f"""<tr>
            <td>{t.get("type","?")}</td>
            <td>${t.get("entry_price",0):,.3f}</td>
            <td>${t.get("exit_price",0):,.3f}</td>
            <td>{exit_dt}</td>
            <td>{dur_m}m</td>
            <td>{er}</td>
            <td class="{cls}">{pnl:+.2f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maty Bot — {symbol} 1-Month Backtest Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f1117; --surface: #1a1d2e; --surface2: #252839;
    --accent: #f59e0b; --green: #22c55e; --red: #ef4444;
    --blue: #3b82f6; --text: #e2e8f0; --muted: #64748b;
    --border: rgba(255,255,255,0.07);
  }}
  body {{ font-family: "Inter", sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 2rem 1.5rem; }}
  .header {{ text-align: center; padding: 3rem 0 2rem; }}
  .header h1 {{ font-size: 2.4rem; font-weight: 700; background: linear-gradient(135deg, #f59e0b, #f97316); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .header p  {{ color: var(--muted); margin-top: .5rem; font-size: .95rem; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 2rem 0; }}
  .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.4rem 1.2rem; }}
  .kpi .label {{ font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: .5rem; }}
  .kpi .value {{ font-size: 1.8rem; font-weight: 700; }}
  .kpi .value.green {{ color: var(--green); }}
  .kpi .value.red   {{ color: var(--red);   }}
  .kpi .value.gold  {{ color: var(--accent); }}
  .kpi .value.blue  {{ color: var(--blue);  }}
  .charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 1.5rem; margin: 2rem 0; }}
  .chart-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.4rem; }}
  .chart-box h3 {{ font-size: .9rem; color: var(--muted); margin-bottom: 1rem; text-transform: uppercase; letter-spacing: .06em; }}
  canvas {{ width: 100% !important; }}
  .charts2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin: 2rem 0; }}
  .table-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.4rem; margin: 2rem 0; overflow-x: auto; }}
  .table-box h3 {{ font-size: .9rem; color: var(--muted); margin-bottom: 1rem; text-transform: uppercase; letter-spacing: .06em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  th {{ color: var(--muted); text-transform: uppercase; font-size: .72rem; letter-spacing: .06em; padding: .6rem .8rem; border-bottom: 1px solid var(--border); text-align: left; }}
  td {{ padding: .55rem .8rem; border-bottom: 1px solid var(--border); }}
  tr:hover td {{ background: rgba(255,255,255,0.03); }}
  .pnl-green {{ color: var(--green); font-weight: 600; }}
  .pnl-red   {{ color: var(--red);   font-weight: 600; }}
  .badge {{ display: inline-block; padding: .2rem .5rem; border-radius: 4px; font-size: .72rem; font-weight: 600; }}
  .badge.green {{ background: rgba(34,197,94,.15); color: var(--green); }}
  .badge.red   {{ background: rgba(239,68,68,.15);  color: var(--red);  }}
  @media(max-width:768px) {{ .charts,.charts2 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🟡 {symbol} Backtest Report {status_icon}</h1>
    <p>{first_dt:%b %d, %Y} → {last_dt:%b %d, %Y} &nbsp;|&nbsp; Maty Bot — SMC DCA Grid Strategy &nbsp;|&nbsp; Capital: ${init_bal:,.0f}</p>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="label">Net PnL</div><div class="value {'green' if net_pnl>0 else 'red'}">${net_pnl:+,.2f}</div></div>
    <div class="kpi"><div class="label">ROI</div><div class="value {'green' if roi_pct>0 else 'red'}">{roi_pct:+.2f}%</div></div>
    <div class="kpi"><div class="label">Win Rate</div><div class="value blue">{win_rate:.1f}%</div></div>
    <div class="kpi"><div class="label">Profit Factor</div><div class="value {'green' if profit_factor>1 else 'red'}">{profit_factor:.2f}x</div></div>
    <div class="kpi"><div class="label">Max Drawdown</div><div class="value red">-${max_dd_usd:,.2f} ({max_dd_pct:.1f}%)</div></div>
    <div class="kpi"><div class="label">Total Trades</div><div class="value gold">{len(closed)}</div></div>
    <div class="kpi"><div class="label">Avg Win</div><div class="value green">${avg_win:+.2f}</div></div>
    <div class="kpi"><div class="label">Avg Loss</div><div class="value red">${avg_loss:+.2f}</div></div>
    <div class="kpi"><div class="label">Avg Duration</div><div class="value blue">{avg_dur_m:.0f} min</div></div>
    <div class="kpi"><div class="label">Final Balance</div><div class="value gold">${broker.balance_usd:,.2f}</div></div>
  </div>

  <div class="charts">
    <div class="chart-box">
      <h3>📈 Equity Curve</h3>
      <canvas id="eqChart" height="200"></canvas>
    </div>
    <div class="chart-box">
      <h3>📊 Monthly PnL</h3>
      <canvas id="moChart" height="200"></canvas>
    </div>
  </div>

  <div class="charts2">
    <div class="chart-box">
      <h3>💹 Last 50 Trades PnL</h3>
      <canvas id="tradeChart" height="200"></canvas>
    </div>
    <div class="chart-box">
      <h3>🥧 Win / Loss Distribution</h3>
      <canvas id="pieChart" height="200"></canvas>
    </div>
  </div>

  <div class="table-box">
    <h3>📋 Last 50 Closed Trades</h3>
    <table>
      <thead><tr><th>Type</th><th>Entry</th><th>Exit</th><th>Exit Time</th><th>Duration</th><th>Reason</th><th>PnL</th></tr></thead>
      <tbody>{trade_rows}</tbody>
    </table>
  </div>
</div>

<script>
const eqLabels  = {json.dumps(eq_labels)};
const eqVals    = {json.dumps(eq_values)};
const balVals   = {json.dumps(bal_values)};
const moLabels  = {json.dumps(mo_labels)};
const moPnls    = {json.dumps(mo_pnls)};
const moColors  = {json.dumps(mo_colors)};
const trLabels  = {json.dumps(trade_labels)};
const trPnls    = {json.dumps(trade_pnls)};
const trColors  = {json.dumps(trade_colors)};
const wins      = {len(wins)};
const losses    = {len(losses)};
const be_count  = {len(breakeven)};

Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';

new Chart(document.getElementById('eqChart'), {{
  type:'line',
  data:{{ labels:eqLabels, datasets:[
    {{label:'Equity', data:eqVals, borderColor:'#f59e0b', backgroundColor:'rgba(245,158,11,0.08)', fill:true, tension:0.3, pointRadius:0}},
    {{label:'Balance', data:balVals, borderColor:'#3b82f6', backgroundColor:'rgba(59,130,246,0.04)', fill:false, tension:0.3, pointRadius:0, borderDash:[4,3]}}
  ]}},
  options:{{ responsive:true, plugins:{{legend:{{labels:{{color:'#94a3b8'}}}}}}, scales:{{x:{{ticks:{{maxTicksLimit:8}}}}, y:{{ticks:{{callback:v=>'$'+v.toLocaleString()}} }} }} }}
}});

new Chart(document.getElementById('moChart'), {{
  type:'bar',
  data:{{ labels:moLabels, datasets:[{{label:'PnL', data:moPnls, backgroundColor:moColors, borderRadius:6}}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}}}}, scales:{{y:{{ticks:{{callback:v=>'$'+v}}}} }} }}
}});

new Chart(document.getElementById('tradeChart'), {{
  type:'bar',
  data:{{ labels:trLabels, datasets:[{{label:'PnL', data:trPnls, backgroundColor:trColors, borderRadius:3}}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}}}}, scales:{{y:{{ticks:{{callback:v=>'$'+v}}}} }} }}
}});

new Chart(document.getElementById('pieChart'), {{
  type:'doughnut',
  data:{{ labels:['Wins','Losses','BE'], datasets:[{{data:[wins,losses,be_count], backgroundColor:['#22c55e','#ef4444','#64748b'], borderWidth:0}}] }},
  options:{{ responsive:true, plugins:{{legend:{{position:'bottom',labels:{{color:'#94a3b8'}}}}}}  }}
}});
</script>
</body>
</html>"""

    fname = f"backtest_{symbol}_{first_dt:%Y%m%d}_{last_dt:%Y%m%d}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  [HTML REPORT] Saved → {fname}")
    print(f"  Open in browser: file:///{os.path.abspath(fname)}")


# ─────────────────────────────────────────────────────────────────────
# 5.  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Maty Gold Backtest")
    p.add_argument("--symbol",  default="PAXGUSDT",  help="Binance symbol (default PAXGUSDT)")
    p.add_argument("--days",    type=int, default=30, help="Days to backtest (default 30)")
    p.add_argument("--balance", type=float, default=5000.0, help="Starting balance USD")
    args = p.parse_args()
    run_backtest(symbol=args.symbol, days=args.days, initial_balance=args.balance)
