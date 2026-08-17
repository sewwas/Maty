"""
Profity AI — Standalone 24/7 VPS Background Bot Daemon Service
Runs trading logic continuously in background without needing any open browser or Streamlit tab.
Reads & synchronizes commands with bot_state.pkl.
"""

import time
import os
import pickle
import logging
from typing import Dict

# Core imports
import core.data
import core.engine
import core.mt5_broker
import core.license
import core.signals

from core.mt5_broker import MT5Broker, SimulatedBroker, MT5_AVAILABLE, get_symbol_magic_number
from core.engine import BreakoutGridBot
from core.data import get_live_price, get_default_price

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot_service.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "bot_state.pkl")
LOCK_PATH = os.path.join(BASE_DIR, "bot_service.lock")

_symbols = ["PAXGUSDT", "GBPUSD", "EURUSD", "USDJPY", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]

_golden_sweet_spots = {
    "PAXGUSDT": {"gap": 0.07, "offset": 0.07, "size": 0.01,  "tp": 10.0, "mult": 1.25},
    "GBPUSD":   {"gap": 0.05, "offset": 0.05, "size": 0.02,  "tp": 9.0,  "mult": 1.25},
    "EURUSD":   {"gap": 0.05, "offset": 0.05, "size": 0.02,  "tp": 8.0,  "mult": 1.25},
    "USDJPY":   {"gap": 0.05, "offset": 0.05, "size": 0.02,  "tp": 9.0,  "mult": 1.25},
    "BTCUSDT":  {"gap": 0.02, "offset": 0.015, "size": 0.04, "tp": 10.0, "mult": 1.25},
    "ETHUSDT":  {"gap": 0.04, "offset": 0.02, "size": 1.00,  "tp": 10.0, "mult": 1.25},
    "SOLUSDT":  {"gap": 0.07, "offset": 0.07, "size": 1.50,  "tp": 10.0, "mult": 1.25},
    "BNBUSDT":  {"gap": 0.07, "offset": 0.07, "size": 0.20,  "tp": 10.0, "mult": 1.25},
    "DOGEUSDT": {"gap": 0.07, "offset": 0.07, "size": 100.0, "tp": 10.0, "mult": 1.25},
}

def load_saved_state() -> Dict[str, dict]:
    if os.path.exists(STATE_PATH):
        for _ in range(3):
            try:
                with open(STATE_PATH, "rb") as f:
                    data = pickle.load(f)
                    if isinstance(data, dict):
                        return data.get("markets", {})
            except Exception:
                time.sleep(0.05)
    return {}

def save_state(markets: dict):
    now = time.time()
    try:
        state_data = {
            "timestamp": now,
            "markets": {}
        }
        for sym_code, m_data in markets.items():
            brk = m_data.get("broker")
            bot = m_data.get("bot")
            trade_hist = list(getattr(brk, "closed_trades", [])) if brk else []
            if not trade_hist and bot and hasattr(bot, "cycle_history"):
                trade_hist = list(getattr(bot, "cycle_history", []))
            state_data["markets"][sym_code] = {
                "running": m_data.get("running", False),
                "last_price": m_data.get("last_price", 0.0),
                "trade_history": trade_hist,
                "realized_pnl": getattr(brk, "realized_pnl", 0.0) if brk else 0.0,
                "cycle_history": getattr(bot, "cycle_history", []) if bot else []
            }
        # Safe retry write on Windows to handle file lock contention cleanly
        for attempt in range(3):
            try:
                with open(STATE_PATH, "wb") as f:
                    pickle.dump(state_data, f)
                break
            except (PermissionError, OSError):
                time.sleep(0.05)
    except Exception as e:
        logging.error(f"Error saving state: {e}")

def main():
    logging.info("Starting Profity AI 24/7 Background Bot Service...")
    use_mt5 = MT5_AVAILABLE
    saved_state = load_saved_state()

    markets = {}
    for sym in _symbols:
        magic = get_symbol_magic_number(sym)
        brk = MT5Broker(symbol=sym, magic_number=magic) if use_mt5 else SimulatedBroker(symbol=sym, magic_number=magic)
        g_cfg = _golden_sweet_spots.get(sym, {"gap": 0.07, "offset": 0.07, "size": 0.01, "tp": 10.0, "mult": 1.5})
        
        bot = BreakoutGridBot(
            broker=brk,
            symbol=sym,
            grid_gap=g_cfg["gap"],
            trap_offset=g_cfg["offset"],
            grid_levels=5,
            order_size=g_cfg["size"],
            order_size_multiplier=g_cfg["mult"],
            target_profit=g_cfg["tp"],
            is_percent=True,
            max_cycle_duration=float("inf"),
            auto_restart=True,
            use_auto_reading=True
        )
        init_px = get_default_price(sym)
        
        m_info = saved_state.get(sym, {})
        has_orders = bool(brk and (len(getattr(brk, "open_positions", {})) > 0 or len(getattr(brk, "pending_orders", {})) > 0))
        is_running = bool(m_info.get("running", False)) if isinstance(m_info, dict) else has_orders

        if is_running:
            bot.auto_restart = True
            bot.use_breakeven = False
            bot.use_trailing_stop = True
            bot.trailing_stop_distance = 0.35
            if not bot.deployed:
                live_px = get_live_price(sym) or init_px
                try:
                    bot.deploy_traps(live_px, time.time(), force=True)
                    logging.info(f"[{sym}] Startup Trap Deployment: {len(brk.pending_orders)} traps placed @ {live_px}")
                except Exception as e:
                    logging.error(f"[{sym}] Startup deploy error: {e}")

        markets[sym] = {
            "broker": brk,
            "bot": bot,
            "running": is_running,
            "last_price": init_px,
            "price_history": [(time.time(), init_px)]
        }

    logging.info(f"Initialized {len(markets)} pairs. Starting 24/7 execution loop...")

    try:
        while True:
            now = time.time()
            
            # Update lock timestamp so app.py knows service is alive
            with open(LOCK_PATH, "w") as lf:
                lf.write(str(now))

            # Sync external commands from bot_state.pkl (e.g. start/stop from Streamlit UI)
            disk_state = load_saved_state()
            for sym, disk_info in disk_state.items():
                if sym in markets and isinstance(disk_info, dict):
                    disk_running = disk_info.get("running", False)
                    if markets[sym]["running"] != disk_running:
                        markets[sym]["running"] = disk_running
                        logging.info(f"[{sym}] State updated from UI: running={disk_running}")
                        
                        if disk_running:
                            import MetaTrader5 as mt5_ref
                            brk_inst = markets[sym]["broker"]
                            ex_s = brk_inst.get_exness_symbol(sym) if hasattr(brk_inst, "get_exness_symbol") else sym
                            active_mt5_ords = mt5_ref.orders_get(symbol=ex_s) if (mt5_ref.initialize() and ex_s) else None
                            active_mt5_poss = mt5_ref.positions_get(symbol=ex_s) if (mt5_ref.initialize() and ex_s) else None
                            
                            if not active_mt5_ords and not active_mt5_poss:
                                markets[sym]["bot"].deployed = False
                                live_px = get_live_price(sym) or markets[sym]["last_price"]
                                try:
                                    markets[sym]["bot"].deploy_traps(live_px, now, force=False)
                                    logging.info(f"[{sym}] Auto-healing trap deployment @ {live_px}")
                                except Exception as e:
                                    logging.error(f"[{sym}] Trap deploy error: {e}")

            # Process Ticks
            for sym, m_data in markets.items():
                live_p = get_live_price(sym)
                if live_p and live_p > 0:
                    m_data["last_price"] = live_p
                    m_data["price_history"].append((now, live_p))
                    if len(m_data["price_history"]) > 100:
                        m_data["price_history"] = m_data["price_history"][-100:]

                if m_data.get("running", False):
                    try:
                        cur_p = m_data["last_price"]
                        hist = m_data["price_history"]
                        prev_p = hist[-2][1] if len(hist) >= 2 else cur_p
                        
                        m_data["bot"].process_tick(prev_p, cur_p, now)
                    except Exception as tick_err:
                        logging.error(f"[{sym}] Tick error: {tick_err}")

            save_state(markets)
            time.sleep(2.0)

    except KeyboardInterrupt:
        logging.info("Shutting down bot service...")
    finally:
        if os.path.exists(LOCK_PATH):
            try:
                os.remove(LOCK_PATH)
            except Exception:
                pass

if __name__ == "__main__":
    main()
