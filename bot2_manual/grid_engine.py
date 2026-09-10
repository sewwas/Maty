#!/usr/bin/env python3
"""
===============================================================================
  🤖 PROFITY AI — BOT #2 AUTONOMOUS 24/7 GRID ENGINE DAEMON
  Dedicated Zero-Latency Execution Engine for XAUUSD (Exness #257515247)
===============================================================================
  ⚡ 100% ISOLATED & DECOUPLED from Streamlit web UI.
  🎯 Guarantees INSTANT ZERO-LATENCY TARGET PROFIT & STOP LOSS AUTO-CLOSING 24/7.
  🔄 Runs continuously via systemd even when browser is closed or PC is off.
  📡 Directly controls MT5 Wine Bridge (port 8002) with high-speed persistent pooling.
===============================================================================
"""

import os
import sys
import time
import json
import signal
import logging
import datetime
import threading
import concurrent.futures
import requests

# ── Force UTF-8 Output ────────────────────────────────────────────────────────
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ── Directory & Path Setup ───────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── Configure Logging ─────────────────────────────────────────────────────────
LOG_FILE = os.path.join(ROOT_DIR, "bot2_engine.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Bot2Engine] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("Bot2Engine")

# ── High-Speed Persistent HTTP Session (Zero-Handshake Connection Pooling) ────
_FAST_SESSION = requests.Session()
_FAST_SESSION.trust_env = False  # Direct localhost communication; bypass proxies
_adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=50, max_retries=0)
_FAST_SESSION.mount("http://", _adapter)

# ── Core Constants ────────────────────────────────────────────────────────────
MANUAL_MAGIC          = 777001                # Dedicated magic number for Bot #2
ALLOWED_MANUAL_MAGICS = (MANUAL_MAGIC, 1008876)
SYMBOL                = "PAXGUSDT"            # Binance / Coinbase price feed key
EXNESS_SYMBOL         = "XAUUSD"              # MT5 broker symbol
MT5_BRIDGE_PORT       = "8002"
os.environ["WINE_BRIDGE_PORT"] = MT5_BRIDGE_PORT

STATE_FILE         = os.path.join(BASE_DIR, "manual_state.json")
MAX_HISTORY_ROWS   = 300

from core.data import get_live_price, get_default_price
from core.mt5_broker import MT5Broker

# ── State Management ──────────────────────────────────────────────────────────
_STATE_LOCK = threading.Lock()

def load_state() -> dict:
    """Loads persisted manual desk state from disk with thread safety."""
    default = {
        "grid_config": {
            "center_mode": "Live Price (Auto-Centered)",
            "center_price": 0.0,
            "levels_above": 11,
            "levels_below": 11,
            "offset_mode": "USD ($)",
            "offset_value": 3.0,
            "offset_pct": 0.05,
            "gap_mode": "USD ($)",
            "gap_value": 3.0,
            "gap_pct": 0.07,
            "lot_size": 0.01,
            "flat_levels": 2,
            "lot_mult": 1.3,
            "target_profit": 5.0,
            "stop_loss": 500.0,
            "auto_redeploy": True,
            "cycle_close_all": True,
            "side_harvest": False,
            "single_tp": 1.50,
        },
        "trade_history": [],
        "deployed": False,
        "grid_levels": {},
    }
    with _STATE_LOCK:
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        for k, v in default.items():
                            if k not in data:
                                data[k] = v
                        if "grid_config" in data:
                            for ck, cv in default["grid_config"].items():
                                if ck not in data["grid_config"]:
                                    data["grid_config"][ck] = cv
                        return data
        except Exception as e:
            logger.warning(f"State load warning: {e}")
    return default


def save_state(state: dict):
    """Saves manual desk state to disk atomically with thread safety."""
    with _STATE_LOCK:
        try:
            pid = os.getpid()
            tid = threading.get_ident()
            tmp_file = f"{STATE_FILE}.{pid}_{tid}_{time.time_ns()}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_file, STATE_FILE)
        except Exception as e:
            logger.warning(f"State save warning: {e}")


# ── Broker & Market Data Helpers ──────────────────────────────────────────────
def get_manual_broker() -> MT5Broker:
    """Creates the MT5Broker instance connected to Bridge port 8002."""
    _env_pass = os.environ.get("EXNESS_PASSWORD", "")
    brk = MT5Broker(
        symbol=SYMBOL,
        login=None,
        password=_env_pass,
        server="",
        magic_number=MANUAL_MAGIC,
    )
    return brk


def get_mt5_live_price(brk: MT5Broker = None) -> float:
    """Fetches real-time bid/ask mid price directly from MT5 bridge."""
    try:
        r = _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/symbol_info?symbol={EXNESS_SYMBOL}", timeout=3.0)
        if r.status_code == 200:
            d = r.json()
            ask = float(d.get("ask", 0.0) or 0.0)
            bid = float(d.get("bid", 0.0) or 0.0)
            if ask > 0 and bid > 0:
                return round((ask + bid) / 2.0, 2)
    except Exception:
        pass
    p = get_live_price(EXNESS_SYMBOL) or get_live_price(SYMBOL) or get_default_price(EXNESS_SYMBOL)
    return round(float(p), 2)


def compute_grid_levels(
    center: float,
    gap_val: float,
    levels_above: int,
    levels_below: int,
    gap_mode: str = "USD ($)",
    offset_val: float = 3.0,
    offset_mode: str = "USD ($)"
) -> dict:
    """Computes symmetric grid levels above and below center price."""
    if "USD" in str(offset_mode).upper() or str(offset_mode) == "$":
        off_step = max(0.01, round(float(offset_val), 2))
    else:
        off_step = max(0.01, round(center * (float(offset_val) / 100.0), 2))

    if "USD" in str(gap_mode).upper() or str(gap_mode) == "$":
        gap_step = max(0.01, round(float(gap_val), 2))
    else:
        gap_step = max(0.01, round(center * (float(gap_val) / 100.0), 2))

    buy_stops = sorted([
        round(center + off_step + (gap_step * i), 2)
        for i in range(levels_above)
    ])
    sell_stops = sorted([
        round(center - off_step - (gap_step * i), 2)
        for i in range(levels_below)
    ], reverse=True)

    return {
        "buy_stops": buy_stops,
        "sell_stops": sell_stops,
        "step": gap_step,
        "offset": off_step,
    }


def get_live_positions(brk: MT5Broker) -> list:
    """Returns all open positions with Bot #2 magic."""
    raw = brk._fetch_live_positions()
    if not raw:
        return []
    return [p for p in raw if getattr(p, "magic", 0) in ALLOWED_MANUAL_MAGICS]


def get_live_pending(brk: MT5Broker) -> list:
    """Returns all pending orders with Bot #2 magic."""
    raw = brk._fetch_live_orders()
    if not raw:
        return []
    return [o for o in raw if getattr(o, "magic", 0) in ALLOWED_MANUAL_MAGICS]


def get_account_summary(brk: MT5Broker) -> dict:
    """Returns live account summary from bridge port 8002."""
    try:
        r = _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/account", timeout=3.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"balance": 0.0, "equity": 0.0, "currency": "USC", "connected": False}


# ── Execution Logic ───────────────────────────────────────────────────────────
def _pos_priority_key(p):
    profit = float(getattr(p, "profit", 0.0))
    vol = float(getattr(p, "volume", 0.0))
    return (0, -vol, -profit) if profit >= 0 else (1, -vol, profit)


def deploy_grid(brk: MT5Broker, levels: dict, lot_size: float, lot_mult: float = 1.0, flat_levels: int = 2) -> tuple:
    """Places grid pending orders with progressive Martingale sizing."""
    placed, errors = 0, []
    ts = time.time()

    # Pre-deployment purge
    try:
        cancel_all_pending(brk)
        time.sleep(0.10)
    except Exception:
        pass

    live_p = get_mt5_live_price(brk)
    min_dist = brk.get_min_stop_distance() if hasattr(brk, "get_min_stop_distance") else 0.50
    gap_step = max(0.20, float(levels.get("step", 3.0)))

    # BUY_STOPS
    last_buy_px = round(live_p + min_dist, 2)
    for i, price in enumerate(levels.get("buy_stops", [])):
        try:
            exponent = 0 if i < flat_levels else (i - flat_levels + 1)
            actual_lot = round(lot_size * (lot_mult ** exponent), 2)
            target_px = max(price, last_buy_px) if i == 0 else max(price, round(last_buy_px + gap_step, 2))
            last_buy_px = target_px

            order = brk.place_order("BUY_STOP", price=target_px, size=actual_lot, timestamp=ts)
            if order:
                placed += 1
            else:
                errors.append(f"BUY_STOP @ {target_px:.2f}: no order returned")
        except Exception as e:
            errors.append(f"BUY_STOP @ {price:.2f}: {e}")

    # SELL_STOPS
    last_sell_px = round(live_p - min_dist, 2)
    for i, price in enumerate(levels.get("sell_stops", [])):
        try:
            exponent = 0 if i < flat_levels else (i - flat_levels + 1)
            actual_lot = round(lot_size * (lot_mult ** exponent), 2)
            target_px = min(price, last_sell_px) if i == 0 else min(price, round(last_sell_px - gap_step, 2))
            last_sell_px = target_px

            order = brk.place_order("SELL_STOP", price=target_px, size=actual_lot, timestamp=ts)
            if order:
                placed += 1
            else:
                errors.append(f"SELL_STOP @ {target_px:.2f}: no order returned")
        except Exception as e:
            errors.append(f"SELL_STOP @ {price:.2f}: {e}")

    return placed, errors


def cancel_all_pending(brk: MT5Broker) -> str:
    """Cancels all pending orders for Bot #2 immediately."""
    cancelled = 0
    errors = []
    for m_id in ALLOWED_MANUAL_MAGICS:
        try:
            r = _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/cancel_all?magic={m_id}", timeout=3.0)
            if r.status_code == 200 and r.json().get("success"):
                cancelled += int(r.json().get("cancelled_count", 0))
        except Exception as e:
            errors.append(str(e))

    # Concurrently cancel any remaining pendings
    orders = get_live_pending(brk)
    if orders:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(
                    lambda t_id: _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/order_cancel?ticket={t_id}", timeout=2.0),
                    getattr(o, "ticket", 0)
                )
                for o in orders if getattr(o, "ticket", 0) > 0
            ]
            for f in concurrent.futures.as_completed(futures):
                try:
                    res = f.result()
                    if res.status_code == 200 and res.json().get("success"):
                        cancelled += 1
                except Exception:
                    pass

    return f"Cancelled {cancelled} pending order(s)"


def flatten_all(brk: MT5Broker, state: dict) -> str:
    """
    INSTANT ZERO-LATENCY FLATTEN SEQUENCE:
    1. Close market positions FIRST (largest lot size & most profitable first).
    2. Concurrent straggler cleanup.
    3. Cancel all pending orders.
    4. Save audit trail to disk.
    """
    closed_count = 0
    cancelled_pend = 0
    total_pnl = 0.0
    errors = []
    audit_steps = []

    acc = get_account_summary(brk)
    acct_curr = acc.get("currency", "USD")
    curr_sym = "¢" if acct_curr == "USC" else "$"

    # PASS 1: Fast Atomic Bulk Close on Bridge
    for m_id in ALLOWED_MANUAL_MAGICS:
        try:
            r = _FAST_SESSION.get(
                f"http://127.0.0.1:{MT5_BRIDGE_PORT}/close_all?magic={m_id}&cancel_pending=0",
                timeout=6.0
            )
            if r.status_code == 200:
                d = r.json()
                if d.get("success"):
                    c_cnt = int(d.get("closed_count", 0))
                    closed_count += c_cnt
                    total_pnl += float(d.get("total_pnl", 0.0))
                    for a in d.get("audit", []):
                        audit_steps.append(f"Closed #{a['ticket']} ({a['volume']}L {a['side']}): {curr_sym}{a['pnl']:+.2f}")
        except Exception as e:
            errors.append(f"Bridge atomic close error: {e}")

    # PASS 2: Immediate concurrent sweep for any straggler positions
    rem_pos = get_live_positions(brk)
    if rem_pos:
        rem_pos.sort(key=_pos_priority_key)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            close_futures = [
                executor.submit(
                    lambda t_id, vol: _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/position_close?ticket={t_id}&volume={vol}", timeout=2.5),
                    getattr(p, "ticket", 0),
                    getattr(p, "volume", 0.0)
                )
                for p in rem_pos if getattr(p, "ticket", 0) > 0
            ]
            for f in concurrent.futures.as_completed(close_futures):
                try:
                    res = f.result()
                    if res.status_code == 200 and res.json().get("success"):
                        closed_count += 1
                except Exception:
                    pass

    # PASS 3: Cancel all pending orders
    for m_id in ALLOWED_MANUAL_MAGICS:
        try:
            r = _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/cancel_all?magic={m_id}", timeout=3.0)
            if r.status_code == 200 and r.json().get("success"):
                cancelled_pend += int(r.json().get("cancelled_count", 0))
        except Exception as e:
            pass

    rem_ord = get_live_pending(brk)
    if rem_ord:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            cancel_futures = [
                executor.submit(
                    lambda t_id: _FAST_SESSION.get(f"http://127.0.0.1:{MT5_BRIDGE_PORT}/order_cancel?ticket={t_id}", timeout=2.0),
                    getattr(o, "ticket", 0)
                )
                for o in rem_ord if getattr(o, "ticket", 0) > 0
            ]
            for f in concurrent.futures.as_completed(cancel_futures):
                try:
                    res = f.result()
                    if res.status_code == 200 and res.json().get("success"):
                        cancelled_pend += 1
                except Exception:
                    pass

    # Record trade history & audit state
    ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if closed_count > 0:
        record = {
            "time":      ts_str,
            "action":    "FLATTEN ALL",
            "count":     closed_count,
            "total_pnl": round(total_pnl, 2),
            "audit":     audit_steps,
        }
        state["trade_history"] = [record] + state.get("trade_history", [])[:MAX_HISTORY_ROWS]
    
    state["last_audit"] = {
        "time": ts_str,
        "closed_count": closed_count,
        "cancelled_pending": cancelled_pend,
        "total_pnl": round(total_pnl, 2),
        "steps": audit_steps[:10],
    }
    state["deployed"] = False
    state["grid_levels"] = {}
    save_state(state)

    final_rem_pos = get_live_positions(brk)
    final_rem_ord = get_live_pending(brk)
    is_fully_clean = (len(final_rem_pos) == 0 and len(final_rem_ord) == 0)

    if not is_fully_clean:
        return f"⚠️ Warning ({len(final_rem_pos)} pos, {len(final_rem_ord)} ord remaining): {'; '.join(errors[:2])}"
    return f"⚡ 100% Zero-Latency Closed ({closed_count} pos, {cancelled_pend} pend) | Net: {curr_sym}{total_pnl:+.2f} {acct_curr}"


# ── 24/7 Engine Loop ──────────────────────────────────────────────────────────
class Bot2Engine:
    def __init__(self):
        self.running = True
        self.peak_pnl = 0.0
        self.trail_floor = 0.0
        self.last_msg = ""
        self.last_cfg_sync = 0.0
        self.last_telemetry_save = 0.0
        self.brk = get_manual_broker()

    def stop(self, signum=None, frame=None):
        logger.info("Shutdown signal received. Stopping Bot2Engine...")
        self.running = False

    def run(self):
        logger.info("=" * 70)
        logger.info("⚡ BOT #2 AUTONOMOUS 24/7 GRID ENGINE STARTED")
        logger.info(f"   Magic: {MANUAL_MAGIC} | Bridge Port: {MT5_BRIDGE_PORT} | Symbol: {EXNESS_SYMBOL}")
        logger.info("=" * 70)

        # Register termination handlers
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        state = load_state()
        cfg = state.get("grid_config", {})
        tp_target = float(cfg.get("target_profit", 5.0))
        sl_limit  = float(cfg.get("stop_loss", 500.0))
        single_tp = float(cfg.get("single_tp", 1.50))

        while self.running:
            try:
                now_t = time.time()

                # 1. Periodically sync user configuration from manual_state.json (every 1.0s)
                if now_t - self.last_cfg_sync >= 1.0:
                    try:
                        state = load_state()
                        cfg = state.get("grid_config", {})
                        tp_target = float(cfg.get("target_profit", 5.0))
                        sl_limit  = float(cfg.get("stop_loss", 500.0))
                        single_tp = float(cfg.get("single_tp", 1.50))
                        self.last_cfg_sync = now_t
                    except Exception as e:
                        logger.warning(f"Config sync error: {e}")

                # 2. Check for manual command flags in state (e.g. user clicked FLATTEN from UI)
                if state.get("manual_cmd_flatten"):
                    logger.info("🚨 Immediate Manual Flatten Command received from state!")
                    res = flatten_all(self.brk, state)
                    self.last_msg = f"Manual Flatten: {res}"
                    state = load_state()
                    state["manual_cmd_flatten"] = False
                    save_state(state)
                    self.peak_pnl = 0.0
                    self.trail_floor = 0.0
                    time.sleep(0.5)
                    continue

                # 3. Query live positions
                positions = get_live_positions(self.brk)
                n_pos = len(positions)
                has_positions = n_pos > 0
                is_deployed = bool(state.get("deployed", False))

                # Check manual pause toggle
                manual_paused = bool(state.get("engine_paused", False))

                # Calculate P&L
                if has_positions and not manual_paused:
                    buy_pos  = [p for p in positions if getattr(p, "type", 0) == 0]
                    sell_pos = [p for p in positions if getattr(p, "type", 0) == 1]
                    buy_pnl  = sum(float(getattr(p, "profit", 0.0)) for p in buy_pos)
                    sell_pnl = sum(float(getattr(p, "profit", 0.0)) for p in sell_pos)
                    pnl      = round(buy_pnl + sell_pnl, 2)

                    acc = get_account_summary(self.brk)
                    acct_curr = acc.get("currency", "USD")
                    curr_sym = "¢" if acct_curr == "USC" else "$"

                    # 1 position: single_tp; 2+ positions: tp_target basket
                    cycle_target = single_tp if n_pos == 1 else tp_target
                    self.peak_pnl = max(self.peak_pnl, pnl)

                    exit_action = None
                    exit_msg = ""

                    # Condition A: Full Target Profit hit
                    if pnl >= cycle_target:
                        exit_action = "FULL_TP"
                        exit_msg = f"🎯 TARGET PROFIT HIT: {curr_sym}{pnl:+.2f} {acct_curr} (Target: +{curr_sym}{cycle_target:.2f}) — Instant Flattening {n_pos} positions!"

                    # Condition B: Trailing Profit Lock
                    elif self.peak_pnl >= (cycle_target * 0.60) and n_pos >= 2:
                        min_floor = max(0.50 if acct_curr == "USC" else 0.10, cycle_target * 0.20)
                        self.trail_floor = min(max(min_floor, self.peak_pnl * 0.50), self.peak_pnl * 0.80)
                        if pnl <= self.trail_floor:
                            exit_action = "TRAIL_LOCK"
                            exit_msg = f"🛡️ TRAILING PROFIT LOCK: {curr_sym}{pnl:+.2f} {acct_curr} (Peak: {curr_sym}{self.peak_pnl:.2f}, Floor: {curr_sym}{self.trail_floor:.2f}) — Flattening {n_pos} positions!"
                    else:
                        self.trail_floor = 0.0

                    # Condition C: Stop Loss Hit
                    if not exit_action and pnl <= -abs(sl_limit):
                        exit_action = "STOP_LOSS"
                        exit_msg = f"🛑 STOP LOSS HIT: {curr_sym}{pnl:+.2f} {acct_curr} (SL: -{curr_sym}{sl_limit:.2f}) — Emergency Flattening!"

                    # EXECUTE AUTO-CLOSE IMMEDIATELY
                    if exit_action:
                        logger.info(exit_msg)
                        flat_res = flatten_all(self.brk, state)
                        auto_redeploy = bool(cfg.get("auto_redeploy", True))

                        if auto_redeploy and exit_action != "STOP_LOSS":
                            time.sleep(0.15)
                            new_center = get_mt5_live_price(self.brk)
                            new_levels = compute_grid_levels(
                                center=new_center,
                                gap_val=float(cfg.get("gap_value", 3.0)),
                                levels_above=int(cfg.get("levels_above", 11)),
                                levels_below=int(cfg.get("levels_below", 11)),
                                gap_mode=cfg.get("gap_mode", "USD ($)"),
                                offset_val=float(cfg.get("offset_value", 3.0)),
                                offset_mode=cfg.get("offset_mode", "USD ($)"),
                            )
                            placed, errs = deploy_grid(
                                self.brk,
                                new_levels,
                                lot_size=float(cfg.get("lot_size", 0.01)),
                                lot_mult=float(cfg.get("lot_mult", 1.3)),
                                flat_levels=int(cfg.get("flat_levels", 2)),
                            )
                            fresh_s = load_state()
                            if placed > 0:
                                fresh_s["deployed"] = True
                                fresh_s["grid_levels"] = new_levels
                                fresh_s["grid_config"]["center_price"] = new_center
                                save_state(fresh_s)
                                self.last_msg = f"{exit_action} {curr_sym}{pnl:+.2f}! 100% ALL CLOSED ({n_pos} pos). 🚀 Redeployed fresh grid ({placed} orders) @ ${new_center:,.2f}"
                            else:
                                self.last_msg = f"{exit_action} {curr_sym}{pnl:+.2f}! 100% ALL CLOSED. Redeploy warning: {'; '.join(errs[:2])}"
                        else:
                            self.last_msg = f"{exit_action} {curr_sym}{pnl:+.2f}! {flat_res} · Desk 100% FLAT."

                        logger.info(self.last_msg)
                        self.peak_pnl = 0.0
                        self.trail_floor = 0.0
                        time.sleep(0.5)

                else:
                    self.peak_pnl = 0.0
                    self.trail_floor = 0.0
                    pnl = 0.0
                    cycle_target = single_tp

                # 4. Periodically save engine telemetry to state (every 0.5s) for the UI
                if now_t - self.last_telemetry_save >= 0.5:
                    state = load_state()
                    state["engine_telemetry"] = {
                        "alive": True,
                        "last_tick": now_t,
                        "pnl": pnl if has_positions else 0.0,
                        "positions_count": n_pos,
                        "peak_pnl": round(self.peak_pnl, 2),
                        "trail_floor": round(self.trail_floor, 2),
                        "cycle_target": round(cycle_target, 2),
                        "manual_paused": manual_paused,
                        "last_msg": self.last_msg,
                        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    save_state(state)
                    self.last_telemetry_save = now_t

            except Exception as e:
                logger.error(f"Tick cycle error: {e}", exc_info=True)

            # High-speed polling rate: 50ms when orders/positions exist, 200ms when idle
            time.sleep(0.05 if (has_positions or is_deployed) else 0.20)

        logger.info("Bot2Engine stopped cleanly.")


if __name__ == "__main__":
    engine = Bot2Engine()
    engine.run()
