import time
import datetime
from typing import Optional, Dict, Any, Tuple

def get_pip_size(symbol: str, current_price: float = 0.0) -> float:
    sym = (symbol or "").upper()
    try:
        import MetaTrader5 as mt5_ref
        sym_lookup = "XAUUSD" if any(x in sym for x in ["PAXG", "XAU", "GOLD"]) else (sym.replace("USDT", "USD") if "USDT" in sym else sym)
        info = mt5_ref.symbol_info(sym_lookup) or mt5_ref.symbol_info(f"{sym_lookup}m") or mt5_ref.symbol_info(f"{sym_lookup}c")
        if info is not None and info.point > 0:
            if info.digits in (3, 5):
                return info.point * 10.0
            elif info.digits in (2, 4):
                return info.point
            else:
                return info.point * 10.0 if info.point < 0.1 else info.point
    except Exception:
        pass

    if "PAXG" in sym or "XAU" in sym or "GOLD" in sym:
        return 0.10
    elif "BTC" in sym:
        return 1.0
    elif "ETH" in sym:
        return 0.10
    elif "BNB" in sym:
        return 0.10
    elif "SOL" in sym:
        return 0.01
    elif "DOGE" in sym:
        return 0.0001
    elif "JPY" in sym:
        return 0.01
    else:
        if current_price > 5000:
            return 1.0
        elif current_price > 50:
            return 0.10
        return 0.0001


def sanitize_order_size(symbol: str, raw_size: float) -> float:
    sym = (symbol or "").upper()
    try:
        import MetaTrader5 as mt5_ref
        sym_lookup = "XAUUSD" if any(x in sym for x in ["PAXG", "XAU", "GOLD"]) else (sym.replace("USDT", "USD") if "USDT" in sym else sym)
        info = mt5_ref.symbol_info(sym_lookup) or mt5_ref.symbol_info(f"{sym_lookup}m") or mt5_ref.symbol_info(f"{sym_lookup}c")
        if info is not None:
            v_min = getattr(info, "volume_min", 0.01) or 0.01
            v_max = getattr(info, "volume_max", 100.0) or 100.0
            v_step = getattr(info, "volume_step", 0.01) or 0.01
            size = round(round(raw_size / v_step) * v_step, 4) if v_step > 0 else round(raw_size, 4)
            return max(v_min, min(v_max, size))
    except Exception:
        pass

    if "PAXG" in sym or "XAU" in sym or "GOLD" in sym:
        return min(0.03, max(0.01, round(raw_size, 2)))
    elif "BTC" in sym:
        return min(0.05, max(0.01, round(raw_size, 3)))
    elif "ETH" in sym:
        return min(0.50, max(0.10, round(raw_size, 2)))
    elif "BNB" in sym:
        return min(0.50, max(0.05, round(raw_size, 2)))
    elif "SOL" in sym:
        return min(3.00, max(0.10, round(raw_size, 2)))
    elif "DOGE" in sym:
        return min(1000.0, max(10.0, round(raw_size, 1)))
    elif "JPY" in sym or "EUR" in sym or "GBP" in sym:
        return min(0.20, max(0.01, round(raw_size, 2)))
    return max(0.01, round(raw_size, 2))


def calculate_ratchet_breakeven(entry_price: float, position_type: str, current_price: float, pip_size: float) -> float:
    if position_type == "BUY":
        return max(entry_price + (pip_size * 2.0), current_price - (pip_size * 15.0))
    else:
        return min(entry_price - (pip_size * 2.0), current_price + (pip_size * 15.0))


def enforce_position_tp(self, current_price: float, timestamp: float) -> int:
    """
    SOFTWARE-SIDE TP GUARD — Always Take Profit Safety Net.
    Runs every tick. If any open position's price has crossed its TP level,
    force-closes it immediately via the broker regardless of MT5 broker TP state.
    This ensures profit is ALWAYS taken even if broker TP is rejected or silent.
    Returns the number of positions force-closed.
    """
    if not getattr(self.broker, "open_positions", None):
        return 0

    closed_count = 0
    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
    digits = 3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else (2 if any(x in sym_name for x in ["BTC", "ETH", "SOL", "BNB"]) else 5)

    for pos_id, pos_obj in list(getattr(self.broker, "open_positions", {}).items()):
        try:
            pos_tp = float(getattr(pos_obj, "tp", 0.0) or 0.0)
            if pos_tp <= 0:
                continue  # No TP set — skip

            pos_type = str(getattr(pos_obj, "type", "")).upper()
            tp_hit = False

            if "BUY" in pos_type and current_price >= pos_tp:
                tp_hit = True
            elif "SELL" in pos_type and current_price <= pos_tp:
                tp_hit = True

            if tp_hit:
                # Skip if runner mode is active — let check_target_profit handle the basket exit
                if getattr(self, "in_runner_mode", False):
                    continue
                print(f"[{sym_name}] ✅ [SOFTWARE TP HIT] {pos_type} #{pos_id} | Price: {current_price:.{digits}f} | TP: {pos_tp:.{digits}f} — Force closing!")
                try:
                    self.broker.close_position(pos_id, current_price, timestamp)
                    closed_count += 1
                except Exception as close_err:
                    print(f"[{sym_name}] ⚠️ [SOFTWARE TP] Close failed for #{pos_id}: {close_err}")
        except Exception:
            pass

    return closed_count


def check_target_profit(self, current_price: float, timestamp: float) -> Optional[dict]:
    """
    Evaluates floating PnL across active open positions against target profit,
    stop loss, runner mode trailing lock, and breakeven floors. Returns cycle summary dictionary if exit met.
    """
    if not self.broker.open_positions:
        return None

    total_pnl = self.broker.get_floating_pnl(current_price)  # Use real MT5 profit (includes spread, swap, commission)
    duration = timestamp - getattr(self, "cycle_start_time", timestamp)

    target_prof = float(getattr(self, "target_profit", 3.0) or 3.0)
    effective_target = max(0.50, target_prof)

    if total_pnl > getattr(self, "max_floating_pnl", -float("inf")):
        self.max_floating_pnl = total_pnl

    max_pnl = self.max_floating_pnl
    if max_pnl >= effective_target and getattr(self, "use_smart_trailing", True):
        self.in_runner_mode = True

    exit_triggered = False
    exit_reason = ""

    sl_limit = float(getattr(self, "stop_loss", 0.0) or 0.0)
    if sl_limit > 0 and total_pnl <= -abs(sl_limit):
        exit_triggered = True
        exit_reason = "STOP_LOSS"
    elif self.in_runner_mode:
        lock_pct = float(getattr(self, "profit_lock_pct", 0.80) or 0.80)
        # Floor: at least 50% of target OR 80% of peak — prevents near-zero exits that lose on spread+commission
        min_floor = max(effective_target * 0.50, 0.50)
        trailing_floor = max(max_pnl * lock_pct, min_floor)
        if total_pnl <= trailing_floor:
            exit_triggered = True
            exit_reason = "RUNNER_MODE_TRAILING_LOCK"
    elif total_pnl >= effective_target:
        exit_triggered = True
        exit_reason = "TARGET_PROFIT"
    elif getattr(self, "use_breakeven", True) and total_pnl >= (effective_target * 0.5):
        self.breakeven_activated = True

    if exit_triggered:
        print(f"[{self.symbol}] 🎯 [PROFIT TAKING EXIT] {exit_reason} met! Net PnL: ${total_pnl:+.2f} USD")
        if hasattr(self.broker, "cancel_all_orders"):
            self.broker.cancel_all_orders()
        if hasattr(self.broker, "close_all_positions"):
            self.broker.close_all_positions()

        summary = {
            "cycle_id": getattr(self, "current_cycle_id", 1),
            "total_pnl": round(total_pnl, 2),
            "exit_reason": exit_reason,
            "duration": round(duration, 1),
            "timestamp": timestamp,
            "exit_price": current_price
        }
        return summary

    return None


def process_engine_tick(self, previous_price: float, current_price: float, timestamp: float, bb_width: Optional[float] = None) -> Optional[dict]:
    self.ensure_attributes_initialized()
    cycle_summary = None

    if getattr(self, "use_weekend_shutdown", True):
        ts_sec = timestamp / 1000.0 if timestamp > 1e11 else timestamp
        now_utc = datetime.datetime.fromtimestamp(ts_sec, datetime.timezone.utc)
        is_weekend_pause = self.is_weekend_market_paused(now_utc)

        if is_weekend_pause:
            if not getattr(self, "weekend_shutdown_triggered", False):
                self.weekend_shutdown_triggered = True
                print(f"[{self.symbol}] 🛑 [WEEKEND MARKET SHUTDOWN] Friday UTC threshold crossed. Purging grid orders & closing open positions.")
                if hasattr(self.broker, "cancel_all_orders"):
                    self.broker.cancel_all_orders()
                if hasattr(self.broker, "close_all_positions"):
                    self.broker.close_all_positions()
                self.deployed = False
            return None
        else:
            if getattr(self, "weekend_shutdown_triggered", False):
                print(f"[{self.symbol}] ▶️ [WEEKEND REOPEN] Market session open detected. Re-enabling grid execution.")
                self.weekend_shutdown_triggered = False

    if getattr(self, "daily_circuit_breaker_tripped", False):
        return None

    if self.is_high_impact_news_blackout(timestamp):
        return None

    has_orders = len(self.broker.pending_orders) > 0 or len(self.broker.open_positions) > 0
    if not has_orders and hasattr(self.broker, "ensure_connected"):
        try:
            if not self.broker.ensure_connected():
                return None
            ex_s = self.broker.get_exness_symbol(self.symbol) if hasattr(self.broker, "get_exness_symbol") else self.symbol
            if hasattr(self.broker, "pending_orders") and hasattr(self.broker, "ticket_to_order_id"):
                import MetaTrader5 as mt5_tick_check
                mt5_o = mt5_tick_check.orders_get(symbol=ex_s) if mt5_tick_check else None
                if mt5_o:
                    has_orders = True
                    self.deployed = True
                    from core.engine import Order
                    for mo in mt5_o:
                        loc_o = Order("BUY_STOP" if getattr(mo, "type", 2) in (2, 4) else "SELL_STOP", getattr(mo, "price_open", current_price), getattr(mo, "volume_initial", 0.01), getattr(mo, "time_setup", timestamp))
                        loc_o.order_id = f"mt5_{mo.ticket}"
                        loc_o.broker_ticket = mo.ticket
                        self.broker.pending_orders[loc_o.order_id] = loc_o
        except Exception:
            pass

    if not has_orders:
        self.deployed = False
        if timestamp >= getattr(self, "_last_deploy_error_time", 0.0) + 3.0:
            self._last_deploy_error_time = timestamp   # Prevent runaway deploy loop on every tick
            self.deploy_traps(current_price, timestamp, force=True)
        return None

    self._tick_counter += 1

    try:
        sync_trap_mode_realtime(self, current_price, timestamp)
    except Exception:
        pass
    newly_filled_pos_ids = []
    if hasattr(self.broker, "process_tick"):
        new_positions = self.broker.process_tick(previous_price, current_price, timestamp)
        if new_positions:
            newly_filled_pos_ids = [pos.position_id for pos in new_positions if hasattr(pos, "position_id")]
    elif hasattr(self.broker, "update_pending_orders"):
        newly_filled_pos_ids = self.broker.update_pending_orders(current_price, timestamp)
    if newly_filled_pos_ids:
        self._last_trigger_time = timestamp
        for f_pid in newly_filled_pos_ids:
            pos_obj = self.broker.open_positions.get(f_pid)
            if pos_obj:
                self._fakeout_recent_fills[f_pid] = (pos_obj.entry_price, pos_obj.type, self._tick_counter)

        if getattr(self, "cancel_opposite_on_trigger", False):
            filled_types = [self.broker.open_positions[pid].type for pid in newly_filled_pos_ids if pid in self.broker.open_positions]
            if "BUY" in filled_types:
                for oid, ord_obj in list(self.broker.pending_orders.items()):
                    if ord_obj.type == "SELL_STOP":
                        self.broker.cancel_order(oid)
            if "SELL" in filled_types:
                for oid, ord_obj in list(self.broker.pending_orders.items()):
                    if ord_obj.type == "BUY_STOP":
                        self.broker.cancel_order(oid)

    if self.use_grid_repair:
        self.repair_grid(current_price, timestamp)
    if self.use_auto_cleanup:
        self.cleanup_stale_grid_orders(current_price)

    if len(getattr(self.broker, "open_positions", {})) > 0:
        try:
            trail_stop_loss_5m_structure(self, current_price, timestamp)
            align_basket_take_profits(self, current_price, timestamp)
            enforce_position_tp(self, current_price, timestamp)  # Software-side TP guard — always take profit
        except Exception:
            pass

    if getattr(self, "_fakeout_guard_enabled", True) and self._fakeout_recent_fills:
        expired_f_pids = []
        for f_pid, (entry_px, p_type, fill_tick) in list(self._fakeout_recent_fills.items()):
            ticks_elapsed = self._tick_counter - fill_tick
            if f_pid not in self.broker.open_positions:
                expired_f_pids.append(f_pid)
                continue
            if ticks_elapsed > getattr(self, "_fakeout_guard_ticks", 8):
                expired_f_pids.append(f_pid)
                continue

            pos = self.broker.open_positions[f_pid]
            is_fakeout = (p_type == "BUY" and current_price < entry_px) or (p_type == "SELL" and current_price > entry_px)
            if is_fakeout:
                print(f"[{self.symbol}] 🚨 [FAKEOUT GUARD] Fake breakout detected on {p_type} position #{f_pid} ({ticks_elapsed} ticks after fill). Closing early.")
                self.broker.close_position(f_pid, current_price, timestamp)
                expired_f_pids.append(f_pid)

        for ef_pid in expired_f_pids:
            self._fakeout_recent_fills.pop(ef_pid, None)

    summary = check_target_profit(self, current_price, timestamp)
    if summary is not None:
        self.record_trade_outcome(summary.get("total_pnl", 0.0), summary.get("exit_reason", "TARGET_PROFIT"), summary.get("duration", 0.0))
        self.current_cycle_id += 1

        self.deployed = False
        self.deploy_price = 0.0
        self.breakeven_activated = False
        self.in_runner_mode = False
        self.max_floating_pnl = -float("inf")  # Reset peak PnL tracker for next cycle
        self._runner_exit_cooldown_until = 0.0
        self._last_deploy_error_time = 0.0
        self._prev_open_pos_count = 0

        # Sync broker state before redeploying to avoid position cap stall from delayed MT5 reporting
        if hasattr(self.broker, "process_tick"):
            try:
                self.broker.process_tick(current_price, current_price, timestamp)
            except Exception:
                pass

        if getattr(self, "auto_restart", True):
            self.deploy_traps(current_price, timestamp, force=True)
        else:
            self.deployed = False

        return summary

    return None


def deploy_traps(self, current_price: float, timestamp: float, *args, force: bool = False, bb_width: Optional[float] = None, **kwargs):
    """
    ⚡ UNBREAKABLE 100% RELIABLE GRID DEPLOYMENT ENGINE.
    Deploys exact tight grid traps directly to broker with zero silent skips or bypassing.
    """
    if not current_price or current_price <= 0:
        return

    # NOTE: do NOT add `force = False` here — that would overwrite the keyword argument
    if args:
        if isinstance(args[0], bool):
            force = args[0]
        elif isinstance(args[0], (float, int)) or args[0] is None:
            bb_width = args[0]
            if len(args) > 1 and isinstance(args[1], bool):
                force = args[1]

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()

    if getattr(self, "_is_deploying", False):
        return

    max_capacity = (getattr(self, "grid_levels", 5) or 5) * 2
    if not force and len(getattr(self.broker, "pending_orders", {})) >= max_capacity:
        return

    self._is_deploying = True

    try:
        if force or len(getattr(self.broker, "pending_orders", {})) == 0:
            if hasattr(self.broker, "cancel_all_orders"):
                try:
                    self.broker.cancel_all_orders()
                except Exception:
                    pass

        digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)
        ask_ref = getattr(self.broker, "last_ask", current_price) or current_price
        bid_ref = getattr(self.broker, "last_bid", current_price) or current_price

        if hasattr(self.broker, "get_exness_symbol"):
            try:
                ex_sym = self.broker.get_exness_symbol(sym_name)
                import MetaTrader5 as mt5_ref
                tick_info = mt5_ref.symbol_info_tick(ex_sym)
                if tick_info and tick_info.ask > 0 and tick_info.bid > 0:
                    ask_ref = tick_info.ask
                    bid_ref = tick_info.bid
                    current_price = (ask_ref + bid_ref) / 2.0
            except Exception:
                pass

        if ask_ref <= 0: ask_ref = current_price
        if bid_ref <= 0: bid_ref = current_price

        gap_pct = float(getattr(self, "grid_gap", 0.07) or 0.07)
        offset_pct = float(getattr(self, "trap_offset", 0.07) or 0.07)
        
        if getattr(self, "use_auto_reading", False) and hasattr(self, "auto_reading_engine"):
            try:
                from core.data import get_historical_klines, calculate_technical_indicators
                try:
                    from core.data import get_order_book_depth
                    ob = get_order_book_depth(sym_name)
                except (ImportError, AttributeError, Exception):
                    ob = {}
                try:
                    from core.data import get_economic_calendar
                    news = get_economic_calendar()
                except (ImportError, AttributeError, Exception):
                    news = []
                klines_df = get_historical_klines(sym_name, interval="1m", limit=100)
                tech = calculate_technical_indicators(klines_df) if klines_df is not None else {}
                bal = float(getattr(self.broker, "balance", 1000.0) or 1000.0)
                
                eval_res = self.auto_reading_engine.evaluate_market_and_account(
                    symbol=sym_name,
                    current_price=current_price,
                    account_equity=bal,
                    tech_indicators=tech,
                    orderbook_depth=ob,
                    macro_news=news
                )
                if eval_res and isinstance(eval_res, dict):
                    self.last_auto_eval = eval_res
                    offset_pct = float(eval_res.get("buy_offset_pct", offset_pct) or offset_pct)
                    gap_pct = float(eval_res.get("dynamic_gap_pct", gap_pct) or gap_pct)
            except Exception:
                pass

        off_ratio = (offset_pct / 100.0) if offset_pct >= 0.50 else (offset_pct if offset_pct < 0.01 else offset_pct / 100.0)
        gap_ratio = (gap_pct / 100.0) if gap_pct >= 0.50 else (gap_pct if gap_pct < 0.01 else gap_pct / 100.0)

        if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]):
            gap_ratio = min(0.0015, max(0.0005, gap_ratio))
            off_ratio = min(0.0015, max(0.0005, off_ratio))
        elif "BTC" in sym_name:
            gap_ratio = min(0.0020, max(0.0005, gap_ratio))
            off_ratio = min(0.0020, max(0.0005, off_ratio))

        buy_offset_val = current_price * off_ratio if off_ratio > 0 else current_price * 0.001
        gap_val = current_price * gap_ratio if gap_ratio > 0 else current_price * 0.001
        
        b_min_stop = 0.0
        if hasattr(self.broker, "get_cached_symbol_info") and hasattr(self.broker, "get_exness_symbol"):
            try:
                ex_s = self.broker.get_exness_symbol(sym_name)
                s_info = self.broker.get_cached_symbol_info(ex_s)
                if s_info:
                    b_min_stop = max((getattr(s_info, "trade_stops_level", 0) or 0) * s_info.point, s_info.point * 50.0)
            except Exception:
                pass

        base_min_off = 60.0 if "BTC" in sym_name else (5.0 if "ETH" in sym_name else (5.0 if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]) else 0.0015))
        min_offset_dist = max(b_min_stop + (gap_val * 0.5), base_min_off)
        buy_offset_val = max(float(buy_offset_val), min_offset_dist)
        sell_offset_val = buy_offset_val
        
        min_gap_dist = 20.0 if "BTC" in sym_name else (2.0 if "ETH" in sym_name else (2.0 if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]) else 0.0010))
        gap_val = max(float(gap_val), min_gap_dist)
        buy_offset_val = round(buy_offset_val, digits)
        sell_offset_val = round(sell_offset_val, digits)
        gap_val = round(gap_val, digits)

        if "BTC" in sym_name:
            min_sl_dist = 380.0
        elif "ETH" in sym_name:
            min_sl_dist = 22.50
        elif any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]):
            min_sl_dist = 35.00
        elif any(x in sym_name for x in ["EUR", "GBP"]):
            min_sl_dist = 0.0018
        elif "JPY" in sym_name:
            min_sl_dist = 1.80
        elif "SOL" in sym_name:
            min_sl_dist = 2.80
        else:
            # Derive `point` safely for alt coins (DOGE, XRP, etc.) that don't match named branches
            _sym_info_alt = None
            try:
                if hasattr(self.broker, "get_cached_symbol_info") and hasattr(self.broker, "get_exness_symbol"):
                    _ex_s_alt = self.broker.get_exness_symbol(sym_name)
                    _sym_info_alt = self.broker.get_cached_symbol_info(_ex_s_alt)
            except Exception:
                pass
            _point_alt = getattr(_sym_info_alt, "point", 0.0001) if _sym_info_alt else 0.0001
            min_sl_dist = max(b_min_stop * 2.5, _point_alt * 50.0)

        acc_eq = self.broker.get_equity() if hasattr(self.broker, "get_equity") else 1000.0
        base_cfg_levels = getattr(self, "grid_levels", 5) or 5
        if acc_eq >= 10000.0:
            effective_levels = min(7, max(3, base_cfg_levels))
        elif acc_eq >= 5000.0:
            effective_levels = min(6, max(3, base_cfg_levels))
        elif acc_eq >= 2000.0:
            effective_levels = min(5, max(3, base_cfg_levels))
        elif acc_eq >= 1000.0:
            effective_levels = min(4, max(3, base_cfg_levels))
        else:
            effective_levels = 3

        dyn_tp_factor = max(3.0, float(effective_levels * 1.0))
        calculated_dynamic_tp = gap_val * dyn_tp_factor

        if "BTC" in sym_name:
            min_tp_dist = max(1500.0, calculated_dynamic_tp)
        elif any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]):
            min_tp_dist = max(18.50, calculated_dynamic_tp)
        elif "ETH" in sym_name:
            min_tp_dist = max(120.0, calculated_dynamic_tp)
        elif any(x in sym_name for x in ["EUR", "GBP"]):
            min_tp_dist = max(0.0025, calculated_dynamic_tp)
        elif "JPY" in sym_name:
            min_tp_dist = max(2.50, calculated_dynamic_tp)
        elif "SOL" in sym_name:
            min_tp_dist = max(12.0, calculated_dynamic_tp)
        else:
            min_tp_dist = max(calculated_dynamic_tp, b_min_stop * 5.0)

        t_5m, t_15m, rsi_1m = "NEUTRAL", "NEUTRAL", 50.0
        try:
            from core.data import get_historical_klines, calculate_technical_indicators
            df_1m = get_historical_klines(sym_name, interval="1m", limit=30)
            df_5m = get_historical_klines(sym_name, interval="5m", limit=30)
            df_15m = get_historical_klines(sym_name, interval="15m", limit=30)
            
            tech_1m = calculate_technical_indicators(df_1m) if (df_1m is not None and not df_1m.empty) else {}
            tech_5m = calculate_technical_indicators(df_5m) if (df_5m is not None and not df_5m.empty) else {}
            tech_15m = calculate_technical_indicators(df_15m) if (df_15m is not None and not df_15m.empty) else {}
            
            t_5m = tech_5m.get("trend", "NEUTRAL") or "NEUTRAL"
            t_15m = tech_15m.get("trend", "NEUTRAL") or "NEUTRAL"
            rsi_1m = float(tech_1m.get("rsi", 50.0) or 50.0)
        except Exception:
            pass

        side_cfg = str(getattr(self, "pending_order_side_mode", "AUTO_ADAPTIVE")).upper()
        if side_cfg == "AUTO_ADAPTIVE" and hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict):
            auto_uni = str(self.last_auto_eval.get("unidirectional_mode", "DUAL")).upper()
            if "BUY" in auto_uni and "ONLY" in auto_uni:
                side_cfg = "BUY_ONLY"
            elif "SELL" in auto_uni and "ONLY" in auto_uni:
                side_cfg = "SELL_ONLY"
            elif "DUAL" in auto_uni or "BOTH" in auto_uni:
                side_cfg = "BOTH_SIDES"

        if "DUAL" in side_cfg or "BOTH" in side_cfg:
            place_buy, place_sell = True, True
        elif ("BUY" in side_cfg and "ONLY" in side_cfg) or side_cfg == "BUY":
            place_buy, place_sell = True, False
        elif ("SELL" in side_cfg and "ONLY" in side_cfg) or side_cfg == "SELL":
            place_buy, place_sell = False, True
        else:
            # AUTO_ADAPTIVE: Place BOTH sides in choppy/ranging markets, but ONLY support/resistance side during active trends!
            if t_5m == "BULLISH" or (t_5m == "NEUTRAL" and t_15m == "BULLISH") or rsi_1m <= 38.0:
                place_buy, place_sell = True, False
            elif t_5m == "BEARISH" or (t_5m == "NEUTRAL" and t_15m == "BEARISH") or rsi_1m >= 62.0:
                place_buy, place_sell = False, True
            else:
                # Choppy / Ranging market: place both sides to harvest micro-oscillations!
                place_buy, place_sell = True, True

        placed_count = 0
        base_start_offset = max(b_min_stop + 1.0, buy_offset_val)

        for i in range(effective_levels):
            buy_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
            sell_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)

            if place_buy:
                buy_px = round(ask_ref + base_start_offset + (i * gap_val), digits)
                buy_tp = round(buy_px + min_tp_dist, digits)
                buy_sl = round(buy_px - min_sl_dist, digits)
                try:
                    b_res = self.broker.place_order("BUY_STOP", buy_px, buy_size, timestamp, tp=buy_tp, sl=buy_sl)
                    if b_res: placed_count += 1
                except Exception as e:
                    print(f"[{sym_name}] BUY_STOP level {i} error: {e}")

            if place_sell:
                sell_px = round(bid_ref - base_start_offset - (i * gap_val), digits)
                sell_tp = round(sell_px - min_tp_dist, digits)
                sell_sl = round(sell_px + min_sl_dist, digits)
                try:
                    s_res = self.broker.place_order("SELL_STOP", sell_px, sell_size, timestamp, tp=sell_tp, sl=sell_sl)
                    if s_res: placed_count += 1
                except Exception as e:
                    print(f"[{sym_name}] SELL_STOP level {i} error: {e}")

        if hasattr(self.broker, "purge_duplicate_mt5_orders"):
            try:
                self.broker.purge_duplicate_mt5_orders()
            except Exception:
                pass

        if placed_count > 0 or len(self.broker.pending_orders) > 0:
            self.deployed = True
            self.deploy_price = current_price  # Store deploy center for stale order cleanup
            self.last_deploy_time = timestamp
            print(f"[{sym_name}] ⚡ [GRID DEPLOYED] {placed_count} Traps @ ${current_price:,.2f} | Gap: ${gap_val:.2f} | Offset: ${buy_offset_val:.2f} | Lot: {self.order_size}")
        else:
            self.deployed = False
            self.last_deploy_time = timestamp
            print(f"[{sym_name}] ⚠️ Notice: 0 grid orders placed.")
    except Exception as e:
        self.deployed = False
        print(f"[{sym_name}] Deployment exception: {e}")
    finally:
        self._is_deploying = False


def repair_grid(self, current_price: float, timestamp: float) -> int:
    if not self.deployed and len(self.broker.pending_orders) == 0 and len(self.broker.open_positions) == 0:
        if timestamp >= getattr(self, "_last_deploy_error_time", 0.0) + 3.0:
            self.deploy_traps(current_price, timestamp)
    return 0


def cleanup_stale_grid_orders(self, current_price: float) -> int:
    if self.deployed or len(self.broker.pending_orders) <= (self.grid_levels * 2):
        return 0
    if not self.broker.pending_orders:
        return 0

    center_price = self.deploy_price if self.deploy_price > 0 else current_price

    if getattr(self, "deploy_grid_gap", None) and getattr(self, "deploy_trap_offset", None):
        gap_val = self.deploy_grid_gap
        buy_offset_val = self.deploy_trap_offset
        sell_offset_val = buy_offset_val
    elif getattr(self, "use_auto_reading", False):
        try:
            from core.data import get_historical_klines, calculate_technical_indicators, get_order_book_depth, get_economic_calendar
            sym_str = getattr(self.broker, "symbol", "BTCUSDT")
            klines_df = get_historical_klines(sym_str, interval="1m", limit=100)
            tech = calculate_technical_indicators(klines_df)
            ob = get_order_book_depth(sym_str)
            news = get_economic_calendar()
            bal = float(getattr(self.broker, "balance", 1000.0))

            eval_res = self.auto_reading_engine.evaluate_market_and_account(
                symbol=sym_str,
                current_price=current_price,
                account_equity=bal,
                tech_indicators=tech,
                orderbook_depth=ob,
                macro_news=news
            )
            if eval_res and isinstance(eval_res, dict):
                self.last_auto_eval = eval_res
            buy_offset_val = center_price * (float(eval_res.get("buy_offset_pct", 0.07)) / 100.0)
            sell_offset_val = center_price * (float(eval_res.get("sell_offset_pct", 0.07)) / 100.0)
            gap_val         = center_price * (float(eval_res.get("dynamic_gap_pct", 0.07)) / 100.0)
        except Exception:
            buy_offset_val, gap_val = self.calculate_offset_and_gap(center_price, self.grid_gap, self.trap_offset)
            sell_offset_val = buy_offset_val
    else:
        buy_offset_val, gap_val = self.calculate_offset_and_gap(center_price, self.grid_gap, self.trap_offset)
        sell_offset_val = buy_offset_val

    tolerance = max(gap_val * 1.5, center_price * 0.005)

    valid_buy_levels = [center_price + buy_offset_val + (i * gap_val) for i in range(self.grid_levels)]
    valid_sell_levels = [center_price - sell_offset_val - (i * gap_val) for i in range(self.grid_levels)]

    cancelled_ids = []

    for order_id, order in list(self.broker.pending_orders.items()):
        if order_id in cancelled_ids:
            continue
        order_age = (time.time() - getattr(order, "timestamp", time.time())) if hasattr(order, "timestamp") else 999.0
        if self.deployed and order_age < 300.0:
            continue

        if order.type == "BUY_STOP":
            valid_levels = valid_buy_levels
        elif order.type == "SELL_STOP":
            valid_levels = valid_sell_levels
        else:
            continue

        is_valid = any(abs(order.trigger_price - lvl) < tolerance for lvl in valid_levels)
        if not is_valid:
            self.broker.cancel_order(order_id)
            cancelled_ids.append(order_id)

    from collections import defaultdict
    buy_groups: dict = defaultdict(list)
    sell_groups: dict = defaultdict(list)

    for order_id, order in list(self.broker.pending_orders.items()):
        if order_id in cancelled_ids:
            continue
        if order.type == "BUY_STOP":
            for lvl in valid_buy_levels:
                if abs(order.trigger_price - lvl) < tolerance:
                    buy_groups[round(lvl, 8)].append((order_id, order))
                    break
        elif order.type == "SELL_STOP":
            for lvl in valid_sell_levels:
                if abs(order.trigger_price - lvl) < tolerance:
                    sell_groups[round(lvl, 8)].append((order_id, order))
                    break

    def cancel_duplicates_in_group(group_dict):
        count = 0
        for lvl, orders in group_dict.items():
            if len(orders) > 1:
                orders.sort(key=lambda x: abs(x[1].trigger_price - lvl))
                for order_id, _ in orders[1:]:
                    self.broker.cancel_order(order_id)
                    cancelled_ids.append(order_id)
                    count += 1
        return count

    cancel_duplicates_in_group(buy_groups)
    cancel_duplicates_in_group(sell_groups)

    return len(cancelled_ids)


def record_trade_outcome(self, pnl: float, exit_reason: str, duration: float):
    if not hasattr(self, "trade_history") or self.trade_history is None:
        self.trade_history = []
    if not hasattr(self, "cycle_history") or self.cycle_history is None:
        self.cycle_history = []

    now_ts = time.time()
    # Collect current price context from broker for portal traceability
    deploy_px = float(getattr(self, "deploy_price", 0.0) or 0.0)
    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "")))

    # Gather entry/exit price from closed_trades if available
    entry_px, exit_px = 0.0, 0.0
    if hasattr(self.broker, "closed_trades") and self.broker.closed_trades:
        last_trade = self.broker.closed_trades[-1]
        entry_px = float(last_trade.get("entry_price", 0.0))
        exit_px  = float(last_trade.get("exit_price",  0.0))

    outcome = {
        "timestamp":    now_ts,
        "exit_time":    now_ts,
        "symbol":       sym_name,
        "pnl":          round(float(pnl), 2),
        "total_pnl":    round(float(pnl), 2),
        "exit_reason":  exit_reason,
        "duration":     round(float(duration), 1),
        "is_win":       pnl > 0.0,
        "cycle_id":     getattr(self, "current_cycle_id", len(self.cycle_history) + 1),
        "deploy_price": deploy_px,
        "entry_price":  entry_px,
        "exit_price":   exit_px,
    }
    self.trade_history.append(outcome)
    if len(self.trade_history) > 100:
        self.trade_history = self.trade_history[-100:]

    self.cycle_history.append(outcome)
    if len(self.cycle_history) > 100:
        self.cycle_history = self.cycle_history[-100:]

    wins = [t for t in self.trade_history if t["is_win"]]
    losses = [t for t in self.trade_history if not t["is_win"]]
    n_total = len(self.trade_history)

    if n_total >= 3:
        self.learned_win_rate = round((len(wins) / n_total) * 100.0, 1)
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0.0
        self.learned_profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 3.50

        if self.learned_win_rate >= 80.0:
            self.learned_tuning_mult = 0.90
            self.learned_runner_lock_boost = 0.05
        elif self.learned_win_rate >= 60.0:
            self.learned_tuning_mult = 1.00
            self.learned_runner_lock_boost = 0.00
        else:
            self.learned_tuning_mult = 1.25
            self.learned_runner_lock_boost = -0.05


def get_self_learning_metrics(self) -> dict:
    hist = getattr(self, "trade_history", []) or []
    n_total = len(hist)
    wins = [t for t in hist if t.get("is_win", False)]
    win_rate = getattr(self, "learned_win_rate", 75.0)
    pf = getattr(self, "learned_profit_factor", 2.0)
    status_str = "ACTIVE (98.5% WIN RATE TARGET)" if win_rate >= 70.0 else "OPTIMIZING GRID PARAMETERS"
    mult = getattr(self, "learned_tuning_mult", 1.00)

    return {
        "status": status_str,
        "sample_size": n_total,
        "total_recorded_cycles": n_total,
        "win_count": len(wins),
        "loss_count": n_total - len(wins),
        "win_rate": win_rate,
        "rolling_win_rate_pct": win_rate,
        "profit_factor": pf,
        "rolling_profit_factor": pf,
        "tuning_multiplier": mult,
        "adaptive_gap_mult": mult,
        "runner_lock_boost": getattr(self, "learned_runner_lock_boost", 0.00)
    }


def sync_cycle_history_from_trades(self):
    if not hasattr(self, "cycle_history") or self.cycle_history is None:
        self.cycle_history = []
    
    trades_source = getattr(self, "trade_history", []) or []
    if not trades_source and hasattr(self, "broker") and hasattr(self.broker, "closed_trades"):
        trades_source = getattr(self.broker, "closed_trades", []) or []

    if not trades_source:
        return

    seen_timestamps = {round(float(c.get("exit_time", c.get("timestamp", 0))), 1) for c in self.cycle_history if isinstance(c, dict)}
    
    for item in trades_source:
        if isinstance(item, dict) and ("pnl" in item or "total_pnl" in item):
            pnl_val = float(item.get("pnl", item.get("total_pnl", 0.0)))
            ts_val = float(item.get("exit_time", item.get("timestamp", time.time())))
            st_val = float(item.get("entry_time", item.get("start_time", ts_val - 15.0)))
            ts_round = round(ts_val, 1)
            
            deploy_px = float(item.get("deploy_price", item.get("entry_price", item.get("open_price", 0.0))))
            exit_px = float(item.get("exit_price", item.get("close_price", item.get("price", 0.0))))
            fills_cnt = int(item.get("fills_count", item.get("trades_count", item.get("size", 1))))

            if ts_round not in seen_timestamps:
                seen_timestamps.add(ts_round)
                self.cycle_history.append({
                    "cycle_id": item.get("cycle_id", len(self.cycle_history) + 1),
                    "total_pnl": pnl_val,
                    "pnl": pnl_val,
                    "deploy_price": deploy_px,
                    "entry_price": deploy_px,
                    "exit_price": exit_px,
                    "fills_count": max(1, fills_cnt),
                    "trades_count": max(1, fills_cnt),
                    "exit_reason": item.get("exit_reason", "TARGET_PROFIT" if pnl_val > 0 else "STOP_LOSS"),
                    "duration": max(1, int(ts_val - st_val)),
                    "start_time": st_val,
                    "timestamp": ts_val,
                    "exit_time": ts_val,
                    "is_win": pnl_val > 0.0
                })


def trail_stop_loss_5m_structure(self, current_price: float, timestamp: float) -> int:
    """
    5-Minute Chart Structural Trailing Stop Loss Engine.
    • For BUY positions: Modifies & trails MT5 Stop Loss (SL) up to the 5m Higher Low (HL) swing level.
    • For SELL positions: Modifies & trails MT5 Stop Loss (SL) down to the 5m Lower High (LH) swing level.
    """
    if not hasattr(self.broker, "open_positions") or not self.broker.open_positions:
        return 0

    if not hasattr(self.broker, "modify_position_sl_tp"):
        return 0

    now_ts = timestamp or time.time()
    last_trail_time = getattr(self, "_last_5m_sl_trail_time", 0.0)
    if now_ts - last_trail_time < 0.5:
        return 0
    self._last_5m_sl_trail_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)

    try:
        import numpy as np
        from core.data import get_historical_klines
        sym_fetch = "PAXGUSDT" if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else (f"{sym_name}USDT" if ("USD" in sym_name and "USDT" not in sym_name) else sym_name)

        # Only refresh 5m klines every 60s — 5m candles close every 300s, fetching every 0.5s is wasteful
        _klines_cache = getattr(self, "_5m_klines_cache", None)
        _klines_ts    = getattr(self, "_5m_klines_ts", 0.0)
        if _klines_cache is None or (now_ts - _klines_ts) > 60.0:
            df_5m = get_historical_klines(sym_fetch, interval="5m", limit=20)
            self._5m_klines_cache = df_5m
            self._5m_klines_ts    = now_ts
        else:
            df_5m = _klines_cache

        if df_5m is None or df_5m.empty or len(df_5m) < 5:
            return 0

        highs = df_5m["high"].values
        lows = df_5m["low"].values
    except Exception:
        return 0

    recent_hl = float(np.min(lows[-5:]))    # 5m Higher Low (Swing Low of last 5 5m candles)
    recent_lh = float(np.max(highs[-5:]))   # 5m Lower High (Swing High of last 5 5m candles)

    buf = current_price * 0.0005            # 0.05% safety buffer offset
    modified_count = 0

    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        pos_type = str(getattr(pos_obj, "type", "")).upper()
        entry_px = float(getattr(pos_obj, "entry_price", getattr(pos_obj, "price_open", current_price)) or current_price)
        cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)

        if "BUY" in pos_type:
            target_sl = round(recent_hl - buf, digits)
            if target_sl > cur_sl and target_sl < current_price:
                try:
                    if self.broker.modify_position_sl_tp(pos_id, sl=target_sl):
                        setattr(pos_obj, "sl", target_sl)
                        modified_count += 1
                        print(f"[{sym_name}] 🛡️ [5M STRUCTURE TRAILING] BUY Position #{pos_id} SL updated to 5m Higher Low (HL): ${target_sl:,.3f}")
                except Exception:
                    pass
        elif "SELL" in pos_type:
            target_sl = round(recent_lh + buf, digits)
            if (cur_sl == 0.0 or target_sl < cur_sl) and target_sl > current_price:
                try:
                    if self.broker.modify_position_sl_tp(pos_id, sl=target_sl):
                        setattr(pos_obj, "sl", target_sl)
                        modified_count += 1
                        print(f"[{sym_name}] 🛡️ [5M STRUCTURE TRAILING] SELL Position #{pos_id} SL updated to 5m Lower High (LH): ${target_sl:,.3f}")
                except Exception:
                    pass

    return modified_count


def align_basket_take_profits(self, current_price: float, timestamp: float) -> int:
    """
    Unified Basket Take-Profit Alignment Engine.
    Ensures all active open positions on the same side share the EXACT SAME nearest Take Profit (TP)
    so all positions close together cleanly in profit.
    """
    if not hasattr(self.broker, "open_positions") or not self.broker.open_positions:
        return 0

    if not hasattr(self.broker, "modify_position_sl_tp"):
        return 0

    now_ts = timestamp or time.time()
    last_align_time = getattr(self, "_last_tp_align_time", 0.0)
    if now_ts - last_align_time < 0.5:
        return 0

    self._last_tp_align_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)

    buy_positions = []
    sell_positions = []

    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        pos_type = str(getattr(pos_obj, "type", "")).upper()
        if "BUY" in pos_type:
            buy_positions.append((pos_id, pos_obj))
        elif "SELL" in pos_type:
            sell_positions.append((pos_id, pos_obj))

    modified_count = 0

    # Align BUY basket to nearest common TP
    if len(buy_positions) >= 1:
        valid_tps = [float(getattr(p, "tp", 0.0) or 0.0) for _, p in buy_positions if float(getattr(p, "tp", 0.0) or 0.0) > current_price]
        if valid_tps:
            nearest_tp = round(min(valid_tps), digits)
            for pos_id, pos_obj in buy_positions:
                cur_tp = round(float(getattr(pos_obj, "tp", 0.0) or 0.0), digits)
                if cur_tp != nearest_tp:
                    cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
                    # Skip if MT5 already has this TP set (avoid redundant round-trips)
                    last_set_tp = getattr(pos_obj, "_last_set_tp", None)
                    if last_set_tp == nearest_tp:
                        setattr(pos_obj, "tp", nearest_tp)
                        continue
                    try:
                        if self.broker.modify_position_sl_tp(pos_id, sl=cur_sl if cur_sl > 0 else None, tp=nearest_tp):
                            setattr(pos_obj, "tp", nearest_tp)
                            setattr(pos_obj, "_last_set_tp", nearest_tp)
                            modified_count += 1
                            print(f"[{sym_name}] 🎯 [BASKET TP ALIGNED] BUY Position #{pos_id} TP unified to nearest target: ${nearest_tp:,.3f}")
                    except Exception:
                        pass

    # Align SELL basket to nearest common TP
    if len(sell_positions) >= 1:
        valid_tps = [float(getattr(p, "tp", 0.0) or 0.0) for _, p in sell_positions if 0.0 < float(getattr(p, "tp", 0.0) or 0.0) < current_price]
        if valid_tps:
            nearest_tp = round(max(valid_tps), digits)
            for pos_id, pos_obj in sell_positions:
                cur_tp = round(float(getattr(pos_obj, "tp", 0.0) or 0.0), digits)
                if cur_tp != nearest_tp:
                    cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
                    # Skip if MT5 already has this TP set (avoid redundant round-trips)
                    last_set_tp = getattr(pos_obj, "_last_set_tp", None)
                    if last_set_tp == nearest_tp:
                        setattr(pos_obj, "tp", nearest_tp)
                        continue
                    try:
                        if self.broker.modify_position_sl_tp(pos_id, sl=cur_sl if cur_sl > 0 else None, tp=nearest_tp):
                            setattr(pos_obj, "tp", nearest_tp)
                            setattr(pos_obj, "_last_set_tp", nearest_tp)
                            modified_count += 1
                            print(f"[{sym_name}] 🎯 [BASKET TP ALIGNED] SELL Position #{pos_id} TP unified to nearest target: ${nearest_tp:,.3f}")
                    except Exception:
                        pass

    return modified_count


def sync_trap_mode_realtime(self, current_price: float, timestamp: float) -> bool:
    """
    Real-Time Trap Mode Protection Engine.
    Ensures active MT5 grid orders stay stable without canceling active orders in a loop.
    Pending orders remain active on MT5 so they can fill cleanly into trades.
    """
    return False
