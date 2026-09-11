import time
import datetime
from typing import Optional, Dict, Any, Tuple

def get_pip_size(symbol: str, current_price: float = 0.0) -> float:
    sym = (symbol or "").upper()
    sym_lookup = "XAUUSD" if any(x in sym for x in ["PAXG", "XAU", "GOLD"]) else sym.replace("USDT", "USD").replace("USDC", "USD")
    try:
        import MetaTrader5 as mt5_ref
        if mt5_ref is not None and hasattr(mt5_ref, "symbol_info"):
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

    try:
        import requests, os
        bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
        r_si = requests.get(f"http://127.0.0.1:{bridge_port}/symbol_info?symbol={sym_lookup}", timeout=0.6)
        if r_si.status_code == 200:
            d_si = r_si.json()
            pt = float(d_si.get("point", 0.0) or 0.0)
            dg = int(d_si.get("digits", 0) or 0)
            if pt > 0:
                if dg in (3, 5):
                    return pt * 10.0
                elif dg in (2, 4):
                    return pt
                else:
                    return pt * 10.0 if pt < 0.1 else pt
    except Exception:
        pass

    if "PAXG" in sym or "XAU" in sym or "GOLD" in sym:
        return 0.10
    else:
        if current_price > 5000:
            return 1.0
        elif current_price > 50:
            return 0.10
        return 0.0001


def sanitize_order_size(symbol: str, raw_size: float) -> float:
    sym = (symbol or "").upper()
    sym_lookup = "XAUUSD" if any(x in sym for x in ["PAXG", "XAU", "GOLD"]) else sym.replace("USDT", "USD").replace("USDC", "USD")
    try:
        import MetaTrader5 as mt5_ref
        if mt5_ref is not None and hasattr(mt5_ref, "symbol_info"):
            info = mt5_ref.symbol_info(sym_lookup) or mt5_ref.symbol_info(f"{sym_lookup}m") or mt5_ref.symbol_info(f"{sym_lookup}c")
            if info is not None:
                v_min = getattr(info, "volume_min", 0.01) or 0.01
                v_max = getattr(info, "volume_max", 100.0) or 100.0
                v_step = getattr(info, "volume_step", 0.01) or 0.01
                size = round(round(raw_size / v_step) * v_step, 4) if v_step > 0 else round(raw_size, 4)
                return max(v_min, min(v_max, size))
    except Exception:
        pass

    try:
        import requests, os
        bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
        r_si = requests.get(f"http://127.0.0.1:{bridge_port}/symbol_info?symbol={sym_lookup}", timeout=0.6)
        if r_si.status_code == 200:
            d_si = r_si.json()
            v_min = float(d_si.get("volume_min", 0.01) or 0.01)
            v_max = float(d_si.get("volume_max", 100.0) or 100.0)
            v_step = float(d_si.get("volume_step", 0.01) or 0.01)
            size = round(round(raw_size / v_step) * v_step, 4) if v_step > 0 else round(raw_size, 4)
            return max(v_min, min(v_max, size))
    except Exception:
        pass

    if "PAXG" in sym or "XAU" in sym or "GOLD" in sym:
        return min(0.03, max(0.01, round(raw_size, 2)))
    return max(0.01, round(raw_size, 2))


def calculate_ratchet_breakeven(entry_price: float, position_type: str, current_price: float, pip_size: float) -> float:
    if position_type == "BUY":
        return max(entry_price + (pip_size * 2.0), current_price - (pip_size * 15.0))
    else:
        return min(entry_price - (pip_size * 2.0), current_price + (pip_size * 15.0))


def is_auto_100pct_confirmed(self) -> bool:
    """
    🟢 AUTO MODE TREND CONFIRMATION GATE.
    """
    if not getattr(self, "use_auto_reading", True):
        return False  # Strict manual mode — never auto-confirm

    # Gate 1: Must be in auto mode with a clear directional bias
    auto_uni = str(getattr(self, "unidirectional_mode",
                           getattr(self, "auto_universe_bias", "DUAL"))).upper()
    if not (("BUY" in auto_uni and "ONLY" in auto_uni) or
            ("SELL" in auto_uni and "ONLY" in auto_uni)):
        return False  # DUAL / ranging — do not activate aggressive mode

    # Also check last_auto_eval for the most-recent engine decision
    last_eval = getattr(self, "last_auto_eval", None)
    if isinstance(last_eval, dict):
        eval_uni = str(last_eval.get("unidirectional_mode", "DUAL")).upper()
        if not (("BUY" in eval_uni and "ONLY" in eval_uni) or
                ("SELL" in eval_uni and "ONLY" in eval_uni)):
            return False

    # Gate 2: ADX >= 20 (trending) and CI < 55 (not ranging)
    # Lowered from 25/50 → 20/55 so confirmation fires more readily,
    # allowing the aggressive profit-lock & trail to kick in sooner.
    trail_cache = getattr(self, "_trail_trend_cache", None)
    if trail_cache:
        adx = float(trail_cache.get("adx", 0.0))
        ci  = float(trail_cache.get("ci", 100.0))
        if adx < 20.0 or ci >= 55.0:
            return False  # Weak trend or choppy — stay conservative

    return True


def enforce_profit_lock(self, current_price: float, timestamp: float) -> int:
    """
    BREAKEVEN PROTECTION.
    Moves SL to breakeven once a position is safely in profit.
    """
    # Update running peak for check_target_profit runner-mode calculations
    if getattr(self.broker, "open_positions", None):
        total_pnl = float(self.broker.get_floating_pnl(current_price))
        if total_pnl > getattr(self, "max_floating_pnl", -float("inf")):
            self.max_floating_pnl = total_pnl
            
    if not getattr(self.broker, "open_positions", None) or not hasattr(self.broker, "modify_position_sl_tp"):
        return 0

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)
    is_gold = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])
    
    state = compute_basket_state(self, current_price, timestamp)
    atr = state["atr_5m"]
    
    actions = 0
    
    if is_gold:
        breakeven_trigger_dist = max(6.00, atr * 1.8)
        breakeven_buffer = max(1.00, min(current_price * 0.0003, 1.50))
        min_room_from_price = 3.50
    elif "BTC" in sym_name:
        breakeven_trigger_dist = max(350.0, atr * 2.5)
        breakeven_buffer = max(50.0, atr * 0.5)
        min_room_from_price = 150.0
    elif "ETH" in sym_name:
        breakeven_trigger_dist = max(25.0, atr * 2.5)
        breakeven_buffer = max(4.0, atr * 0.5)
        min_room_from_price = 15.0
    else:
        breakeven_trigger_dist = atr * 2.5
        breakeven_buffer = min(current_price * 0.0005, atr * 0.5)
        min_room_from_price = atr * 1.5
    
    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        # Minimum 30-second breathing room before moving SL to breakeven
        pos_open_time = float(getattr(pos_obj, "entry_time", getattr(pos_obj, "time_setup", 0.0)) or 0.0)
        if pos_open_time > 0 and (timestamp - pos_open_time) < 30.0:
            continue

        pos_type = str(getattr(pos_obj, "type", "")).upper()
        entry = float(getattr(pos_obj, "entry_price", getattr(pos_obj, "price_open", current_price)) or current_price)
        cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
        cur_tp = float(getattr(pos_obj, "tp", 0.0) or 0.0)
        
        if "BUY" in pos_type:
            if current_price >= entry + breakeven_trigger_dist:
                new_sl = round(entry + breakeven_buffer, digits)
                if (current_price - new_sl) >= min_room_from_price:
                    if (cur_sl == 0.0 or cur_sl < new_sl) and new_sl < current_price:
                        try:
                            if self.broker.modify_position_sl_tp(pos_id, sl=new_sl, tp=cur_tp if cur_tp > 0 else None):
                                setattr(pos_obj, "sl", new_sl)
                                actions += 1
                                print(f"[{sym_name}] 🛡️ [BREAKEVEN] BUY #{pos_id} SL moved to {new_sl}")
                        except Exception as e:
                            pass
        elif "SELL" in pos_type:
            if current_price <= entry - breakeven_trigger_dist:
                new_sl = round(entry - breakeven_buffer, digits)
                if (new_sl - current_price) >= min_room_from_price:
                    if (cur_sl == 0.0 or cur_sl > new_sl) and new_sl > current_price:
                        try:
                            if self.broker.modify_position_sl_tp(pos_id, sl=new_sl, tp=cur_tp if cur_tp > 0 else None):
                                setattr(pos_obj, "sl", new_sl)
                                actions += 1
                                print(f"[{sym_name}] 🛡️ [BREAKEVEN] SELL #{pos_id} SL moved to {new_sl}")
                        except Exception as e:
                            pass
                        
    return actions


def compute_basket_state(self, current_price: float, timestamp: float) -> dict:
    """
    Computes the weighted-average basket state across all open positions.
    Shares the 5m klines cache with trail_stop_loss_5m_structure to avoid
    duplicate API calls.

    Returns a dict with:
      weighted_avg_entry_buy, weighted_avg_entry_sell,
      total_lots_buy, total_lots_sell,
      buy_positions, sell_positions,
      atr_5m, swing_high_5m, swing_low_5m,
      swing_range
    """
    empty = {
        "weighted_avg_entry_buy": 0.0, "weighted_avg_entry_sell": 0.0,
        "total_lots_buy": 0.0, "total_lots_sell": 0.0,
        "buy_positions": [], "sell_positions": [],
        "atr_5m": current_price * 0.002,
        "swing_high_5m": current_price, "swing_low_5m": current_price,
        "swing_range": current_price * 0.002,
    }
    if not getattr(self.broker, "open_positions", None):
        return empty

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    is_gold = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])

    # ── Shared 5m klines cache (written by trail_stop_loss_5m_structure too) ──
    atr_5m = current_price * 0.002
    swing_high_5m = current_price
    swing_low_5m  = current_price
    now_ts = timestamp or time.time()
    try:
        import numpy as np
        from core.data import get_historical_klines
        sym_fetch = "PAXGUSDT" if is_gold else (
            f"{sym_name}USDT" if ("USD" in sym_name and "USDT" not in sym_name) else sym_name
        )
        _klines_cache = getattr(self, "_5m_klines_cache", None)
        _klines_ts    = getattr(self, "_5m_klines_ts", 0.0)
        if _klines_cache is None or (now_ts - _klines_ts) > 60.0:
            df_5m = get_historical_klines(sym_fetch, interval="3m", limit=30)
            self._5m_klines_cache = df_5m
            self._5m_klines_ts    = now_ts
        else:
            df_5m = _klines_cache

        if df_5m is not None and not df_5m.empty and len(df_5m) >= 10:
            highs  = df_5m["high"].values
            lows   = df_5m["low"].values
            closes = df_5m["close"].values
            tr_list = []
            for i in range(1, len(df_5m)):
                tr = max(highs[i] - lows[i],
                         abs(highs[i] - closes[i-1]),
                         abs(lows[i]  - closes[i-1]))
                tr_list.append(tr)
            if tr_list:
                atr_5m = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else float(np.mean(tr_list))
            lb = min(8, len(highs) - 1)
            swing_high_5m = float(np.max(highs[-lb:]))
            swing_low_5m  = float(np.min(lows[-lb:]))
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")

    if atr_5m <= 0:
        atr_5m = current_price * 0.002

    # ── Weighted-average entry per side ──
    buy_positions, sell_positions = [], []
    wsum_buy, wsum_sell = 0.0, 0.0
    lots_buy, lots_sell = 0.0, 0.0

    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        pos_type = str(getattr(pos_obj, "type", "")).upper()
        entry = float(getattr(pos_obj, "entry_price", getattr(pos_obj, "price_open", current_price)) or current_price)
        size  = float(getattr(pos_obj, "size", getattr(pos_obj, "volume", 0.01)) or 0.01)
        if "BUY" in pos_type:
            buy_positions.append((pos_id, pos_obj, entry, size))
            wsum_buy += entry * size
            lots_buy  += size
        elif "SELL" in pos_type:
            sell_positions.append((pos_id, pos_obj, entry, size))
            wsum_sell += entry * size
            lots_sell += size

    w_avg_buy  = wsum_buy  / lots_buy  if lots_buy  > 0 else 0.0
    w_avg_sell = wsum_sell / lots_sell if lots_sell > 0 else 0.0
    swing_range = max(swing_high_5m - swing_low_5m, atr_5m)

    return {
        "weighted_avg_entry_buy":  w_avg_buy,
        "weighted_avg_entry_sell": w_avg_sell,
        "total_lots_buy":          lots_buy,
        "total_lots_sell":         lots_sell,
        "buy_positions":           buy_positions,
        "sell_positions":          sell_positions,
        "atr_5m":                  atr_5m,
        "swing_high_5m":           swing_high_5m,
        "swing_low_5m":            swing_low_5m,
        "swing_range":             swing_range,
    }


def evaluate_partial_tp(self, current_price: float, timestamp: float) -> int:
    """
    Disabled per user request: scale-outs bleed in chop.
    The bot now closes when the full dynamic basket target is hit.
    """
    return 0


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
    digits = 3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 5

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
                print(f"[{sym_name}] ✅ [SOFTWARE TP HIT] {pos_type} #{pos_id} | Price: {current_price:.{digits}f} | TP: {pos_tp:.{digits}f} — Force closing!")
                try:
                    self.broker.close_position(pos_id, current_price, timestamp)
                    closed_count += 1
                except Exception as close_err:
                    print(f"[{sym_name}] ⚠️ [SOFTWARE TP] Close failed for #{pos_id}: {close_err}")
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

    return closed_count


def check_target_profit(self, current_price: float, timestamp: float) -> Optional[dict]:
    """
    Evaluates floating PnL across active open positions against target profit,
    stop loss, runner mode trailing lock, and breakeven floors. Returns cycle summary dictionary if exit met.
    """
    if not self.broker.open_positions:
        return None

    total_pnl = self.broker.get_floating_pnl(current_price)  # Use real MT5 profit (includes spread, swap, commission)
    _c_st = float(getattr(self, "_cycle_start_time", 0.0) or getattr(self, "cycle_start_time", 0.0) or timestamp)
    duration = max(1.0, timestamp - _c_st)

    sym_u = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
    
    # Auto-detect Cent (USC) logic
    is_cent_account = False
    acc_info = getattr(self.broker, "get_account_info", lambda: None)()
    if acc_info:
        currency = str(getattr(acc_info, "currency", "")).upper()
        if currency in ["USC", "USX", "EUC", "GBPC"]:
            is_cent_account = True
            
    # Fallback suffix check for cent accounts
    if not is_cent_account and any(sym_u.endswith(s) for s in ["C", "MICRO"]):
        is_cent_account = True

    # MT5 natively returns floating PnL and account balance directly in the account currency (USC for cent accounts).
    # cent_multiplier is set to 1.0 so targets are evaluated in native account units without 100x inflation.
    cent_multiplier = 1.0

    total_volume = sum(float(getattr(p, "size", 0.01)) for p in self.broker.open_positions.values())
    micro_lots = max(1.0, total_volume / 0.01)

    target_prof = float(getattr(self, "target_profit", 3.0) or 3.0)
    effective_target = max(0.50, target_prof)

    if total_pnl > getattr(self, "max_floating_pnl", -float("inf")):
        self.max_floating_pnl = total_pnl

    max_pnl = self.max_floating_pnl

    # ── Fix #4: Resolve trend bias ONCE here — prevents stale/inconsistent reads
    #    across all three exit checks (runner, trend-reversal, near-target lock)
    auto_uni = str(getattr(self, "unidirectional_mode", getattr(self, "auto_universe_bias", "DUAL"))).upper()
    if hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict):
        eval_uni = self.last_auto_eval.get("unidirectional_mode", "")
        if eval_uni: auto_uni = str(eval_uni).upper()

    if max_pnl >= effective_target and getattr(self, "use_smart_trailing", True):
        self.in_runner_mode = True

    exit_triggered = False
    exit_reason = ""

    # ─────────────────────────────────────────────────────────────
    # Real-Market Structure Governance (No Artificial Hard Cap)
    # Stop Loss is strictly governed by MT5 broker-level SL anchored at real 5m tops/bottoms.
    # Emergency Catastrophic Circuit Breaker: Only triggers if account equity faces catastrophic 40%+ loss.
    # ─────────────────────────────────────────────────────────────
    if not exit_triggered:
        acc_bal = float(getattr(self.broker, "balance", 1000.0) or 1000.0)
        # Emergency catastrophic breaker: 40% of balance (last-resort safety if broker connection fails)
        catastrophe_limit = max(150.0 * cent_multiplier, acc_bal * 0.40)
        if total_pnl <= -abs(catastrophe_limit):
            exit_triggered = True
            exit_reason = "CATASTROPHIC_EMERGENCY_STOP"
            print(f"[{self.symbol}] 🛑 [CATASTROPHIC CIRCUIT BREAKER] Floating PnL {total_pnl:.2f} <= -{catastrophe_limit:.2f}. Emergency exit.")

    # ─────────────────────────────────────────────────────────────
    # Basket Target Profit (Cycle Exit)
    # ─────────────────────────────────────────────────────────────
    # Cent logic is hoisted to the top of the function

    min_profit_threshold = 0.50 * cent_multiplier * micro_lots  # Minimum gross profit to close a cycle, mitigating fee attrition
    if not exit_triggered:
        # Base basket target for full cycle (e.g. 25.0 for Gold, 10.0 for others in native account currency)
        base_target = 25.0 if any(x in sym_u for x in ["XAU", "GOLD", "PAXG"]) else 10.0
        
        default_target = base_target
        
        raw_ai_target = float(getattr(self, "deploy_target_profit", 0.0) or 0.0)
        ai_target = raw_ai_target if raw_ai_target > 0 else 0.0
        
        raw_user_target = float(getattr(self, "target_profit", 0.0) or 0.0)
        user_target = raw_user_target if raw_user_target > 0 else 0.0
        
        cycle_target = ai_target if ai_target > 0 else (user_target if user_target > 0 else default_target)
        
        is_gold = any(x in sym_u for x in ["XAU", "GOLD", "PAXG"])
        min_gold_target = 20.0 if is_cent_account else 25.0
        if is_gold and cycle_target < min_gold_target:
            cycle_target = min_gold_target

        # Enforce minimum profit threshold
        effective_cycle_target = max(cycle_target, min_profit_threshold)
            
        # ── 1. Basket Target Profit (Strict Full Target) ──
        # When floating profit reaches the full cycle target (e.g. $25+ for Gold), exit immediately.
        if total_pnl >= effective_cycle_target:
            exit_triggered = True
            exit_reason = "TARGET_PROFIT"
            print(f"[{sym_u}] 💰 [CYCLE TP HIT] Basket reached full target of ${effective_cycle_target:.2f} (Total PnL: ${total_pnl:.2f})! Instant Close All.")

        # ── 2. Basket Trailing Profit Lock (Guaranteed Profit Retention) ──
        # Track peak PnL and lock in high trailing profit floor (75% retention) once target is reached
        if not exit_triggered:
            basket_peak = float(getattr(self, "_basket_peak_pnl", 0.0) or 0.0)
            if total_pnl > basket_peak:
                basket_peak = total_pnl
                self._basket_peak_pnl = basket_peak

            # Only activate trailing floor once PnL has reached the target profit to give trades room to breathe
            if basket_peak >= effective_cycle_target:
                # Lock floor at 75% of peak (guarantees retaining 75%+ of peak profit without choking on noise)
                trailing_floor = max(effective_cycle_target * 0.70, basket_peak * 0.75)
                if total_pnl <= trailing_floor:
                    exit_triggered = True
                    exit_reason = "TRAILING_PROFIT_LOCK"
                    try:
                        print(f"[{sym_u}] 🛡️ [BASKET TRAIL HIT] PnL pulled back from peak ${basket_peak:.2f} to floor ${trailing_floor:.2f}! Locking in ${total_pnl:.2f} profit.")
                    except UnicodeEncodeError:
                        print(f"[{sym_u}] [BASKET TRAIL HIT] PnL pulled back from peak ${basket_peak:.2f} to floor ${trailing_floor:.2f}! Locking in ${total_pnl:.2f} profit.")

    if exit_triggered:
        try:
            print(f"[{self.symbol}] 🎯 [PROFIT TAKING EXIT] {exit_reason} met! Net PnL: ${total_pnl:+.2f} USD")
        except UnicodeEncodeError:
            print(f"[{self.symbol}] [PROFIT TAKING EXIT] {exit_reason} met! Net PnL: ${total_pnl:+.2f} USD")
        _deal_side = "BUY"
        if getattr(self.broker, "open_positions", None):
            _types = [str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values()]
            _deal_side = "SELL" if sum(1 for t in _types if "SELL" in t) >= sum(1 for t in _types if "BUY" in t) else "BUY"

        # 1. Close active market positions FIRST (lock in live profit before any slippage)
        if hasattr(self.broker, "close_all_positions"):
            try: self.broker.close_all_positions()
            except Exception as e: import logging; logging.warning(f"Close error: {e}")

        # 2. Cancel pending orders SECOND (after active positions are secured)
        if hasattr(self.broker, "cancel_all_orders"):
            try: self.broker.cancel_all_orders()
            except Exception as e: import logging; logging.warning(f"Cancel error: {e}")

        self.in_runner_mode = False
        self.max_floating_pnl = -float("inf")
        self._max_open_in_cycle = 0
        self._basket_max_pnl = 0.0
        self._basket_peak_pnl = 0.0
        self._cycle_start_time = 0.0
        self._cycle_start_realized_pnl = 0.0

        summary = {
            "cycle_id": getattr(self, "current_cycle_id", 1),
            "total_pnl": round(total_pnl, 2),
            "type": _deal_side,
            "side": _deal_side,
            "exit_reason": exit_reason,
            "duration": round(duration, 1),
            "timestamp": timestamp,
            "exit_price": current_price
        }

        # Note: Grid redeployment is managed after full MT5 clearance & cooldown in process_engine_tick
        return summary

    return None


def realign_pending_orders(bot, current_price, timestamp):
    """
    Pending orders are anchored to institutional SMC structural levels (OBs, FVGs, swing extremes).
    Dynamic realignment is bypassed to allow structural traps to execute without churning.
    """
    return


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
                if hasattr(self.broker, "close_all_positions"):
                    self.broker.close_all_positions()
                if hasattr(self.broker, "cancel_all_orders"):
                    self.broker.cancel_all_orders()
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

    has_orders = len(getattr(self.broker, "pending_orders", {})) > 0 or len(getattr(self.broker, "open_positions", {})) > 0
    if not has_orders and hasattr(self.broker, "ensure_connected"):
        try:
            if not self.broker.ensure_connected():
                return None
            ex_s = self.broker.get_exness_symbol(self.symbol) if hasattr(self.broker, "get_exness_symbol") else self.symbol
            try:
                import MetaTrader5 as mt5_tick_check
                if mt5_tick_check is not None and hasattr(mt5_tick_check, "orders_get") and callable(getattr(mt5_tick_check, "orders_get", None)):
                    mt5_o = mt5_tick_check.orders_get(symbol=ex_s)
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

            # ── CYCLE OVERLAP GUARD: also check MT5 live positions ──
            if not has_orders:
                mt5_p = None
                try:
                    import MetaTrader5 as mt5_p_check
                    if mt5_p_check is not None and hasattr(mt5_p_check, "positions_get") and callable(getattr(mt5_p_check, "positions_get", None)):
                        mt5_p = mt5_p_check.positions_get(symbol=ex_s)
                        if not mt5_p:
                            all_p = mt5_p_check.positions_get()
                            if all_p:
                                clean_tgt = "XAU" if any(x in (ex_s or "").upper() for x in ["XAU", "GOLD"]) else (
                                    "PAXG" if "PAXG" in (ex_s or "").upper() else
                                    (ex_s or "").replace("USDT", "").replace("USDC", "").replace("USD", "").upper()
                                )
                                mt5_p = [p for p in all_p if clean_tgt in str(p.symbol).upper()]
                except Exception:
                    mt5_p = None

                if mt5_p and len(mt5_p) > 0:
                    has_orders = True   # Lingering positions still open — do NOT redeploy
                    self.deployed = True
                    try:
                        self.broker.process_tick(current_price, current_price, timestamp)
                    except Exception as e:
                        import logging; logging.warning(f"Exception: {e}")
                    print(f"[{self.symbol}] ⚠️ [CYCLE GUARD] {len(mt5_p)} MT5 position(s) still live — blocking new deploy until clear")
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

    if not has_orders:
        self.deployed = False
        
        # ── GRID SELF-HEALING / AUTO-START GUARD ──
        # Fix #13: Only start the empty-grid timer when the grid IS empty.
        # Fix #13 (Refined): Timer initialized on first empty, then reset to None if grid becomes non-empty.
        if not hasattr(self, "_last_empty_grid_time") or self._last_empty_grid_time is None:
            self._last_empty_grid_time = timestamp
            
        if timestamp - self._last_empty_grid_time >= 300.0:  # 5 minutes stuck empty
            print(f"[{self.symbol}] 🚑 [SELF HEALING] Grid empty for 5 minutes. Forcing auto-start...")
            self._post_loss_cooldown = 0.0
            self._is_deploying = False
            self._last_empty_grid_time = timestamp
            try:
                if hasattr(self.broker, "cancel_all_orders"):
                    self.broker.cancel_all_orders()
            except: pass

        if timestamp >= getattr(self, "_last_deploy_attempt_time", 0.0) + 3.0:
            self._last_deploy_attempt_time = timestamp   # Prevent runaway deploy loop on every tick
            post_cd = max(getattr(self, "_post_loss_cooldown", 0.0), getattr(self, "_post_cycle_cooldown_until", 0.0))
            if timestamp >= post_cd:
                self.deploy_traps(current_price, timestamp, force=True)
        return None
    else:
        self._last_empty_grid_time = None

    self._tick_counter += 1

    try:
        sync_trap_mode_realtime(self, current_price, timestamp)
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")
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
            sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
            filled_types = [self.broker.open_positions[pid].type for pid in newly_filled_pos_ids if pid in self.broker.open_positions]
            if "BUY" in filled_types:
                for oid, ord_obj in list(self.broker.pending_orders.items()):
                    if getattr(ord_obj, "symbol", sym_name) == sym_name and ord_obj.type == "SELL_STOP":
                        self.broker.cancel_order(oid)
            if "SELL" in filled_types:
                for oid, ord_obj in list(self.broker.pending_orders.items()):
                    if getattr(ord_obj, "symbol", sym_name) == sym_name and ord_obj.type == "BUY_STOP":
                        self.broker.cancel_order(oid)

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    current_pending = sum(1 for o in getattr(self.broker, "pending_orders", {}).values() if getattr(o, "symbol", sym_name) == sym_name)
    current_open = sum(1 for p in getattr(self.broker, "open_positions", {}).values() if getattr(p, "symbol", sym_name) == sym_name)

    if current_open > getattr(self, "_max_open_in_cycle", 0):
        if getattr(self, "_max_open_in_cycle", 0) == 0:
            self._cycle_start_realized_pnl = getattr(self.broker, "realized_pnl", 0.0)
            self._cycle_start_time = timestamp
            self.cycle_start_time = timestamp
            self._cycle_recorded = False
        self._max_open_in_cycle = current_open

    last_pending = getattr(self, "_last_pending_count", current_pending)
    last_open = getattr(self, "_last_open_count", current_open)

    needs_refresh = False
    refresh_reason = ""

    # Refresh grid ONLY when a position cycle has fully closed and 0 positions remain
    if getattr(self, "_max_open_in_cycle", 0) > 0 and current_open == 0 and current_pending > 0:
        needs_refresh = True
        refresh_reason = "Position cycle completed"
    elif current_open == 0 and current_pending > 0:
        # Check if pending orders are drifting or stale with NO open positions
        sym_pend = [o for o in getattr(self.broker, "pending_orders", {}).values() if getattr(o, "symbol", sym_name) == sym_name]
        if sym_pend:
            min_dist_to_price = min(abs(float(getattr(o, "trigger_price", current_price) or current_price) - current_price) for o in sym_pend)
            is_gold = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])
            drift_thresh = max(4.50 if is_gold else (10.00 if "ETH" in sym_name else (150.00 if "BTC" in sym_name else current_price * 0.0015)), current_price * 0.0008)
            now_ts = timestamp / 1000.0 if timestamp > 1e11 else timestamp
            oldest_age = max((now_ts - (float(getattr(o, "timestamp", now_ts) or now_ts) / 1000.0 if float(getattr(o, "timestamp", now_ts) or now_ts) > 1e11 else float(getattr(o, "timestamp", now_ts) or now_ts))) for o in sym_pend)
            
            last_drift_realign = getattr(self, "_last_stale_drift_realign_time", 0.0)
            if (min_dist_to_price > drift_thresh and oldest_age > 60.0 and (now_ts - last_drift_realign >= 60.0)) or (oldest_age > 300.0 and (now_ts - last_drift_realign >= 120.0)):
                needs_refresh = True
                refresh_reason = f"Stale pending traps drifted with 0 open positions (nearest dist: ${min_dist_to_price:.2f} > ${drift_thresh:.2f}, oldest age: {oldest_age:.0f}s)"
                self._last_stale_drift_realign_time = now_ts
        if not needs_refresh:
            # Debounce AI trend bias flip (minimum 120s cooldown between trend flip redeployments)
            curr_uni = str(getattr(self, "unidirectional_mode", getattr(self, "auto_universe_bias", ""))).upper()
            last_uni = str(getattr(self, "_last_synced_uni_mode", curr_uni)).upper()
            last_flip_time = getattr(self, "_last_trend_flip_deploy_time", 0.0)
            if (curr_uni and last_uni and curr_uni != last_uni and 
                    current_open == 0 and current_pending > 0 and 
                    (timestamp - last_flip_time) >= 120.0):
                needs_refresh = True
                refresh_reason = f"Trend bias confirmed flip ({last_uni} -> {curr_uni})"
                self._last_trend_flip_deploy_time = timestamp
            self._last_synced_uni_mode = curr_uni

    if needs_refresh:
        if refresh_reason == "Position cycle completed":
            cycle_start_pnl = getattr(self, "_cycle_start_realized_pnl", getattr(self.broker, "realized_pnl", 0.0))
            cycle_pnl = getattr(self.broker, "realized_pnl", 0.0) - cycle_start_pnl
            
            # Anti-duplication guard: ONLY record if not already recorded by exit handlers
            if not getattr(self, "_cycle_recorded", False):
                is_duplicate = False
                if hasattr(self, "cycle_history") and self.cycle_history:
                    last_c = self.cycle_history[-1]
                    if abs(float(last_c.get("exit_time", 0.0)) - timestamp) < 60.0 and abs(float(last_c.get("total_pnl", 0.0)) - cycle_pnl) < 0.1:
                        is_duplicate = True

                if not is_duplicate and abs(cycle_pnl) > 0.01:
                    last_trade_reason = None
                    if hasattr(self.broker, "closed_trades") and self.broker.closed_trades:
                        last_trade_reason = self.broker.closed_trades[-1].get("exit_reason")
                    reason = last_trade_reason or ("NATIVE_SL" if cycle_pnl < 0 else "NATIVE_TP")
                    dur = max(1.0, timestamp - getattr(self, "_cycle_start_time", timestamp))
                    self.record_trade_outcome(cycle_pnl, reason, dur, current_price)
                    self.current_cycle_id = getattr(self, "current_cycle_id", len(self.cycle_history)) + 1
                    self._cycle_recorded = True
                    if cycle_pnl < 0:
                        self._post_loss_cooldown = timestamp + 180.0
                        self._post_cycle_cooldown_until = timestamp + 180.0
                    else:
                        self._post_cycle_cooldown_until = timestamp + 90.0

            self._cycle_recorded = False  # Reset for next cycle
            self._max_open_in_cycle = 0
            self._basket_max_pnl = 0.0
            self._basket_peak_pnl = 0.0
            self.max_floating_pnl = -float("inf")
            self.in_runner_mode = False
            self._cycle_start_time = 0.0
            self._cycle_start_realized_pnl = 0.0
                
        print(f"[{self.symbol}] 🔄 [GRID REFRESH] {refresh_reason}. Canceling {current_pending} pending orders to deploy fresh grid.")
        try:
            if hasattr(self.broker, "cancel_all_orders"):
                self.broker.cancel_all_orders(symbol=self.symbol)
        except Exception as e:
            print(f"[{self.symbol}] ⚠️ Cancel orders failed: {e}. Will retry next tick.")
            return None
            
        self.deployed = False
        self._max_open_in_cycle = 0
        self._last_pending_count = 0
        self._last_open_count = 0
        
        post_cd = max(getattr(self, "_post_loss_cooldown", 0.0), getattr(self, "_post_cycle_cooldown_until", 0.0))
        if timestamp >= post_cd:
            self.deploy_traps(current_price, timestamp, force=True)
        else:
            remaining_cd = int(post_cd - timestamp)
            print(f"[{self.symbol}] ⏳ [POST-CYCLE COOLDOWN] Grid refresh pending. Waiting {remaining_cd}s cooldown before deploying fresh grid.")
        return None

    self._last_pending_count = current_pending
    self._last_open_count = current_open

    if self.use_grid_repair:
        self.repair_grid(current_price, timestamp)
    if self.use_auto_cleanup:
        self.cleanup_stale_grid_orders(current_price)

    if len(getattr(self.broker, "open_positions", {})) > 0:
        try:
            enforce_profit_lock(self, current_price, timestamp)
            enforce_trend_aware_position_guard(self, current_price, timestamp)  # 🔄 Trend flip → quick exit; trend aligned → hold for max profit
            trail_stop_loss_5m_structure(self, current_price, timestamp)
            align_basket_take_profits(self, current_price, timestamp)       # ATR basket TP alignment (fallback/tighten)
            enforce_position_tp(self, current_price, timestamp)             # Software-side TP guard — always take profit
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

    is_grid_full = len(getattr(self.broker, "open_positions", {})) >= getattr(self, "grid_levels", 5)
    if is_grid_full and getattr(self, "_fakeout_guard_enabled", False) and self._fakeout_recent_fills:
        # Per-symbol minimum distance before declaring a fakeout.
        # Requires substantial structural move against entry ($6+ on Gold) + at least 30s duration.
        sym_u = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
        fakeout_min_dist = max(current_price * 0.002, 1.0)

        expired_f_pids = []
        for f_pid, (entry_px, p_type, fill_tick) in list(self._fakeout_recent_fills.items()):
            ticks_elapsed = self._tick_counter - fill_tick
            if f_pid not in self.broker.open_positions:
                expired_f_pids.append(f_pid)
                continue
            if ticks_elapsed > getattr(self, "_fakeout_guard_ticks", 20):
                expired_f_pids.append(f_pid)
                continue

            pos = self.broker.open_positions[f_pid]
            # Minimum 30-second breathing room before evaluating any fakeout exit
            pos_open_time = float(getattr(pos, "entry_time", getattr(pos, "time_setup", 0.0)) or 0.0)
            if pos_open_time > 0 and (timestamp - pos_open_time) < 30.0:
                continue

            # Only flag fakeout if price has moved a substantial distance past entry
            if p_type == "BUY":
                is_fakeout = current_price < (entry_px - fakeout_min_dist)
            elif p_type == "SELL":
                is_fakeout = current_price > (entry_px + fakeout_min_dist)
            else:
                is_fakeout = False

            if is_fakeout:
                print(f"[{self.symbol}] 🚨 [FAKEOUT GUARD] {p_type} #{f_pid} reversed ${abs(current_price - entry_px):.2f} past entry after {ticks_elapsed} ticks. Closing.")
                self.broker.close_position(f_pid, current_price, timestamp)
                expired_f_pids.append(f_pid)
                self._post_loss_cooldown = timestamp + (3 * 60)  # 3 min cooldown on fakeout

        for ef_pid in expired_f_pids:
            self._fakeout_recent_fills.pop(ef_pid, None)

    summary = check_target_profit(self, current_price, timestamp)
    if summary is not None:
        exit_reason = summary.get("exit_reason", "TARGET_PROFIT")
        self.record_trade_outcome(summary.get("total_pnl", 0.0), exit_reason, summary.get("duration", 0.0), current_price)
        self._cycle_recorded = True
        pnl_val = float(summary.get("total_pnl", 0.0))
        if exit_reason == "STOP_LOSS" or pnl_val < 0:
            self._post_loss_cooldown = timestamp + (3 * 60)  # 3 min cooldown on Stop Loss
            self._post_cycle_cooldown_until = timestamp + (3 * 60)
            print(f"[{self.symbol}] ⏳ [COOLDOWN] Stop Loss hit (-${abs(pnl_val):.2f}). Halting grid deployment for 3 minutes.")
        elif exit_reason in ("TARGET_PROFIT", "PARTIAL_TP") or pnl_val > 0:
            self._post_cycle_cooldown_until = timestamp + 90.0
            print(f"[{self.symbol}] ⏳ [COOLDOWN] Profit secured (+${pnl_val:.2f}). Cooling down for 90s before next grid deployment to avoid chasing momentum.")
        else:
            self._post_cycle_cooldown_until = timestamp + 60.0
        
        self.current_cycle_id = getattr(self, "current_cycle_id", len(self.cycle_history)) + 1

        # CYCLE OVERLAP FIX: Hard MT5 position check before restarting.
        # Reset flags first, then verify MT5 is truly empty before deploying.
        self.deployed = False
        self.deploy_price = 0.0
        self.breakeven_activated = False
        self.in_runner_mode = False
        self.max_floating_pnl = -float("inf")
        self._runner_exit_cooldown_until = 0.0
        self._last_deploy_error_time = 0.0
        self._prev_open_pos_count = 0
        # Reset 3-stage TP flags for next cycle
        self._tp1_buy_taken = False
        self._tp1_sell_taken = False
        self._tp2_buy_taken = False
        self._tp2_sell_taken = False
        self._chandelier_buy_high = 0.0
        self._chandelier_sell_low = 0.0
        self._last_partial_tp_time = 0.0

        # Sync broker state after close
        if hasattr(self.broker, "process_tick"):
            try:
                self.broker.process_tick(current_price, current_price, timestamp)
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        # Verify MT5 reports truly zero positions before allowing redeploy
        mt5_clear = True
        try:
            import MetaTrader5 as _mt5_chk
            if _mt5_chk is not None and hasattr(_mt5_chk, "positions_get") and callable(getattr(_mt5_chk, "positions_get", None)):
                ex_s2 = self.broker.get_exness_symbol(self.symbol) if hasattr(self.broker, "get_exness_symbol") else self.symbol
                mt5_pos = _mt5_chk.positions_get(symbol=ex_s2)
                if not mt5_pos:
                    all_p2 = _mt5_chk.positions_get()
                    if all_p2:
                        clean_tgt2 = "XAU" if any(x in (ex_s2 or "").upper() for x in ["XAU", "GOLD"]) else (
                            "PAXG" if "PAXG" in (ex_s2 or "").upper() else
                            (ex_s2 or "").replace("USDT", "").replace("USDC", "").replace("USD", "").upper()
                        )
                        mt5_pos = [p for p in all_p2 if clean_tgt2 in str(p.symbol).upper()]
                if mt5_pos and len(mt5_pos) > 0:
                    mt5_clear = False
                    print(f"[{self.symbol}] ⏳ [CYCLE GUARD] Cycle ended but {len(mt5_pos)} position(s) still live on MT5 — delaying redeploy")
                    self._last_deploy_attempt_time = timestamp + 3.0  # Force a 3s wait before next deploy attempt
        except Exception as e:
            pass

        if getattr(self, "auto_restart", True) and mt5_clear:
            post_cd = max(getattr(self, "_post_loss_cooldown", 0.0), getattr(self, "_post_cycle_cooldown_until", 0.0))
            if timestamp >= post_cd:
                self.deploy_traps(current_price, timestamp, force=True)
            else:
                remaining_cd = int(post_cd - timestamp)
                print(f"[{self.symbol}] ⏳ [POST-CYCLE COOLDOWN] Waiting {remaining_cd}s cooldown before redeploying grid.")

        return summary

    return None


def deploy_traps(self, current_price: float, timestamp: float, *args, force: bool = False, bb_width: Optional[float] = None, **kwargs):
    """
    ⚡ UNBREAKABLE 100% RELIABLE GRID DEPLOYMENT ENGINE.
    Deploys exact tight grid traps directly to broker with zero silent skips or bypassing.
    """
    if not current_price or current_price <= 0:
        return

    cooldown_expiry = max(
        getattr(self, "_post_loss_cooldown", 0.0),
        getattr(self, "_post_cycle_cooldown_until", 0.0)
    )
    if timestamp < cooldown_expiry and not kwargs.get("manual_user_deploy", False):
        return  # Silently wait out the cooldown
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

    # ── Deploy debounce: max 1 redeploy per 2 s from UI (tick-engine force=True bypasses) ──
    _last_deploy_ts = getattr(self, "_last_deploy_ts", 0.0)
    if not force and (timestamp - _last_deploy_ts) < 2.0:
        return

    max_capacity = (getattr(self, "grid_levels", 5) or 5) * 2
    if not force and len(getattr(self.broker, "pending_orders", {})) >= max_capacity:
        return


    self._is_deploying = True

    try:
        if force and len(getattr(self.broker, "pending_orders", {})) > 0:
            if hasattr(self.broker, "cancel_all_orders"):
                try:
                    self.broker.cancel_all_orders()
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")

        digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)
        ask_ref = getattr(self.broker, "last_ask", current_price) or current_price
        bid_ref = getattr(self.broker, "last_bid", current_price) or current_price

        if hasattr(self.broker, "get_exness_symbol"):
            try:
                ex_sym = self.broker.get_exness_symbol(sym_name)
                import MetaTrader5 as mt5_ref
                if mt5_ref is not None and hasattr(mt5_ref, "symbol_info_tick"):
                    tick_info = mt5_ref.symbol_info_tick(ex_sym)
                    if tick_info and tick_info.ask > 0 and tick_info.bid > 0:
                        ask_ref = tick_info.ask
                        bid_ref = tick_info.bid
                        current_price = (ask_ref + bid_ref) / 2.0
                else:
                    # Linux/Wine VPS — fetch tick via REST bridge
                    import requests as _req
                    import os as _os
                    _bport = _os.getenv("WINE_BRIDGE_PORT", "8001")
                    _r = _req.get(f"http://127.0.0.1:{_bport}/tick?symbol={ex_sym}", timeout=2.0)
                    if _r.status_code == 200:
                        _td = _r.json()
                        _ask = float(_td.get("ask", 0))
                        _bid = float(_td.get("bid", 0))
                        if _ask > 0 and _bid > 0:
                            ask_ref = _ask
                            bid_ref = _bid
                            current_price = (_ask + _bid) / 2.0
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")


        if ask_ref <= 0: ask_ref = current_price
        if bid_ref <= 0: bid_ref = current_price

        gap_pct = float(getattr(self, "grid_gap", 0.07) or 0.07)
        offset_pct = float(getattr(self, "trap_offset", 0.07) or 0.07)
        
        is_manual = getattr(self, "manual_override_active", False)

        if not is_manual and hasattr(self, "auto_reading_engine"):
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
                    if "recommended_size" in eval_res:
                        self.order_size = float(eval_res["recommended_size"])
                    if "recommended_target_profit" in eval_res:
                        self.deploy_target_profit = float(eval_res["recommended_target_profit"])
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        off_ratio = (offset_pct / 100.0) if offset_pct >= 0.50 else (offset_pct if offset_pct < 0.01 else offset_pct / 100.0)
        gap_ratio = (gap_pct / 100.0) if gap_pct >= 0.50 else (gap_pct if gap_pct < 0.01 else gap_pct / 100.0)

        if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]):
            # Give Gold solid breakout threshold to filter out false wicks during consolidation
            gap_ratio = min(0.0040, max(0.0020, gap_ratio))
            off_ratio = min(0.0045, max(0.0025, off_ratio))
        elif "ETH" in sym_name:
            gap_ratio = min(0.0020, max(0.0005, gap_ratio))
            off_ratio = min(0.0025, max(0.0010, off_ratio))

        buy_offset_val = current_price * off_ratio if off_ratio > 0 else current_price * 0.001
        gap_val = current_price * gap_ratio if gap_ratio > 0 else current_price * 0.001
        
        b_min_stop = 0.0
        if hasattr(self.broker, "get_cached_symbol_info") and hasattr(self.broker, "get_exness_symbol"):
            try:
                ex_s = self.broker.get_exness_symbol(sym_name)
                s_info = self.broker.get_cached_symbol_info(ex_s)
                if s_info:
                    b_min_stop = max((getattr(s_info, "trade_stops_level", 0) or 0) * s_info.point, s_info.point * 50.0)
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        base_min_off = max(current_price * 0.0005, 0.0001)
        min_offset_dist = max(b_min_stop + (gap_val * 0.5), base_min_off)
        buy_offset_val = max(float(buy_offset_val), min_offset_dist)
        sell_offset_val = buy_offset_val
        
        min_gap_dist = max(current_price * 0.0003, 0.0001)
        gap_val = max(float(gap_val), min_gap_dist)
        buy_offset_val = round(buy_offset_val, digits)
        sell_offset_val = round(sell_offset_val, digits)
        gap_val = round(gap_val, digits)

        t_5m, t_htf, rsi_1m = "NEUTRAL", "NEUTRAL", 50.0
        atr_5m = None
        try:
            from core.data import get_historical_klines, calculate_technical_indicators
            import numpy as np
            df_1m  = get_historical_klines(sym_name, interval="1m", limit=250)
            df_5m  = get_historical_klines(sym_name, interval="3m", limit=250)
            df_htf = get_historical_klines(sym_name, interval="15m", limit=250)  # Real 15m as HTF
            
            # Manually calculate ATR 5m directly from df_5m to ensure reliability
            if df_5m is not None and not df_5m.empty and len(df_5m) > 5:
                highs = df_5m["high"].values
                lows = df_5m["low"].values
                closes = df_5m["close"].values
                tr_list = []
                for i in range(1, len(df_5m)):
                    tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                    tr_list.append(tr)
                if tr_list:
                    atr_5m = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else float(np.mean(tr_list))

            tech_1m  = calculate_technical_indicators(df_1m)  if (df_1m  is not None and not df_1m.empty)  else {}
            tech_5m  = calculate_technical_indicators(df_5m)  if (df_5m  is not None and not df_5m.empty)  else {}
            tech_htf = calculate_technical_indicators(df_htf) if (df_htf is not None and not df_htf.empty) else {}
            
            t_5m  = tech_5m.get("trend",  "NEUTRAL") or "NEUTRAL"
            t_htf = tech_htf.get("trend", "NEUTRAL") or "NEUTRAL"  # 5m wide-window HTF (replaces 15m)
            rsi_1m = float(tech_1m.get("rsi", 50.0) or 50.0)
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

        if atr_5m is None or atr_5m <= 0:
            atr_5m = current_price * 0.002

        is_gold = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])
        if is_gold:
            min_sl_dist = max(12.00, current_price * 0.0030, atr_5m * 2.2)
        elif "BTC" in sym_name:
            min_sl_dist = max(500.0, current_price * 0.0060, atr_5m * 3.0)
        elif "ETH" in sym_name:
            min_sl_dist = max(35.0, current_price * 0.0120, atr_5m * 3.0)
        else:
            min_sl_dist = max(current_price * 0.005, atr_5m * 2.5)

        # Anti-hunt structural gap buffer: Extra cushion beyond order blocks / swing wicks
        # Prevents market maker liquidity sweeps from hunting SL before the real move starts
        if is_gold:
            anti_hunt_buffer = max(3.50, atr_5m * 0.75)
        elif "BTC" in sym_name:
            anti_hunt_buffer = max(60.0, atr_5m * 0.75)
        elif "ETH" in sym_name:
            anti_hunt_buffer = max(5.0, atr_5m * 0.75)
        else:
            anti_hunt_buffer = max(current_price * 0.0015, atr_5m * 0.75)

        acc_eq = self.broker.get_equity() if hasattr(self.broker, "get_equity") else 1000.0
        _cfg_levels = getattr(self, "grid_levels", 5) or 5  # Hard ceiling from bot config
        if not is_manual and hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict) and "recommended_levels" in self.last_auto_eval:
            # AutoReadingEngine may reduce levels for low-confidence markets but NEVER exceeds the configured cap
            effective_levels = min(int(self.last_auto_eval["recommended_levels"]), _cfg_levels)
        else:
            effective_levels = _cfg_levels

        if is_gold:
            effective_levels = min(effective_levels, 3)

        dyn_tp_factor = max(3.0, float(effective_levels * 1.0))
        calculated_dynamic_tp = gap_val * dyn_tp_factor

        # Guarantee minimum 1.5x R:R over stop loss so every win outpaces average loss
        rr_min_tp = min_sl_dist * 1.50

        if is_gold:
            # On Gold / PAXG: Enforce minimum $16-$25 distance (at least 1.5x SL and 3.0x ATR for institutional R:R)
            min_tp_dist = max(16.0, current_price * 0.0035, atr_5m * 3.0, calculated_dynamic_tp, rr_min_tp)
        elif "ETH" in sym_name:
            # On ETH: Enforce minimum $15-$25 distance (0.5% - 1.0% move), at least 3x ATR
            min_tp_dist = max(15.0, current_price * 0.0050, atr_5m * 3.0, calculated_dynamic_tp, rr_min_tp)
        else:
            min_tp_dist = max(calculated_dynamic_tp, b_min_stop * 5.0, rr_min_tp)

        side_cfg = str(getattr(self, "pending_order_side_mode", "AUTO_ADAPTIVE")).upper()
        _auto_eval_decided = False
        if not is_manual and side_cfg == "AUTO_ADAPTIVE" and hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict):
            auto_uni = str(self.last_auto_eval.get("unidirectional_mode", "AUTO")).upper()
            if "BUY" in auto_uni and "ONLY" in auto_uni:
                side_cfg = "BUY_ONLY"
                _auto_eval_decided = True
            elif "SELL" in auto_uni and "ONLY" in auto_uni:
                side_cfg = "SELL_ONLY"
                _auto_eval_decided = True
            elif "DUAL" in auto_uni or "BOTH" in auto_uni:
                side_cfg = "BOTH_SIDES"
                _auto_eval_decided = True

        if "DUAL" in side_cfg or "BOTH" in side_cfg:
            place_buy, place_sell = True, True
        elif (("BUY" in side_cfg and "ONLY" in side_cfg) or side_cfg == "BUY"):
            place_buy, place_sell = True, False
        elif (("SELL" in side_cfg and "ONLY" in side_cfg) or side_cfg == "SELL"):
            place_buy, place_sell = False, True
        elif _auto_eval_decided:
            # AutoReadingEngine already evaluated — trust its decision, don't override
            place_buy, place_sell = True, True
        elif is_manual:
            # In manual mode, if no side is explicitly selected, default to DUAL (no secret trend filtering)
            place_buy, place_sell = True, True
        else:
            # FALLBACK ONLY when AutoReadingEngine did NOT run (auto_reading disabled).
            # Uses 5m fast / 5m wide-window (HTF) trend as standalone direction filter.
            if t_5m == "BULLISH" or (t_5m == "NEUTRAL" and t_htf == "BULLISH"):
                place_buy, place_sell = True, False
            elif t_5m == "BEARISH" or (t_5m == "NEUTRAL" and t_htf == "BEARISH"):
                place_buy, place_sell = False, True
            else:
                place_buy, place_sell = True, True

        # STRICT DIRECTIONAL LOCK: Invariants must NEVER be violated
        if "SELL" in side_cfg and "ONLY" in side_cfg:
            place_buy = False
        elif "BUY" in side_cfg and "ONLY" in side_cfg:
            place_sell = False

        # ─────────────────────────────────────────────────────────────
        # DIRECTIONAL MODE: Limit orders from optimal price levels
        #   SELL confirmed → SELL_LIMIT above current (sell the bounce at TOP/resistance)
        #   BUY  confirmed → BUY_LIMIT  below current (buy the dip  at BOTTOM/support)
        #   RANGING        → BUY_STOP + SELL_STOP breakout mode (unchanged)
        # Limit orders give a BETTER entry than stop orders → more profit per trade.
        # ─────────────────────────────────────────────────────────────

        # --- POSITION HEDGE PREVENTION ---
        # Never place orders in the opposite direction of an open OR pending position basket, UNLESS it's a 100% confirmed trend.
        _open_pos = getattr(self.broker, "open_positions", {})
        _pending_ord = getattr(self.broker, "pending_orders", {})
        
        has_open_sells = any("SELL" in str(getattr(p, "type", "")).upper() for p in _open_pos.values())
        has_open_buys  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in _open_pos.values())
        
        has_pending_sells = any("SELL" in str(getattr(p, "type", "")).upper() for p in _pending_ord.values())
        has_pending_buys  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in _pending_ord.values())

        has_sells = has_open_sells or has_pending_sells
        has_buys = has_open_buys or has_pending_buys
        
        _is_100pct_grid = is_auto_100pct_confirmed(self) and not is_manual  # AUTO only — never fires in manual mode

        _is_hedged_override = False

        # HARD HTF MOMENTUM GATE: Never place counter-trend orders against confirmed trend
        if not is_manual:
            if "SELL" in side_cfg and "ONLY" in side_cfg:
                # In SELL_ONLY mode, place_buy is already strictly False.
                # Only block place_sell if HTF is decisively BULLISH against our bias.
                if t_htf == "BULLISH" and t_5m == "BULLISH":
                    place_sell = False
            elif "BUY" in side_cfg and "ONLY" in side_cfg:
                # In BUY_ONLY mode, place_sell is already strictly False.
                # Only block place_buy if HTF is decisively BEARISH against our bias.
                if t_htf == "BEARISH" and t_5m == "BEARISH":
                    place_buy = False
            else:
                if t_htf == "BULLISH" or t_5m == "BULLISH":
                    place_sell = False
                elif t_htf == "BEARISH" or t_5m == "BEARISH":
                    place_buy = False

        if has_sells and not _is_100pct_grid:
            if t_htf != "BULLISH" and t_5m != "BULLISH":
                place_buy = False
        elif has_sells and _is_100pct_grid and place_buy:
            _is_hedged_override = True

        if has_buys and not _is_100pct_grid:
            if t_htf != "BEARISH" and t_5m != "BEARISH":
                place_sell = False
        elif has_buys and _is_100pct_grid and place_sell:
            _is_hedged_override = True

        # Invariant re-check: SELL_ONLY must NEVER have place_buy=True, BUY_ONLY must NEVER have place_sell=True
        if "SELL" in side_cfg and "ONLY" in side_cfg:
            place_buy = False
        elif "BUY" in side_cfg and "ONLY" in side_cfg:
            place_sell = False

        if not place_buy and not place_sell:
            print(f"[{sym_name}] ⏳ [TRAP GATED] Both directions blocked (side_cfg={side_cfg}, HTF={t_htf}, 5m={t_5m}). Zero orders placed.")
            self._is_deploying = False
            return

        directional_sell = place_sell and not place_buy   # Pure sell signal
        directional_buy  = place_buy  and not place_sell  # Pure buy signal
        ranging_mode     = place_buy  and place_sell      # Both sides = choppy

        # 3. Chop Restriction (Limit Exposure in Ranging Markets)
        # USER REQUEST: Do not deploy in ranging market without clear trend confirmation.
        if ranging_mode and not is_manual:
            print(f"[{sym_name}] ⏳ [TREND WAIT] Market is ranging. Waiting for clear trend confirmation before deploying.")
            self._is_deploying = False
            return

        # ── 100% Trend Confirmed: aggressive grid mode ──────────────────────────
        # When is_auto_100pct_confirmed fires we place 3 orders (2 Stops + 1 Limit):
        #   • Stop-1 : closest SMC breakout level  → catches initial momentum burst
        #   • Stop-2 : next SMC level ≥ 0.5×ATR away → rides continuation (ATR gap
        #              guard prevents both stops filling on the same candle)
        #   • Limit-1: best structural DCA level below/above price → mean-reversion fill
        #   • TP extended to 1.77× min_tp_dist   → ride the full confirmed move
        #   • Entry offset tightened to 0.20× ATR → enter as close to price as safe

        if (directional_sell or directional_buy) and _is_100pct_grid:
            dir_tp_dist     = min_tp_dist * 1.77  # Extended TP to ride full confirmed move
            # 100% CONFIRMED: Deploy ALL 3 orders in trend direction (2 Stops + 1 Limit pullback)
            effective_levels = 3 if not _is_hedged_override else 2
            _confirmed_offset_mult = 0.20          # Backtest optimal entry — tight breakout
            _confirmed_gap_mult    = 0.70          # Compressed gap → denser continuation
        elif directional_sell or directional_buy:
            dir_tp_dist     = min_tp_dist * 1.15  # Scalp/Momentum TP
            # DIRECTIONAL UNCONFIRMED (<100%): Deploy ONLY 1 single primary STOP order
            if is_manual:
                effective_levels = min(3, max(1, _cfg_levels))
            else:
                effective_levels = 1  # Auto unconfirmed: only 1 primary stop order fills with momentum
            _confirmed_offset_mult = 0.25          # Tight entry offset so stop fills quickly
            _confirmed_gap_mult    = 1.00
        else:
            dir_tp_dist     = min_tp_dist
            _confirmed_offset_mult = 0.70  # Ranging Mode: 0.70x ATR breathing room
            _confirmed_gap_mult    = 1.00

        placed_count = 0
        # 1. Live Spread Anti-Hunt Protection (Adds 1.5x live spread buffer so broker spikes never falsely trigger traps)
        live_spread = max(0.0, float(ask_ref - bid_ref)) if (ask_ref > 0 and bid_ref > 0 and ask_ref >= bid_ref) else 0.0
        spread_anti_hunt_buffer = max(live_spread * 1.5, 0.0)

        # 2. Dynamic ATR-Based Trap Placement — scaled by confirmation state & live spread
        # Cap ATR offset to 1.5× configured value — prevents large-ATR symbols (BTC/ETH)
        # from pushing traps far beyond the user-configured distance.
        _max_atr_offset     = buy_offset_val * 1.5
        dynamic_atr_offset  = min((atr_5m * _confirmed_offset_mult) if (atr_5m is not None and atr_5m > 0) else 0.0, _max_atr_offset)
        
        if directional_sell or directional_buy:
            if _is_100pct_grid:
                # 100% CONFIRMED: Get in fast. Ignore wider buy_offset_val to allow very tight trap placement.
                base_start_offset = max(b_min_stop + (current_price * 0.0001), dynamic_atr_offset) + spread_anti_hunt_buffer
            else:
                # Directional mode (<100% confirmed): Single tight STOP entry to capture momentum breakdown/breakout
                base_start_offset = max(b_min_stop + (current_price * 0.0002), dynamic_atr_offset) + spread_anti_hunt_buffer
        else:
            base_start_offset = max(b_min_stop + (current_price * 0.0004), dynamic_atr_offset, buy_offset_val) + spread_anti_hunt_buffer
        
        # ═══════════════════════════════════════════════════════════════════════
        # SMART CONFLUENCE PLACEMENT ENGINE
        # Only place stop orders where institutional levels exist nearby.
        # No blind fixed-interval placement — every trap has a structural reason.
        # ═══════════════════════════════════════════════════════════════════════

        # ── Collect all known institutional reference levels ──────────────────
        smc_eval = self.last_auto_eval if (hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict)) else {}

        # Order Blocks
        bull_ob   = float(smc_eval.get("bullish_ob",       0.0) or 0.0)
        bear_ob   = float(smc_eval.get("bearish_ob",       0.0) or 0.0)
        # Fair Value Gap edges
        bull_fvg_lo = float(smc_eval.get("bullish_fvg_low",  0.0) or 0.0)
        bull_fvg_hi = float(smc_eval.get("bullish_fvg_high", 0.0) or 0.0)
        bear_fvg_lo = float(smc_eval.get("bearish_fvg_low",  0.0) or 0.0)
        bear_fvg_hi = float(smc_eval.get("bearish_fvg_high", 0.0) or 0.0)
        # Liquidity pools
        buy_liq   = float(smc_eval.get("buy_liquidity",    0.0) or 0.0)
        sell_liq  = float(smc_eval.get("sell_liquidity",   0.0) or 0.0)
        # VWAP
        vwap_dev  = float(smc_eval.get("vwap_dev_pct",     0.0) or 0.0)
        vwap_px   = current_price / (1.0 + vwap_dev / 100.0) if abs(vwap_dev) > 0.01 else 0.0

        # Swing high/low from 5m cache
        swing_hi = float(getattr(self, "_5m_klines_cache", None) is not None and
                         hasattr(self, "_5m_klines_cache") and
                         self._5m_klines_cache is not None and
                         not self._5m_klines_cache.empty and
                         self._5m_klines_cache["high"].max() or 0.0) if hasattr(self, "_5m_klines_cache") else 0.0
        swing_lo = 0.0
        try:
            if hasattr(self, "_5m_klines_cache") and self._5m_klines_cache is not None and not self._5m_klines_cache.empty:
                swing_hi = float(self._5m_klines_cache["high"].values[-8:].max())
                swing_lo = float(self._5m_klines_cache["low"].values[-8:].min())
        except Exception:
            swing_hi = swing_lo = 0.0

        # ── Build candidate level pools: RESISTANCE (above price) & SUPPORT (below price) ──
        snap_tol = gap_val * 1.5   # Snap tolerance: 1.5× gap — levels within this are "nearby"

        # Each entry: (price, label, score_contribution)
        resistance_candidates: list = []  # levels above ask (RESISTANCE / SUPPLY: Bearish OBs, FVGs, Swing Highs)
        support_candidates:    list = []  # levels below bid (SUPPORT / DEMAND: Bullish OBs, FVGs, Swing Lows)

        def _add_resistance(px: float, label: str, score: int):
            # Must be valid for MT5: at least b_min_stop away from ask
            if px >= ask_ref + b_min_stop:
                resistance_candidates.append((round(px, digits), label, score))

        def _add_support(px: float, label: str, score: int):
            # Must be valid for MT5: at least b_min_stop away from bid
            if px <= bid_ref - b_min_stop:
                support_candidates.append((round(px, digits), label, score))

        # RESISTANCE (above current price) — prime zones to pre-trap bounces with SELL_LIMIT:
        # 1. Bearish Order Block (institutional supply where smart money initiated dumps)
        if bear_ob > 0:       _add_resistance(bear_ob,     "BearOB",   4)
        # 2. Bearish FVG boundaries (imbalance supply zones)
        if bear_fvg_hi > 0:   _add_resistance(bear_fvg_hi, "BearFVG",  3)
        if bear_fvg_lo > 0:   _add_resistance(bear_fvg_lo, "BearFVG",  2)
        # 3. Buy-side Liquidity Pool & Swing Highs (stops waiting to be swept)
        if buy_liq > 0:       _add_resistance(buy_liq,     "BuyLiq",   3)
        if swing_hi > 0:      _add_resistance(swing_hi,    "SwingHi",  2)
        # 4. VWAP if above price
        if vwap_px >= ask_ref + b_min_stop: _add_resistance(vwap_px, "VWAP", 1)
        # 5. Breaker Block (if bull_ob is now above price after a breakdown)
        if bull_ob >= ask_ref + b_min_stop: _add_resistance(bull_ob, "BreakerOB", 2)

        # SUPPORT (below current price) — prime zones to pre-trap dips with BUY_LIMIT:
        # 1. Bullish Order Block (institutional demand where smart money initiated pumps)
        if bull_ob > 0:       _add_support(bull_ob,     "BullOB",   4)
        # 2. Bullish FVG boundaries (imbalance demand zones)
        if bull_fvg_lo > 0:   _add_support(bull_fvg_lo, "BullFVG",  3)
        if bull_fvg_hi > 0:   _add_support(bull_fvg_hi, "BullFVG",  2)
        # 3. Sell-side Liquidity Pool & Swing Lows (stops waiting to be swept)
        if sell_liq > 0:      _add_support(sell_liq,    "SellLiq",  3)
        if swing_lo > 0:      _add_support(swing_lo,    "SwingLo",  2)
        # 4. VWAP if below price
        if vwap_px > 0 and vwap_px <= bid_ref - b_min_stop: _add_support(vwap_px, "VWAP", 1)
        # 5. Breaker Block (if bear_ob is now below price after a breakout)
        if bear_ob > 0 and bear_ob <= bid_ref - b_min_stop: _add_support(bear_ob, "BreakerOB", 2)

        # ── Merge nearby candidates (within snap_tol) & score ──
        def _merge_and_score(candidates: list, is_resistance: bool) -> list:
            """Cluster nearby levels, sum scores, return sorted by proximity to price."""
            merged: list = []
            used = set()
            for idx, (px, lbl, sc) in enumerate(candidates):
                if idx in used:
                    continue
                cluster_px  = [px]
                cluster_lbl = [lbl]
                cluster_sc  = sc
                for jdx, (px2, lbl2, sc2) in enumerate(candidates):
                    if jdx != idx and jdx not in used and abs(px2 - px) <= snap_tol:
                        cluster_px.append(px2)
                        cluster_lbl.append(lbl2)
                        cluster_sc += sc2
                        used.add(jdx)
                used.add(idx)
                best_px = round(sum(cluster_px) / len(cluster_px), digits)  # centroid
                merged.append((cluster_sc, best_px, "+".join(sorted(set(cluster_lbl)))))
            
            # Proximity sorting:
            # Resistance (above price): lowest valid level is closest to price -> sort ASCENDING
            # Support (below price): highest valid level is closest to price -> sort DESCENDING
            if is_resistance:
                return sorted(merged, key=lambda x: x[1])
            else:
                return sorted(merged, key=lambda x: x[1], reverse=True)

        merged_resistance = _merge_and_score(resistance_candidates, is_resistance=True)
        merged_support    = _merge_and_score(support_candidates, is_resistance=False)

        # ── Fallback Anchors ──
        # Guarantees structural levels exist even if SMC data is sparse
        ranging_mode = not (directional_buy or directional_sell)
        if not merged_resistance and (directional_sell or directional_buy or ranging_mode):
            merged_resistance = [(1, round(ask_ref + base_start_offset, digits), "Anchor")]
        if not merged_support and (directional_buy or directional_sell or ranging_mode):
            merged_support = [(1, round(bid_ref - base_start_offset, digits), "Anchor")]

        # ── Order Placement Helpers with Structural TP & SL ──
        placed_count = 0

        def _place_sell_limit(px: float, label: str, level_idx: int):
            nonlocal placed_count
            if placed_count + len(_open_pos) >= effective_levels: return
            _mult = 1.0 if _is_hedged_override else self.order_size_multiplier
            sz  = self.calculate_level_size(self.order_size, _mult, level_idx)
            # Smart TP: target extended structural support near our target distance (min 90% of dir_tp_dist)
            smart_tp = round(px - dir_tp_dist, digits)
            valid_tps = [c_px for (_, c_px, _) in merged_support if c_px <= px - (dir_tp_dist * 0.85) and c_px >= px - (dir_tp_dist * 2.2)]
            if valid_tps:
                smart_tp = min(valid_tps, key=lambda c: abs(c - (px - dir_tp_dist)))
            # Smart SL: protected above nearest structural resistance over entry + anti-hunt cushion
            smart_sl = round(px + min_sl_dist + anti_hunt_buffer, digits)
            valid_sls = [c_px for (_, c_px, _) in merged_resistance if c_px >= px + min_sl_dist and c_px <= px + (min_sl_dist * 2.5)]
            if valid_sls:
                smart_sl = round(max(valid_sls) + anti_hunt_buffer, digits)
            # Enforce Institutional R:R (TP distance >= 1.5x SL distance)
            actual_sl_dist = abs(smart_sl - px)
            if abs(px - smart_tp) < actual_sl_dist * 1.50:
                smart_tp = round(px - (actual_sl_dist * 1.50), digits)
            try:
                r = self.broker.place_order("SELL_LIMIT", px, sz, timestamp, tp=smart_tp, sl=smart_sl)
                if r:
                    placed_count += 1
                    self.active_sell_levels.append(px)
                    print(f"[{sym_name}] 🧱 [SELL_LIMIT_BOUNCE|{label}] @ ${px:,.{digits}f}  TP:${smart_tp:,.{digits}f}  SL:${smart_sl:,.{digits}f} (+${anti_hunt_buffer:.2f} anti-hunt) sz:{sz}")
            except Exception as e:
                print(f"[{sym_name}] SELL_LIMIT error @ {px}: {e}")

        def _place_buy_limit(px: float, label: str, level_idx: int):
            nonlocal placed_count
            if placed_count + len(_open_pos) >= effective_levels: return
            _mult = 1.0 if _is_hedged_override else self.order_size_multiplier
            sz  = self.calculate_level_size(self.order_size, _mult, level_idx)
            # Smart TP: target extended structural resistance near our target distance (min 90% of dir_tp_dist)
            smart_tp = round(px + dir_tp_dist, digits)
            valid_tps = [c_px for (_, c_px, _) in merged_resistance if c_px >= px + (dir_tp_dist * 0.85) and c_px <= px + (dir_tp_dist * 2.2)]
            if valid_tps:
                smart_tp = min(valid_tps, key=lambda c: abs(c - (px + dir_tp_dist)))
            # Smart SL: protected below nearest structural support under entry - anti-hunt cushion
            smart_sl = round(px - min_sl_dist - anti_hunt_buffer, digits)
            valid_sls = [c_px for (_, c_px, _) in merged_support if c_px <= px - min_sl_dist and c_px >= px - (min_sl_dist * 2.5)]
            if valid_sls:
                smart_sl = round(min(valid_sls) - anti_hunt_buffer, digits)
            # Enforce Institutional R:R (TP distance >= 1.5x SL distance)
            actual_sl_dist = abs(px - smart_sl)
            if abs(smart_tp - px) < actual_sl_dist * 1.50:
                smart_tp = round(px + (actual_sl_dist * 1.50), digits)
            try:
                r = self.broker.place_order("BUY_LIMIT", px, sz, timestamp, tp=smart_tp, sl=smart_sl)
                if r:
                    placed_count += 1
                    self.active_buy_levels.append(px)
                    print(f"[{sym_name}] 🧺 [BUY_LIMIT_DIP|{label}] @ ${px:,.{digits}f}  TP:${smart_tp:,.{digits}f}  SL:${smart_sl:,.{digits}f} (-${anti_hunt_buffer:.2f} anti-hunt) sz:{sz}")
            except Exception as e:
                print(f"[{sym_name}] BUY_LIMIT error @ {px}: {e}")

        def _place_sell_stop(px: float, label: str, level_idx: int):
            nonlocal placed_count
            if placed_count + len(_open_pos) >= effective_levels: return
            _mult = 1.0 if _is_hedged_override else self.order_size_multiplier
            sz  = self.calculate_level_size(self.order_size, _mult, level_idx)
            smart_tp = round(px - dir_tp_dist, digits)
            valid_tps = [c_px for (_, c_px, _) in merged_support if c_px <= px - (dir_tp_dist * 0.85) and c_px >= px - (dir_tp_dist * 2.2)]
            if valid_tps:
                smart_tp = min(valid_tps, key=lambda c: abs(c - (px - dir_tp_dist)))
            smart_sl = round(px + min_sl_dist + anti_hunt_buffer, digits)
            valid_sls = [c_px for (_, c_px, _) in merged_resistance if c_px >= px + min_sl_dist and c_px <= px + (min_sl_dist * 2.5)]
            if valid_sls:
                smart_sl = round(max(valid_sls) + anti_hunt_buffer, digits)
            # Enforce Institutional R:R (TP distance >= 1.5x SL distance)
            actual_sl_dist = abs(smart_sl - px)
            if abs(px - smart_tp) < actual_sl_dist * 1.50:
                smart_tp = round(px - (actual_sl_dist * 1.50), digits)
            try:
                r = self.broker.place_order("SELL_STOP", px, sz, timestamp, tp=smart_tp, sl=smart_sl)
                if r:
                    placed_count += 1
                    self.active_sell_levels.append(px)
                    print(f"[{sym_name}] 📉 [SELL_STOP_BREAKDOWN|{label}] @ ${px:,.{digits}f}  TP:${smart_tp:,.{digits}f}  SL:${smart_sl:,.{digits}f} (+${anti_hunt_buffer:.2f} anti-hunt) sz:{sz}")
            except Exception as e:
                print(f"[{sym_name}] SELL_STOP error @ {px}: {e}")

        def _place_buy_stop(px: float, label: str, level_idx: int):
            nonlocal placed_count
            if placed_count + len(_open_pos) >= effective_levels: return
            _mult = 1.0 if _is_hedged_override else self.order_size_multiplier
            sz  = self.calculate_level_size(self.order_size, _mult, level_idx)
            smart_tp = round(px + dir_tp_dist, digits)
            valid_tps = [c_px for (_, c_px, _) in merged_resistance if c_px >= px + (dir_tp_dist * 0.85) and c_px <= px + (dir_tp_dist * 2.2)]
            if valid_tps:
                smart_tp = min(valid_tps, key=lambda c: abs(c - (px + dir_tp_dist)))
            smart_sl = round(px - min_sl_dist - anti_hunt_buffer, digits)
            valid_sls = [c_px for (_, c_px, _) in merged_support if c_px <= px - min_sl_dist and c_px >= px - (min_sl_dist * 2.5)]
            if valid_sls:
                smart_sl = round(min(valid_sls) - anti_hunt_buffer, digits)
            # Enforce Institutional R:R (TP distance >= 1.5x SL distance)
            actual_sl_dist = abs(px - smart_sl)
            if abs(smart_tp - px) < actual_sl_dist * 1.50:
                smart_tp = round(px + (actual_sl_dist * 1.50), digits)
            try:
                r = self.broker.place_order("BUY_STOP", px, sz, timestamp, tp=smart_tp, sl=smart_sl)
                if r:
                    placed_count += 1
                    self.active_buy_levels.append(px)
                    print(f"[{sym_name}] 📈 [BUY_STOP_BREAKOUT|{label}] @ ${px:,.{digits}f}  TP:${smart_tp:,.{digits}f}  SL:${smart_sl:,.{digits}f} (-${anti_hunt_buffer:.2f} anti-hunt) sz:{sz}")
            except Exception as e:
                print(f"[{sym_name}] BUY_STOP error @ {px}: {e}")

        self.active_buy_levels  = []
        self.active_sell_levels = []

        # Minimum spacing between orders on same side
        _min_stop_gap_confirmed   = atr_5m * 0.5 if (atr_5m and atr_5m > 0) else (current_price * 0.003)
        _min_stop_gap_unconfirmed = atr_5m * 0.8 if (atr_5m and atr_5m > 0) else (current_price * 0.005)
        _min_stop_gap = _min_stop_gap_confirmed if _is_100pct_grid else _min_stop_gap_unconfirmed

        # ── INSTITUTIONAL PRE-MOVE TRAP DEPLOYMENT ──
        if directional_sell:
            # ── CONFIRMED BEARISH (SELL MODE) ──
            # User requirement: Prioritize STOP orders (SELL_STOP) so momentum fills immediately.
            # Only deploy all 3 orders if 100% confirmed. If unconfirmed, deploy 1 single primary STOP order.

            # 1. Primary Momentum Breakdown Trap: SELL_STOP below market price
            # Placed tightly below bid so downward momentum fills immediately
            primary_stop_px = round(bid_ref - base_start_offset, digits)
            stop1_cand = None
            if merged_support:
                for (_, s_px, s_lb) in merged_support:
                    if s_px <= bid_ref - base_start_offset and s_px >= bid_ref - (base_start_offset * 1.3):
                        stop1_cand = (s_px, s_lb)
                        break
            stop1_px = stop1_cand[0] if stop1_cand else primary_stop_px
            stop1_lb = stop1_cand[1] if stop1_cand else "Momentum"
            _place_sell_stop(stop1_px, stop1_lb, 0)

            # 2. Continuation Breakdown Trap: SELL_STOP further below support floor (rides continuation)
            if effective_levels >= 2:
                stop2_cand = None
                if merged_support:
                    for (_, s_px, s_lb) in merged_support:
                        if s_px <= stop1_px - _min_stop_gap:
                            stop2_cand = (s_px, s_lb)
                            break
                stop2_px = stop2_cand[0] if stop2_cand else round(stop1_px - _min_stop_gap, digits)
                stop2_lb = stop2_cand[1] if stop2_cand else "Continuation"
                _place_sell_stop(stop2_px, stop2_lb, 1)

            # 3. Pullback / DCA Trap: SELL_LIMIT above market price at resistance / OB (catches retracement wick)
            if effective_levels >= 3:
                lim1_px = merged_resistance[0][1] if merged_resistance else round(ask_ref + base_start_offset, digits)
                lim1_lb = merged_resistance[0][2] if merged_resistance else "Supply"
                lim1_px = max(lim1_px, round(ask_ref + base_start_offset, digits))
                _place_sell_limit(lim1_px, lim1_lb, 2)

        elif directional_buy:
            # ── CONFIRMED BULLISH (BUY MODE) ──
            # User requirement: Prioritize STOP orders (BUY_STOP) so momentum fills immediately.
            # Only deploy all 3 orders if 100% confirmed. If unconfirmed, deploy 1 single primary STOP order.

            # 1. Primary Momentum Breakout Trap: BUY_STOP above market price
            # Placed tightly above ask so upward momentum fills immediately
            primary_stop_px = round(ask_ref + base_start_offset, digits)
            stop1_cand = None
            if merged_resistance:
                for (_, r_px, r_lb) in merged_resistance:
                    if r_px >= ask_ref + base_start_offset and r_px <= ask_ref + (base_start_offset * 1.3):
                        stop1_cand = (r_px, r_lb)
                        break
            stop1_px = stop1_cand[0] if stop1_cand else primary_stop_px
            stop1_lb = stop1_cand[1] if stop1_cand else "Momentum"
            _place_buy_stop(stop1_px, stop1_lb, 0)

            # 2. Continuation Breakout Trap: BUY_STOP further above resistance ceiling (rides continuation)
            if effective_levels >= 2:
                stop2_cand = None
                if merged_resistance:
                    for (_, r_px, r_lb) in merged_resistance:
                        if r_px >= stop1_px + _min_stop_gap:
                            stop2_cand = (r_px, r_lb)
                            break
                stop2_px = stop2_cand[0] if stop2_cand else round(stop1_px + _min_stop_gap, digits)
                stop2_lb = stop2_cand[1] if stop2_cand else "Continuation"
                _place_buy_stop(stop2_px, stop2_lb, 1)

            # 3. Pullback / DCA Trap: BUY_LIMIT below market price at support / OB (catches dip wick)
            if effective_levels >= 3:
                lim1_px = merged_support[0][1] if merged_support else round(bid_ref - base_start_offset, digits)
                lim1_lb = merged_support[0][2] if merged_support else "Demand"
                lim1_px = min(lim1_px, round(bid_ref - base_start_offset, digits))
                _place_buy_limit(lim1_px, lim1_lb, 2)

        else:
            # ── RANGING / DUAL MODE ──
            # Balanced boundary traps: Limit orders near boundaries + breakout stops
            if place_buy:
                lim_buy_px = merged_support[0][1] if merged_support else round(bid_ref - base_start_offset, digits)
                lim_buy_lb = merged_support[0][2] if merged_support else "Anchor"
                _place_buy_limit(lim_buy_px, lim_buy_lb, 0)

            if place_sell:
                lim_sell_px = merged_resistance[0][1] if merged_resistance else round(ask_ref + base_start_offset, digits)
                lim_sell_lb = merged_resistance[0][2] if merged_resistance else "Anchor"
                _place_sell_limit(lim_sell_px, lim_sell_lb, 1)

            if effective_levels >= 3 and place_buy:
                stp_buy_px = merged_resistance[0][1] if merged_resistance else round(ask_ref + base_start_offset, digits)
                stp_buy_lb = merged_resistance[0][2] if merged_resistance else "Anchor"
                _place_buy_stop(stp_buy_px, stp_buy_lb, 2)
            if effective_levels >= 4 and place_sell:
                stp_sell_px = merged_support[0][1] if merged_support else round(bid_ref - base_start_offset, digits)
                stp_sell_lb = merged_support[0][2] if merged_support else "Anchor"
                _place_sell_stop(stp_sell_px, stp_sell_lb, 3)


        if hasattr(self.broker, "purge_duplicate_mt5_orders"):
            try:
                self.broker.purge_duplicate_mt5_orders()
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        if placed_count > 0 or len(self.broker.pending_orders) > 0:
            self.deployed = True
            self.deploy_price = current_price  # Store deploy center for stale order cleanup
            self.deploy_grid_gap = gap_val
            self.deploy_trap_offset = buy_offset_val
            self.last_deploy_time = timestamp
            self._last_deploy_ts = timestamp  # Debounce timestamp — prevents rapid UI redeploys
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
        if timestamp >= getattr(self, "_last_deploy_attempt_time", 0.0) + 3.0:
            self.deploy_traps(current_price, timestamp)
    return 0


def cleanup_stale_grid_orders(self, current_price: float) -> int:
    """Lightweight cleanup delegated to broker-level duplicate order cleaner."""
    if hasattr(self.broker, "purge_duplicate_mt5_orders"):
        return self.broker.purge_duplicate_mt5_orders()
    return 0


def record_trade_outcome(self, pnl: float, exit_reason: str, duration: float, exit_price: float = 0.0):
    if not hasattr(self, "trade_history") or self.trade_history is None:
        self.trade_history = []
    if not hasattr(self, "cycle_history") or self.cycle_history is None:
        self.cycle_history = []

    now_ts = time.time()
    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "")))

    entry_px = 0.0
    trade_side = None
    fills_count = 1

    # Derive true entry price from recent MT5 closed trade(s) for this cycle
    if hasattr(self.broker, "closed_trades") and self.broker.closed_trades:
        recent_deals = [t for t in self.broker.closed_trades if abs(float(t.get("exit_time", 0.0)) - now_ts) <= 25.0]
        if not recent_deals:
            recent_deals = [self.broker.closed_trades[-1]]

        if recent_deals:
            total_vol = sum(float(t.get("size", 0.01)) for t in recent_deals) or 0.01
            entry_px = sum(float(t.get("entry_price", t.get("open_price", 0.0))) * float(t.get("size", 0.01)) for t in recent_deals) / total_vol
            if exit_price <= 0.0:
                exit_price = sum(float(t.get("exit_price", t.get("close_price", 0.0))) * float(t.get("size", 0.01)) for t in recent_deals) / total_vol
            fills_count = max(len(recent_deals), sum(int(t.get("fills_count", 1)) for t in recent_deals))

            t_side = str(recent_deals[-1].get("type", recent_deals[-1].get("side", ""))).strip().upper()
            if "BUY" in t_side and "SELL" not in t_side:
                trade_side = "BUY"
            elif "SELL" in t_side and "BUY" not in t_side:
                trade_side = "SELL"

            if exit_reason in ("NATIVE_SL", "NATIVE_TP", "") and recent_deals[-1].get("exit_reason"):
                exit_reason = recent_deals[-1].get("exit_reason")

    if entry_px <= 0.0:
        entry_px = float(getattr(self, "_last_cycle_entry_price", 0.0) or getattr(self, "deploy_price", 0.0) or exit_price)
    if exit_price <= 0.0:
        exit_price = entry_px

    is_cent_account = False
    acc_info = getattr(self.broker, "get_account_info", lambda: None)()
    if acc_info:
        currency = str(getattr(acc_info, "currency", "")).upper()
        if currency in ["USC", "USX", "EUC", "GBPC"]:
            is_cent_account = True
    if not is_cent_account and any(sym_name.endswith(s) for s in ["C", "MICRO"]):
        is_cent_account = True

    cent_mult = 100.0 if is_cent_account else 1.0
    raw_pnl = round(float(pnl), 2)
    real_pnl = round(raw_pnl / cent_mult, 4)
    dur_val = max(1, round(float(duration), 1))
    st_time = float(getattr(self, "_cycle_start_time", 0.0) or getattr(self, "cycle_start_time", 0.0) or 0.0)
    if st_time <= 0.0 or st_time > now_ts:
        st_time = max(0.0, now_ts - dur_val)

    cid = getattr(self, "current_cycle_id", None)
    if cid is None or cid <= 0:
        last_cid = 0
        if self.cycle_history:
            last_cid = max((c.get("cycle_id", 0) for c in self.cycle_history if isinstance(c.get("cycle_id"), (int, float))), default=0)
        cid = int(last_cid) + 1
        self.current_cycle_id = cid

    if not trade_side:
        cand_bias = getattr(self, "pending_order_side_mode", getattr(self, "grid_bias", getattr(self, "unidirectional_mode", "")))
        if "BUY" in str(cand_bias).upper() and "SELL" not in str(cand_bias).upper():
            trade_side = "BUY"
        elif "SELL" in str(cand_bias).upper() and "BUY" not in str(cand_bias).upper():
            trade_side = "SELL"
        elif entry_px > 0 and exit_price > 0 and abs(real_pnl) > 0.0001:
            trade_side = "BUY" if ((exit_price > entry_px and real_pnl > 0) or (exit_price < entry_px and real_pnl < 0)) else "SELL"
        else:
            trade_side = "BUY"

    outcome = {
        "timestamp":    now_ts,
        "exit_time":    now_ts,
        "start_time":   st_time,
        "entry_time":   st_time,
        "symbol":       sym_name,
        "pnl":          real_pnl,
        "total_pnl":    real_pnl,
        "raw_pnl":      raw_pnl,
        "is_cent":      is_cent_account,
        "type":         trade_side,
        "side":         trade_side,
        "exit_reason":  exit_reason,
        "duration":     dur_val,
        "is_win":       real_pnl > 0.0,
        "cycle_id":     cid,
        "deploy_price": entry_px,
        "entry_price":  entry_px,
        "exit_price":   exit_price,
        "fills_count":  fills_count,
        "trades_count": fills_count,
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
    status_str = "ACTIVE" if win_rate >= 70.0 else "OPTIMIZING GRID PARAMETERS"
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
    
    if hasattr(self, "broker") and hasattr(self.broker, "closed_trades"):
        trades_source = getattr(self.broker, "closed_trades", []) or []
    else:
        trades_source = []

    if not trades_source:
        return

    if not hasattr(self, "_processed_deals"):
        self._processed_deals = set()

    for item in trades_source:
        deal_id = str(item.get("position_id", ""))
        if deal_id and deal_id in self._processed_deals:
            continue
        if deal_id:
            self._processed_deals.add(deal_id)
            
        if isinstance(item, dict) and ("pnl" in item or "total_pnl" in item):
            pnl_val = float(item.get("pnl", item.get("total_pnl", 0.0)))
            ts_val = float(item.get("exit_time", item.get("timestamp", time.time())))
            st_val = float(item.get("entry_time", item.get("start_time", ts_val - 15.0)))
            
            deal_sym = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
            item_sym = str(item.get("symbol", deal_sym)).upper()
            merged = False
            for cycle in reversed(self.cycle_history):
                c_sym = str(cycle.get("symbol", deal_sym)).upper()
                time_diff = abs(float(cycle.get("exit_time", 0.0)) - ts_val)
                sym_match = (not c_sym or not item_sym or c_sym == item_sym or 
                             ("GOLD" in c_sym and "PAXG" in item_sym) or 
                             ("PAXG" in c_sym and "GOLD" in item_sym))
                if time_diff <= 15.0 and sym_match:
                    if not cycle.get("mt5_synced", False):
                        cycle["total_pnl"] = 0.0
                        cycle["pnl"] = 0.0
                        cycle["raw_pnl"] = 0.0
                        cycle["fills_count"] = 0
                        cycle["_deals_vsum"] = 0.0
                        cycle["_deals_entry_vsum"] = 0.0
                        cycle["_deals_exit_vsum"] = 0.0
                        cycle["mt5_synced"] = True
                    cycle["total_pnl"] = round(cycle.get("total_pnl", 0.0) + pnl_val, 4)
                    cycle["pnl"] = cycle["total_pnl"]
                    raw_add = float(item.get("raw_pnl", pnl_val * (100.0 if item.get("is_cent") else 1.0)))
                    cycle["raw_pnl"] = round(cycle.get("raw_pnl", 0.0) + raw_add, 2)
                    cycle["is_cent"] = item.get("is_cent", cycle.get("is_cent", False))

                    d_vol = float(item.get("size", 0.01)) or 0.01
                    d_en = float(item.get("entry_price", item.get("open_price", 0.0)))
                    d_ex = float(item.get("exit_price", item.get("close_price", 0.0)))
                    cycle["_deals_vsum"] = cycle.get("_deals_vsum", 0.0) + d_vol
                    if d_en > 0:
                        cycle["_deals_entry_vsum"] = cycle.get("_deals_entry_vsum", 0.0) + (d_en * d_vol)
                        cycle["entry_price"] = round(cycle["_deals_entry_vsum"] / cycle["_deals_vsum"], 3)
                        cycle["deploy_price"] = cycle["entry_price"]
                    if d_ex > 0:
                        cycle["_deals_exit_vsum"] = cycle.get("_deals_exit_vsum", 0.0) + (d_ex * d_vol)
                        cycle["exit_price"] = round(cycle["_deals_exit_vsum"] / cycle["_deals_vsum"], 3)

                    if not cycle.get("type"):
                        cycle["type"] = item.get("type", "BUY")
                        cycle["side"] = cycle["type"]
                    fills_add = max(1, int(item.get("fills_count", item.get("size", 1))))
                    cycle["fills_count"] = cycle.get("fills_count", 0) + fills_add
                    cycle["trades_count"] = cycle["fills_count"]
                    # If this deal hit TP, upgrade the whole basket's reason to TP
                    if item.get("exit_reason") == "TARGET_PROFIT":
                        cycle["exit_reason"] = "TARGET_PROFIT"
                    # Only mark as stop loss if the NET basket is negative and it wasn't a TP
                    elif cycle["total_pnl"] < 0 and cycle.get("exit_reason") != "TARGET_PROFIT":
                        cycle["exit_reason"] = "STOP_LOSS"
                    cycle["is_win"] = cycle["total_pnl"] > 0.0
                    merged = True
                    break
            
            if not merged:
                last_cid = max((c.get("cycle_id", 0) for c in self.cycle_history if isinstance(c.get("cycle_id"), (int, float))), default=0)
                new_cid = int(last_cid) + 1
                raw_t = str(item.get("type", item.get("side", ""))).strip().upper()
                en_p = float(item.get("entry_price", item.get("open_price", item.get("deploy_price", 0.0))))
                ex_p = float(item.get("exit_price", item.get("close_price", 0.0)))
                if "BUY" in raw_t and "SELL" not in raw_t:
                    deal_t = "BUY"
                elif "SELL" in raw_t and "BUY" not in raw_t:
                    deal_t = "SELL"
                elif raw_t in ("0", "BUY_LIMIT", "BUY_STOP"):
                    deal_t = "BUY"
                elif raw_t in ("1", "SELL_LIMIT", "SELL_STOP"):
                    deal_t = "SELL"
                elif en_p > 0 and ex_p > 0 and abs(pnl_val) > 0.0001:
                    deal_t = "BUY" if ((ex_p > en_p and pnl_val > 0) or (ex_p < en_p and pnl_val < 0)) else "SELL"
                else:
                    deal_t = "BUY"
                raw_val = float(item.get("raw_pnl", pnl_val * (100.0 if item.get("is_cent") else 1.0)))
                self.cycle_history.append({
                    "cycle_id": new_cid,
                    "total_pnl": round(pnl_val, 4),
                    "pnl": round(pnl_val, 4),
                    "raw_pnl": round(raw_val, 2),
                    "is_cent": item.get("is_cent", False),
                    "symbol": item_sym,
                    "type": deal_t,
                    "side": deal_t,
                    "deploy_price": en_p,
                    "entry_price": en_p,
                    "exit_price": ex_p,
                    "fills_count": max(1, int(item.get("fills_count", item.get("size", 1)))),
                    "trades_count": max(1, int(item.get("fills_count", item.get("size", 1)))),
                    "exit_reason": item.get("exit_reason", "TARGET_PROFIT" if pnl_val > 0 else "STOP_LOSS"),
                    "duration": max(1, int(ts_val - st_val)),
                    "start_time": st_val,
                    "timestamp": ts_val,
                    "exit_time": ts_val,
                    "is_win": pnl_val > 0.0
                })


def enforce_trend_aware_position_guard(self, current_price: float, timestamp: float) -> int:
    """
    🔄 TREND-AWARE POSITION GUARD — Runs every tick.
    """
    if not getattr(self.broker, "open_positions", None):
        return 0

    now_ts = timestamp or time.time()
    last_tg = getattr(self, "_last_trend_guard_time", 0.0)
    if now_ts - last_tg < 2.0:   # Throttle: check every 2 s
        return 0
    self._last_trend_guard_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
    is_gold  = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])
    digits   = 3 if is_gold else (2 if "BTC" in sym_name else 5)

    # ── Resolve current trend from freshest available source ──────────────────
    auto_uni = str(getattr(self, "unidirectional_mode",
                           getattr(self, "auto_universe_bias", "DUAL"))).upper()
    last_eval = getattr(self, "last_auto_eval", None)
    if isinstance(last_eval, dict):
        eval_uni = str(last_eval.get("unidirectional_mode", "DUAL")).upper()
        if eval_uni and eval_uni != "DUAL":
            auto_uni = eval_uni

    # Secondary: 5m technical trend cache (updated every 60 s)
    trail_cache = getattr(self, "_trail_trend_cache", None)
    trend_5m = str(trail_cache.get("trend", "NEUTRAL")).upper() if trail_cache else "NEUTRAL"

    # Fix: Macro bias (auto_uni) MUST override 5m noise. If we are in SELL_ONLY mode,
    # a 5m BULLISH flicker should NOT cause us to cut positions!
    if "BUY" in auto_uni and "ONLY" in auto_uni:
        trend_is_bull = True
        trend_is_bear = False
    elif "SELL" in auto_uni and "ONLY" in auto_uni:
        trend_is_bull = False
        trend_is_bear = True
    else:
        # In DUAL mode, use the 5m technical trend to detect pullbacks
        trend_is_bull = (trend_5m == "BULLISH")
        trend_is_bear = (trend_5m == "BEARISH")

    if not trend_is_bull and not trend_is_bear:
        return 0

    # ── Per-symbol cut-loss threshold ─────────────────────────────────────────
    # Only cut losses SMALLER than this; larger losses are left to the hard SL.
    
    # Auto-detect Cent (USC) logic to scale thresholds appropriately
    is_cent_account = False
    acc_info = getattr(self.broker, "get_account_info", lambda: None)()
    if acc_info:
        currency = str(getattr(acc_info, "currency", "")).upper()
        if currency in ["USC", "USX", "EUC", "GBPC"]:
            is_cent_account = True
    if not is_cent_account and any(sym_name.endswith(s) for s in ["C", "MICRO"]):
        is_cent_account = True
        
    cent_multiplier = 100.0 if is_cent_account else 1.0

    if is_gold:
        profit_lock_threshold = 4.00     # Gold: lock if price moved >= $4.00 in our favor (solid profit)
    elif "BTC" in sym_name:
        profit_lock_threshold = 40.0     # BTC: lock if price moved >= $40 in our favor
    elif "ETH" in sym_name:
        profit_lock_threshold = 3.0      # ETH: lock if price moved >= $3.0 in our favor
    else:
        profit_lock_threshold = 0.0003   # Forex: lock if price moved >= 3 pips

    closed = 0
    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        try:
            # 🛡️ 30s Minimum Hold Guard: Never cut brand new positions on indicator flicker
            pos_open_time = float(getattr(pos_obj, "open_time", getattr(pos_obj, "time_msc", getattr(pos_obj, "time", 0.0))) or 0.0)
            if pos_open_time > 1e11:
                pos_open_time /= 1000.0
            if pos_open_time > 0 and (now_ts - pos_open_time) < 30.0:
                continue

            pos_type  = str(getattr(pos_obj, "type", "")).upper()
            entry     = float(getattr(pos_obj, "entry_price",
                              getattr(pos_obj, "price_open", current_price)) or current_price)

            if "BUY" in pos_type:
                floating_pnl  = current_price - entry
                trend_against = trend_is_bear   # BUY open but market bearish → flip
                trend_with    = trend_is_bull
            elif "SELL" in pos_type:
                floating_pnl  = entry - current_price
                trend_against = trend_is_bull   # SELL open but market bullish → flip
                trend_with    = trend_is_bear
            else:
                continue

            if trend_with:
                # ✅ Trend is aligned — hold and let profit engine run for max gain
                continue

            if trend_against:
                # ❌ Trend has flipped against this position
                # Only close if in solid profit (>= profit_lock_threshold) to lock gains before a real reversal.
                # Never cut positions at a loss on trend noise; let the strategy SL protect risk.
                if floating_pnl >= profit_lock_threshold:
                    should_close = True
                    tag    = "💰 [PULLBACK — PROFIT SECURED]"
                    detail = f"locking +{floating_pnl:.{digits}f} price points before reversal"
                else:
                    should_close = False

                if should_close:
                    try:
                        self.broker.close_position(pos_id, current_price, timestamp)
                        closed += 1
                        print(f"[{sym_name}] {tag} {pos_type} #{pos_id} "
                              f"@ {current_price:.{digits}f} | {detail}")
                    except Exception as e:
                        import logging; logging.warning(f"Exception: {e}")
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

    return closed


def trail_stop_loss_5m_structure(self, current_price: float, timestamp: float) -> int:
    """
    🛡️ PROFESSIONAL DYNAMIC TRAILING STOP LOSS ENGINE v2.
    
    Rules:
    1. SL is ONLY trailed when trend is confirmed (multi-timeframe agreement).
    2. SL distance is ATR-based — wide enough to survive stop hunts.
    3. SL ratchets to breakeven + buffer once position is in profit.
    4. SL placement uses 5m swing structure (Higher Lows / Lower Highs).
    5. SL NEVER moves backwards (one-way ratchet only).
    6. Minimum SL distance keeps SL outside market-maker hunting zones.
    """
    if not hasattr(self.broker, "open_positions") or not self.broker.open_positions:
        return 0

    if not hasattr(self.broker, "modify_position_sl_tp"):
        return 0

    now_ts = timestamp or time.time()
    last_trail_time = getattr(self, "_last_5m_sl_trail_time", 0.0)
    if now_ts - last_trail_time < 1.5:  # Throttle to every 1.5s (one tick cycle)
        return 0
    self._last_5m_sl_trail_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)
    is_gold = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])

    # ── Step 1: Fetch 5m candle data (cached, refreshed every 60s) ──
    try:
        import numpy as np
        from core.data import get_historical_klines, calculate_technical_indicators
        sym_fetch = "PAXGUSDT" if is_gold else (f"{sym_name}USDT" if ("USD" in sym_name and "USDT" not in sym_name) else sym_name)

        _klines_cache = getattr(self, "_5m_klines_cache", None)
        _klines_ts    = getattr(self, "_5m_klines_ts", 0.0)
        if _klines_cache is None or (now_ts - _klines_ts) > 60.0:
            df_5m = get_historical_klines(sym_fetch, interval="3m", limit=30)
            self._5m_klines_cache = df_5m
            self._5m_klines_ts    = now_ts
        else:
            df_5m = _klines_cache

        if df_5m is None or df_5m.empty or len(df_5m) < 10:
            return 0

        highs = df_5m["high"].values
        lows = df_5m["low"].values
        closes = df_5m["close"].values
    except Exception:
        return 0

    # ── Step 2: Calculate ATR on 5m for dynamic SL distance ──
    try:
        tr_list = []
        for i in range(1, len(df_5m)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)
        atr_5m = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else (float(np.mean(tr_list)) if tr_list else (current_price * 0.002))
    except Exception:
        atr_5m = current_price * 0.002

    # ── Step 3: Get trend confirmation (cached, refreshed every 60s) ──
    _trend_cache = getattr(self, "_trail_trend_cache", None)
    _trend_ts    = getattr(self, "_trail_trend_ts", 0.0)
    if _trend_cache is None or (now_ts - _trend_ts) > 60.0:
        try:
            tech_5m = calculate_technical_indicators(df_5m)
            trend_5m = str(tech_5m.get("trend", "NEUTRAL")).upper()
            adx_5m = float(tech_5m.get("adx", 15.0))
            ci_5m = float(tech_5m.get("choppiness_index", 55.0))
        except Exception:
            trend_5m = "NEUTRAL"
            adx_5m = 15.0
            ci_5m = 55.0
        self._trail_trend_cache = {"trend": trend_5m, "adx": adx_5m, "ci": ci_5m}
        self._trail_trend_ts = now_ts
    else:
        trend_5m = _trend_cache["trend"]
        adx_5m = _trend_cache["adx"]
        ci_5m = _trend_cache["ci"]

    # Use Auto Mode's trend if available, otherwise fallback to 5m trend.
    auto_mode = getattr(self, "unidirectional_mode", "DUAL")
    if auto_mode == "BUY_ONLY":
        trend_confirmed_bull = True
        trend_confirmed_bear = False
    elif auto_mode == "SELL_ONLY":
        trend_confirmed_bull = False
        trend_confirmed_bear = True
    else:
        trend_confirmed_bull = (trend_5m == "BULLISH")
        trend_confirmed_bear = (trend_5m == "BEARISH")

    # ── Step 4: Calculate 5m swing structure levels ──
    # Use last 8 candles (40 min) for swing structure — wide enough to find real structure
    swing_lookback = min(8, len(lows) - 1)
    recent_swing_low  = float(np.min(lows[-swing_lookback:]))     # Higher Low for BUY SL
    recent_swing_high = float(np.max(highs[-swing_lookback:]))    # Lower High for SELL SL

    # ── Step 5: Calculate anti-hunt minimum SL distances ──
    # When 100% confirmed: trail TIGHTER (0.8×ATR) to hug price & capture max profit.
    # When not confirmed:  stay WIDE (1.5×ATR) to avoid cheap stop-hunts.
    _is_100pct_trail = is_auto_100pct_confirmed(self)
    _trail_atr_mult  = 0.8 if _is_100pct_trail else 1.5

    if is_gold:
        min_sl_distance  = max(20.00, min(45.00, atr_5m * (2.0 if _is_100pct_trail else 3.0)))
        breakeven_buffer = 3.00 if _is_100pct_trail else 5.00
        min_profit_to_trail = 10.00
        min_required_trail_gap = max(15.00, atr_5m * 2.0)
    elif "BTC" in sym_name:
        min_sl_distance  = max(350.0 if _is_100pct_trail else 550.0, atr_5m * _trail_atr_mult * 2.0)
        breakeven_buffer = 50.0 if _is_100pct_trail else 100.0
        min_profit_to_trail = 250.0
        min_required_trail_gap = max(300.0, atr_5m * 2.0)
    elif "ETH" in sym_name:
        min_sl_distance  = max(25.0 if _is_100pct_trail else 40.0, atr_5m * _trail_atr_mult * 2.0)
        breakeven_buffer = 4.0 if _is_100pct_trail else 8.0
        min_profit_to_trail = 15.00
        min_required_trail_gap = max(20.00, atr_5m * 2.0)
    else:
        min_sl_distance  = max(0.0010 if _is_100pct_trail else 0.0020, atr_5m * _trail_atr_mult * 2.0)
        breakeven_buffer = 0.0003 if _is_100pct_trail else 0.0005
        min_profit_to_trail = atr_5m * 1.5
        min_required_trail_gap = atr_5m * 1.5

    modified_count = 0

    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        # Minimum 60-second breathing room before trailing SL
        pos_open_time = float(getattr(pos_obj, "entry_time", getattr(pos_obj, "time_setup", 0.0)) or 0.0)
        if pos_open_time > 0 and (now_ts - pos_open_time) < 60.0:
            continue

        pos_type = str(getattr(pos_obj, "type", "")).upper()
        entry_px = float(getattr(pos_obj, "entry_price", getattr(pos_obj, "price_open", current_price)) or current_price)
        cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)

        if "BUY" in pos_type:
            # ── BUY POSITION SL LOGIC ──
            floating_profit = current_price - entry_px
            # Only trail positions that are safely in profit — never choke a nascent or recovering trade
            if floating_profit < min_profit_to_trail:
                continue

            # Calculate structure-based SL: swing low minus anti-hunt buffer
            anti_hunt_trail = max(atr_5m * 0.8, 3.50 if is_gold else (50.0 if "BTC" in sym_name else 4.0))
            structure_sl = round(recent_swing_low - anti_hunt_trail, digits)

            # Enforce minimum distance from current price to avoid stop hunts
            max_allowed_sl = round(current_price - min_sl_distance, digits)
            target_sl = min(structure_sl, max_allowed_sl)

            # SL must be better (higher) than current SL — never move backwards
            if target_sl > cur_sl and target_sl < current_price:
                # Final safety: SL must not be closer than min_required_trail_gap to current price
                if (current_price - target_sl) >= min_required_trail_gap:
                    try:
                        if self.broker.modify_position_sl_tp(pos_id, sl=target_sl):
                            setattr(pos_obj, "sl", target_sl)
                            modified_count += 1
                            print(f"[{sym_name}] 🛡️ [SMART TRAIL] BUY #{pos_id} SL → ${target_sl:,.3f} (5m swing low - ATR buffer, trend CONFIRMED)")
                    except Exception as e:
                        import logging; logging.warning(f"Exception: {e}")

        elif "SELL" in pos_type:
            # ── SELL POSITION SL LOGIC ──
            floating_profit = entry_px - current_price
            # Only trail positions that are safely in profit — never choke a nascent or recovering trade
            if floating_profit < min_profit_to_trail:
                continue

            # Calculate structure-based SL: swing high plus anti-hunt buffer
            anti_hunt_trail = max(atr_5m * 0.8, 3.50 if is_gold else (50.0 if "BTC" in sym_name else 4.0))
            structure_sl = round(recent_swing_high + anti_hunt_trail, digits)

            # Enforce minimum distance
            min_allowed_sl = round(current_price + min_sl_distance, digits)
            target_sl = max(structure_sl, min_allowed_sl)

            # SL must be better (lower) than current SL — never move backwards
            if (cur_sl == 0.0 or target_sl < cur_sl) and target_sl > current_price:
                # Final safety: SL must not be closer than min_required_trail_gap
                if (target_sl - current_price) >= min_required_trail_gap:
                    try:
                        if self.broker.modify_position_sl_tp(pos_id, sl=target_sl):
                            setattr(pos_obj, "sl", target_sl)
                            modified_count += 1
                            print(f"[{sym_name}] 🛡️ [SMART TRAIL] SELL #{pos_id} SL → ${target_sl:,.3f} (5m swing high + ATR buffer, trend CONFIRMED)")
                    except Exception as e:
                        import logging; logging.warning(f"Exception: {e}")

    return modified_count


def align_basket_take_profits(self, current_price: float, timestamp: float) -> int:
    """
    🎯 DYNAMIC BASKET TAKE-PROFIT ENGINE v2.
    
    1. Calculates ATR-based optimal TP distance (1.5× to 2.5× ATR from price).
    2. Snaps TP to 5m swing structure (resistance for BUY, support for SELL).
    3. Unifies all same-side positions to ONE common TP so basket closes together.
    4. Dynamically tightens TP toward the best fillable level as price moves.
    5. TP NEVER moves further away — only tightens toward current price.
    """
    if not hasattr(self.broker, "open_positions") or not self.broker.open_positions:
        return 0

    if not hasattr(self.broker, "modify_position_sl_tp"):
        return 0

    now_ts = timestamp or time.time()
    last_align_time = getattr(self, "_last_tp_align_time", 0.0)
    if now_ts - last_align_time < 1.5:
        return 0
    self._last_tp_align_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()
    digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)
    is_gold = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])

    # ── Fetch 5m data for structure and ATR (use cached from trailing SL if fresh) ──
    atr_5m = 0.0
    swing_high_5m = current_price
    swing_low_5m = current_price
    try:
        import numpy as np
        from core.data import get_historical_klines
        sym_fetch = "PAXGUSDT" if is_gold else (f"{sym_name}USDT" if ("USD" in sym_name and "USDT" not in sym_name) else sym_name)

        _klines_cache = getattr(self, "_5m_klines_cache", None)
        _klines_ts = getattr(self, "_5m_klines_ts", 0.0)
        if _klines_cache is None or (now_ts - _klines_ts) > 60.0:
            df_5m = get_historical_klines(sym_fetch, interval="3m", limit=30)
            self._5m_klines_cache = df_5m
            self._5m_klines_ts = now_ts
        else:
            df_5m = _klines_cache

        if df_5m is not None and not df_5m.empty and len(df_5m) >= 10:
            highs = df_5m["high"].values
            lows = df_5m["low"].values
            closes = df_5m["close"].values

            # ATR on 5m
            tr_list = []
            for i in range(1, len(df_5m)):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                tr_list.append(tr)
            atr_5m = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else (float(np.mean(tr_list)) if tr_list else 0.0)

            # 5m swing structure levels (last 8 candles = 40 min)
            lookback = min(8, len(highs) - 1)
            swing_high_5m = float(np.max(highs[-lookback:]))
            swing_low_5m = float(np.min(lows[-lookback:]))
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")

    # Fallback ATR if calculation failed
    if atr_5m <= 0:
        atr_5m = current_price * 0.002

    # ── Calculate optimal TP distance per symbol ──
    # 🟢 100% CONFIRMED TREND: extend TP to 3.5×ATR to ride the full move for max profit.
    # Unconfirmed: standard 2.5×ATR so TP maintains positive R:R vs SL (~10.95 pts on Gold).
    _is_100pct_tp = is_auto_100pct_confirmed(self)
    _tp_atr_mult  = 3.5 if _is_100pct_tp else 2.5

    if is_gold:
        min_tp_dist = max(16.0, atr_5m * 2.5, current_price * 0.0035)
        optimal_tp_dist = max(min_tp_dist, atr_5m * _tp_atr_mult)
    else:
        min_tp_dist = max(current_price * 0.002, atr_5m * 1.5)
        optimal_tp_dist = max(min_tp_dist, atr_5m * _tp_atr_mult)

    buy_positions = []
    sell_positions = []

    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        pos_type = str(getattr(pos_obj, "type", "")).upper()
        if "BUY" in pos_type:
            buy_positions.append((pos_id, pos_obj))
        elif "SELL" in pos_type:
            sell_positions.append((pos_id, pos_obj))

    modified_count = 0

    # ── Align BUY basket TP ──
    if len(buy_positions) >= 1:
        # Best TP = nearest resistance or ATR-based target, whichever is closer (more fillable)
        atr_tp = round(current_price + optimal_tp_dist, digits)

        # If 5m swing high (resistance) is above current price and within reach, snap to it
        if swing_high_5m > current_price + min_tp_dist:
            structure_tp = round(swing_high_5m - (atr_5m * 0.2), digits)  # Place TP just before resistance
            if _is_100pct_tp:
                best_tp = max(atr_tp, structure_tp)  # EXPAND: Use furthest target to ride the breakout!
            else:
                best_tp = max(structure_tp, current_price + min_tp_dist)
        else:
            best_tp = atr_tp

        # Ensure minimum TP distance (AND never place TP below average entry to prevent negative targets)
        avg_entry = sum(float(getattr(p, "entry_price", getattr(p, "price_open", current_price))) * float(getattr(p, "size", 0.01)) for _, p in buy_positions) / max(0.0001, sum(float(getattr(p, "size", 0.01)) for _, p in buy_positions))
        min_breakeven_tp = avg_entry + (current_price * 0.0002) # Tiny buffer above breakeven
        
        best_tp = max(best_tp, current_price + min_tp_dist)
        best_tp = round(max(best_tp, min_breakeven_tp), digits)

        # Collect existing TPs to check if we should expand or tighten.
        for pos_id, pos_obj in buy_positions:
            cur_tp = round(float(getattr(pos_obj, "tp", 0.0) or 0.0), digits)

            if cur_tp > current_price:
                if _is_100pct_tp or cur_tp == 0.0 or best_tp > cur_tp:
                    # DYNAMIC EXPANSION: Push TP further out dynamically to ride strong momentum!
                    target_tp = max(cur_tp, best_tp)
                else:
                    # Fix #10: STANDARD TIGHTEN — only tighten if new TP is meaningfully
                    # closer (> 0.5×ATR) AND still satisfies min_tp_dist. Prevents noisy ATR fluctuations
                    # from overwriting structural TPs down to unprofitable levels.
                    if (best_tp - current_price) >= min_tp_dist and (cur_tp - best_tp) > (atr_5m * 0.5):
                        target_tp = best_tp
                    else:
                        target_tp = cur_tp  # Keep existing TP — structural level still valid
            else:
                target_tp = best_tp

            if cur_tp != target_tp and target_tp > current_price:
                last_set_tp = getattr(pos_obj, "_last_set_tp", None)
                if last_set_tp == target_tp:
                    setattr(pos_obj, "tp", target_tp)
                    continue
                cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
                try:
                    if self.broker.modify_position_sl_tp(pos_id, sl=cur_sl if cur_sl > 0 else None, tp=target_tp):
                        setattr(pos_obj, "tp", target_tp)
                        setattr(pos_obj, "_last_set_tp", target_tp)
                        modified_count += 1
                        print(f"[{sym_name}] 🎯 [SMART TP] BUY #{pos_id} TP → ${target_tp:,.3f} (ATR: ${atr_5m:.2f}, dist: ${target_tp - current_price:.2f})")
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")

    # ── Align SELL basket TP ──
    if len(sell_positions) >= 1:
        # Best TP = nearest support or ATR-based target, whichever is closer
        atr_tp = round(current_price - optimal_tp_dist, digits)

        # If 5m swing low (support) is below current price and within reach, snap to it
        if swing_low_5m < current_price - min_tp_dist:
            structure_tp = round(swing_low_5m + (atr_5m * 0.2), digits)  # Place TP just before support
            if _is_100pct_tp:
                best_tp = min(atr_tp, structure_tp)  # EXPAND: Use furthest target (lowest price)
            else:
                best_tp = min(structure_tp, current_price - min_tp_dist)
        else:
            best_tp = atr_tp

        # Ensure minimum TP distance (AND never place TP above average entry to prevent negative targets)
        avg_entry = sum(float(getattr(p, "entry_price", getattr(p, "price_open", current_price))) * float(getattr(p, "size", 0.01)) for _, p in sell_positions) / max(0.0001, sum(float(getattr(p, "size", 0.01)) for _, p in sell_positions))
        min_breakeven_tp = avg_entry - (current_price * 0.0002) # Tiny buffer below breakeven
        
        best_tp = min(best_tp, current_price - min_tp_dist)
        best_tp = round(min(best_tp, min_breakeven_tp), digits)

        for pos_id, pos_obj in sell_positions:
            cur_tp = round(float(getattr(pos_obj, "tp", 0.0) or 0.0), digits)

            if 0.0 < cur_tp < current_price:
                if _is_100pct_tp:
                    # DYNAMIC EXPANSION: Push TP further down!
                    target_tp = min(cur_tp, best_tp)
                else:
                    # Fix #10: STANDARD TIGHTEN — only tighten if new TP is meaningfully
                    # closer (> 0.5×ATR) AND still satisfies min_tp_dist.
                    if (current_price - best_tp) >= min_tp_dist and (best_tp - cur_tp) > (atr_5m * 0.5):
                        target_tp = best_tp
                    else:
                        target_tp = cur_tp  # Keep existing TP — structural level still valid
            else:
                target_tp = best_tp

            if cur_tp != target_tp and 0.0 < target_tp < current_price:
                last_set_tp = getattr(pos_obj, "_last_set_tp", None)
                if last_set_tp == target_tp:
                    setattr(pos_obj, "tp", target_tp)
                    continue
                cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
                try:
                    if self.broker.modify_position_sl_tp(pos_id, sl=cur_sl if cur_sl > 0 else None, tp=target_tp):
                        setattr(pos_obj, "tp", target_tp)
                        setattr(pos_obj, "_last_set_tp", target_tp)
                        modified_count += 1
                        print(f"[{sym_name}] 🎯 [SMART TP] SELL #{pos_id} TP → ${target_tp:,.3f} (ATR: ${atr_5m:.2f}, dist: ${current_price - target_tp:.2f})")
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")

    return modified_count


def sync_trap_mode_realtime(self, current_price: float, timestamp: float) -> bool:
    """Trap modes are strictly enforced directly during order placement in deploy_traps."""
    return False


def enforce_global_hedged_recovery(self, current_price: float, timestamp: float) -> bool:
    """Bot executes unidirectional momentum grids. Basket exits are strictly governed by check_target_profit."""
    return False

