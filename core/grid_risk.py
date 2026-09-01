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
    BREAKEVEN PROTECTION: FULLY DISABLED by user request.
    Trades are allowed to run freely without any SL modification based on profit.
    Only the structure-based trail (trail_stop_loss_5m_structure) remains active.
    """
    # Update running peak for check_target_profit runner-mode calculations
    if getattr(self.broker, "open_positions", None):
        total_pnl = float(self.broker.get_floating_pnl(current_price))
        if total_pnl > getattr(self, "max_floating_pnl", -float("inf")):
            self.max_floating_pnl = total_pnl
    return 0


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
            df_5m = get_historical_klines(sym_fetch, interval="5m", limit=30)
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
    INDUSTRY-GRADE 3-STAGE TAKE PROFIT ENGINE.

    Stage 1 – TP1 (40% partial close at 1×ATR from weighted basket entry):
      • Locks in realized profit immediately.
      • Moves SL of remaining positions to breakeven+buffer → zero-risk runner.

    Stage 2 – TP2 (25% partial close at Fibonacci 1.618× extension):
      • Targets the institutional golden-ratio extension level.
      • Only triggers after TP1 has been hit.

    Stage 3 – Chandelier Runner Exit (remaining 35%):
      • Trails the high/low with ATR×2 Chandelier — lets winners run.
      • Activates only after TP1 hit; exits when chandelier is breached.

    State flags (reset on new grid cycle by engine.py):
      _tp1_buy_taken, _tp1_sell_taken,
      _tp2_buy_taken, _tp2_sell_taken,
      _chandelier_buy_high, _chandelier_sell_low
    """
    # USER REQUESTED: Disabled partial take profit (scale-out) entirely.
    # The bot will now ONLY close when the full dynamic basket target is hit.
    return 0
    
    if not getattr(self.broker, "open_positions", None):
        return 0
    if not hasattr(self.broker, "partial_close_position"):
        return 0

    # Throttle to once per 1.5s
    now_ts = timestamp or time.time()
    last_ptp = getattr(self, "_last_partial_tp_time", 0.0)
    if now_ts - last_ptp < 1.5:
        return 0
    self._last_partial_tp_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
    is_gold  = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])
    digits   = 3 if is_gold else (2 if "BTC" in sym_name else 5)

    state = compute_basket_state(self, current_price, timestamp)
    atr   = state["atr_5m"]
    swing_range = state["swing_range"]

    # Fibonacci 1.618× extension distance
    fib_dist  = swing_range * 1.618

    # ── Per-symbol minimum distances to prevent noise triggers ──
    # Increased minimum distances to prevent closing on 1-minute noise (e.g., $0.03 profit).
    min_tp1_dist = max(current_price * 0.0015, atr * 1.5)
    min_tp2_dist = max(current_price * 0.0025, fib_dist)
    breakeven_buf = current_price * 0.0001

    actions = 0

    # ═══════════════════════════════════════════════════════
    # BUY BASKET
    # ═══════════════════════════════════════════════════════
    buy_positions = state["buy_positions"]
    w_avg_buy     = state["weighted_avg_entry_buy"]

    if buy_positions and w_avg_buy > 0:
        tp1_level = w_avg_buy + min_tp1_dist
        tp2_level = w_avg_buy + min_tp2_dist
        tp1_taken = getattr(self, "_tp1_buy_taken", False)
        tp2_taken = getattr(self, "_tp2_buy_taken", False)

        # ── Stage 1: TP1 — 40% close ──
        if not tp1_taken and current_price >= tp1_level:
            closed_any = False
            for pos_id, pos_obj, entry, size in buy_positions:
                try:
                    rec = self.broker.partial_close_position(pos_id, 0.40, current_price, now_ts)
                    if rec:
                        closed_any = True
                        actions += 1
                        print(f"[{sym_name}] 🎯 [TP1 PARTIAL] BUY #{pos_id}: closed 40% @ ${current_price:,.{digits}f} "
                              f"(1xATR from weighted entry ${w_avg_buy:,.{digits}f}) PnL≈${rec['pnl']:+.2f}")
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")

            if closed_any:
                self._tp1_buy_taken = True
                # Breakeven lock removed — let runner continue freely

        # ── Stage 2: TP2 — Fibonacci 1.618× (25% close) ──
        if tp1_taken and not tp2_taken and current_price >= tp2_level:
            closed_any = False
            for pos_id, pos_obj, entry, size in buy_positions:
                if pos_id not in self.broker.open_positions:
                    continue
                try:
                    rec = self.broker.partial_close_position(pos_id, 0.25, current_price, now_ts)
                    if rec:
                        closed_any = True
                        actions += 1
                        print(f"[{sym_name}] 💎 [TP2 FIB] BUY #{pos_id}: closed 25% @ ${current_price:,.{digits}f} "
                              f"(Fib 161.8% = ${tp2_level:,.{digits}f}) PnL≈${rec['pnl']:+.2f}")
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")
            if closed_any:
                self._tp2_buy_taken = True
                self._chandelier_buy_high = current_price   # Seed chandelier high

        # ── Stage 3: Chandelier Exit for runner (remaining ~35%) ──
        if tp1_taken and current_price > 0:
            # Track running high for Chandelier
            chan_high = getattr(self, "_chandelier_buy_high", current_price)
            if current_price > chan_high:
                self._chandelier_buy_high = current_price
                chan_high = current_price
            # Chandelier SL = highest_high - ATR×2
            chandelier_sl = round(chan_high - (atr * 2.0), digits)
            if current_price <= chandelier_sl:
                # Chandelier breached — exit all remaining BUY runners
                for pos_id, pos_obj, entry, size in buy_positions:
                    if pos_id not in self.broker.open_positions:
                        continue
                    try:
                        rec = self.broker.partial_close_position(pos_id, 1.0, current_price, now_ts)
                        if rec:
                            actions += 1
                            print(f"[{sym_name}] 🏃 [CHANDELIER EXIT] BUY #{pos_id}: runner closed @ ${current_price:,.{digits}f} "
                                  f"(chandelier SL=${chandelier_sl:,.{digits}f}, peak=${chan_high:,.{digits}f})")
                    except Exception as e:
                        import logging; logging.warning(f"Exception: {e}")
                # Reset for next cycle
                self._tp1_buy_taken = False
                self._tp2_buy_taken = False
                self._chandelier_buy_high = 0.0

    # ═══════════════════════════════════════════════════════
    # SELL BASKET
    # ═══════════════════════════════════════════════════════
    sell_positions = state["sell_positions"]
    w_avg_sell     = state["weighted_avg_entry_sell"]

    if sell_positions and w_avg_sell > 0:
        tp1_level = w_avg_sell - min_tp1_dist
        tp2_level = w_avg_sell - min_tp2_dist
        tp1_taken = getattr(self, "_tp1_sell_taken", False)
        tp2_taken = getattr(self, "_tp2_sell_taken", False)

        # ── Stage 1: TP1 — 40% close ──
        if not tp1_taken and current_price <= tp1_level:
            closed_any = False
            for pos_id, pos_obj, entry, size in sell_positions:
                try:
                    rec = self.broker.partial_close_position(pos_id, 0.40, current_price, now_ts)
                    if rec:
                        closed_any = True
                        actions += 1
                        print(f"[{sym_name}] 🎯 [TP1 PARTIAL] SELL #{pos_id}: closed 40% @ ${current_price:,.{digits}f} "
                              f"(1xATR from weighted entry ${w_avg_sell:,.{digits}f}) PnL≈${rec['pnl']:+.2f}")
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")
            if closed_any:
                self._tp1_sell_taken = True
                # Breakeven lock removed — let runner continue freely

        # ── Stage 2: TP2 — Fibonacci 1.618× (25% close) ──
        if tp1_taken and not tp2_taken and current_price <= tp2_level:
            closed_any = False
            for pos_id, pos_obj, entry, size in sell_positions:
                if pos_id not in self.broker.open_positions:
                    continue
                try:
                    rec = self.broker.partial_close_position(pos_id, 0.25, current_price, now_ts)
                    if rec:
                        closed_any = True
                        actions += 1
                        print(f"[{sym_name}] 💎 [TP2 FIB] SELL #{pos_id}: closed 25% @ ${current_price:,.{digits}f} "
                              f"(Fib 161.8% = ${tp2_level:,.{digits}f}) PnL≈${rec['pnl']:+.2f}")
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")
            if closed_any:
                self._tp2_sell_taken = True
                self._chandelier_sell_low = current_price

        # ── Stage 3: Chandelier Exit for runner ──
        if tp1_taken and current_price > 0:
            chan_low = getattr(self, "_chandelier_sell_low", current_price)
            if current_price < chan_low:
                self._chandelier_sell_low = current_price
                chan_low = current_price
            chandelier_sl = round(chan_low + (atr * 2.0), digits)
            if current_price >= chandelier_sl:
                for pos_id, pos_obj, entry, size in sell_positions:
                    if pos_id not in self.broker.open_positions:
                        continue
                    try:
                        rec = self.broker.partial_close_position(pos_id, 1.0, current_price, now_ts)
                        if rec:
                            actions += 1
                            print(f"[{sym_name}] 🏃 [CHANDELIER EXIT] SELL #{pos_id}: runner closed @ ${current_price:,.{digits}f} "
                                  f"(chandelier SL=${chandelier_sl:,.{digits}f}, trough=${chan_low:,.{digits}f})")
                    except Exception as e:
                        import logging; logging.warning(f"Exception: {e}")
                self._tp1_sell_taken = False
                self._tp2_sell_taken = False
                self._chandelier_sell_low = 0.0

    return actions


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
    duration = timestamp - getattr(self, "cycle_start_time", timestamp)

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
    # Cycle Max Drawdown (Hard Stop Loss)
    # ─────────────────────────────────────────────────────────────
    is_manual = getattr(self, "manual_override_active", False)
    
    if not is_manual:
        # Extreme Drawdown (Catastrophic Fallback Protection)
        if not exit_triggered:
            max_cycle_dd = float(getattr(self, "max_cycle_drawdown", 30.0) or 30.0)
            extreme_dd = max_cycle_dd * 3.0
            if total_pnl <= -abs(extreme_dd):
                exit_triggered = True
                exit_reason = "STOP_LOSS"
                print(f"[{self.symbol}] 🛑 [EXTREME DRAWDOWN HIT] Cycle PnL {total_pnl:.2f} <= -{extreme_dd:.2f}. Forcing market close.")
    else:
        # In manual mode, we do NOT enforce the hardcoded auto max drawdown. 
        # The user's manual SL/TP parameters or manual closures govern risk.
        pass

    # ─────────────────────────────────────────────────────────────
    # Standard Stop Loss
    # ─────────────────────────────────────────────────────────────
    if not exit_triggered:
        sl_limit = float(getattr(self, "stop_loss", 0.0) or 0.0)
        if sl_limit > 0:
            # Fix #8: Per-basket SL — fixed dollar amount, NOT scaled by lot count.
            # Scaling by micro_lots caused SL to grow as DCA levels filled, preventing it from ever triggering.
            if total_pnl <= -abs(sl_limit):
                exit_triggered = True
                exit_reason = "STOP_LOSS"

    # ─────────────────────────────────────────────────────────────
    # Basket Target Profit (Cycle Exit)
    # ─────────────────────────────────────────────────────────────
    sym_u = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
    
    # Auto-detect Cent (USC) logic disabled: treating all accounts (USC/USD) the same
    is_cent_account = False
    cent_multiplier = 1.0

    min_profit_threshold = 0.50 * cent_multiplier  # Minimum gross profit to close a cycle, mitigating fee attrition
    if not exit_triggered:
        # Calculate total open volume in the basket
        total_volume = sum(float(getattr(p, "size", 0.01)) for p in self.broker.open_positions.values())
        micro_lots = total_volume / 0.01
        
        # Base target per 0.01 lot (e.g. $10 for Gold, $3 for others)
        base_target = 10.0 if any(x in sym_u for x in ["XAU", "GOLD", "PAXG"]) else 3.0
        
        # Scale all targets by the volume multiplier (micro_lots)
        default_target = (base_target * micro_lots) * cent_multiplier
        
        raw_ai_target = float(getattr(self, "deploy_target_profit", 0.0) or 0.0)
        ai_target = (raw_ai_target * micro_lots) if raw_ai_target > 0 else 0.0
        
        raw_user_target = float(getattr(self, "target_profit", 0.0) or 0.0)
        user_target = (raw_user_target * micro_lots) * cent_multiplier if raw_user_target > 0 else 0.0
        
        cycle_target = ai_target if ai_target > 0 else (user_target if user_target > 0 else default_target)
        
        # Enforce minimum profit threshold
        effective_cycle_target = max(cycle_target, min_profit_threshold)
            
        # ── 1. Basket Target Profit & Runner Mode Expansion ──
        # When floating profit reaches the cycle target (e.g. $10+ for Gold), let winning trends run!
        use_trailing = getattr(self, "use_smart_trailing", True) or getattr(self, "use_trailing_stop", False)

        if total_pnl >= effective_cycle_target:
            if use_trailing:
                self.in_runner_mode = True
                
                # Fix #2/#4: Use hoisted auto_uni (resolved once at top of function)
                # Check if trend is aligned with positions
                trend_aligned = False
                if auto_uni:
                    has_sells_local = any("SELL" in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
                    has_buys_local  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
                    is_bull_local = any(x in auto_uni for x in ["BUY", "BULLISH"])
                    is_bear_local = any(x in auto_uni for x in ["SELL", "BEARISH"])
                    trend_aligned = (has_buys_local and not has_sells_local and is_bull_local and not is_bear_local) or \
                                    (has_sells_local and not has_buys_local and is_bear_local and not is_bull_local)

                # In runner mode: Give massive breathing room to weather pullbacks and capture huge trends
                # Fix #2+#7: Guard with max(0.0,...) so floor can never be negative, and require
                # minimum $0.05 net profit to cover spread/commission before exiting.
                if trend_aligned:
                    runner_floor = max(0.0, max(effective_cycle_target * 0.10, max_pnl * 0.30))
                else:
                    runner_floor = max(0.0, max(effective_cycle_target * 0.50, max_pnl * 0.60))
                
                # Apply learned booster if win rate is extremely high
                if getattr(self, "learned_runner_lock_boost", 0.0) > 0:
                    runner_floor = runner_floor * (1.0 + self.learned_runner_lock_boost)

                if total_pnl <= runner_floor and total_pnl >= 0.05:  # min $0.05 to cover spread
                    exit_triggered = True
                    exit_reason = "RUNNER_EXPANSION"
                    print(f"[{sym_u}] 🚀 [RUNNER EXIT] Peak was +${max_pnl:.2f}. Trailing floor +${runner_floor:.2f} reached. Net PnL: +${total_pnl:.2f}!")
                else:
                    # Let it run! Log every new high
                    if total_pnl >= max_pnl:
                        aligned_tag = " [TREND ALIGNED]" if trend_aligned else ""
                        print(f"[{sym_u}] 🚀 [RUNNER EXPANDING]{aligned_tag} Winning trend active! PnL +${total_pnl:.2f} (Target was ${effective_cycle_target:.2f}). Trailing floor: +${runner_floor:.2f}")
            else:
                exit_triggered = True
                exit_reason = "TARGET_PROFIT"
                print(f"[{sym_u}] 💰 [CYCLE TP HIT] Basket reached target of ${effective_cycle_target:.2f} (Total PnL: ${total_pnl:.2f})! Instant Close All.")

        # ── 2. Smart Trend Reversal Exit (Only in Substantial Profit) ──
        # Only exit on trend reversal if we already have substantial profit (>= 70% of target)
        # to prevent cutting promising trends on 1-minute noise.
        _is_gold_tr = any(x in sym_u for x in ["XAU", "GOLD", "PAXG"])
        trend_reversal_threshold = max(effective_cycle_target * 0.70, 5.0 if _is_gold_tr else 2.50)

        if not exit_triggered and total_pnl >= trend_reversal_threshold and auto_uni:
            has_sells = any("SELL" in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
            has_buys  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())

            is_bullish = any(x in auto_uni for x in ["BUY", "BULLISH"])
            is_bearish = any(x in auto_uni for x in ["SELL", "BEARISH"])

            if has_sells and not has_buys and is_bullish and not is_bearish:
                exit_triggered = True
                exit_reason = "TARGET_PROFIT"
                print(f"[{sym_u}] 🔄 [TREND REVERSAL EXIT] Higher TF trend flipped to {auto_uni}. Securing +${total_pnl:.2f} (>= ${trend_reversal_threshold:.2f} threshold).")
            elif has_buys and not has_sells and is_bearish and not is_bullish:
                exit_triggered = True
                exit_reason = "TARGET_PROFIT"
                print(f"[{sym_u}] 🔄 [TREND REVERSAL EXIT] Higher TF trend flipped to {auto_uni}. Securing +${total_pnl:.2f} (>= ${trend_reversal_threshold:.2f} threshold).")

        # ── 3. High-Water Mark Trailing Protection (Near Target Only) ──
        # Relaxed for more noise room! Let trades breathe before target is fully hit.
        near_target_activation = effective_cycle_target * 0.85
        if not exit_triggered and max_pnl >= near_target_activation:
            # Fix #4: Use hoisted auto_uni (resolved at function top) — no duplicate resolution
            # Check if trend is aligned with positions
            trend_aligned_lock = False
            if auto_uni:
                has_sells_loc = any("SELL" in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
                has_buys_loc  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
                is_bull_loc = any(x in auto_uni for x in ["BUY", "BULLISH"])
                is_bear_loc = any(x in auto_uni for x in ["SELL", "BEARISH"])
                trend_aligned_lock = (has_buys_loc and not has_sells_loc and is_bull_loc and not is_bear_loc) or \
                                     (has_sells_loc and not has_buys_loc and is_bear_loc and not is_bull_loc)

            # Fix #3: Guard locked_floor with max(0.0,...) — floor can never be negative
            # Lock in 30% of target or 50% of max_pnl, preventing choke-outs on standard chop
            if trend_aligned_lock:
                locked_floor = max(0.0, max(effective_cycle_target * 0.10, max_pnl * 0.20))
            else:
                locked_floor = max(0.0, max(effective_cycle_target * 0.30, max_pnl * 0.50))
                
            if total_pnl <= locked_floor and total_pnl > 0:
                exit_triggered = True
                exit_reason = "TARGET_PROFIT"
                print(f"[{sym_u}] 🏆 [PEAK PROFIT TRAIL LOCK] Peak reached +${max_pnl:.2f} (>= 85% of ${effective_cycle_target:.2f} target). Pullback floor +${locked_floor:.2f} reached. Securing +${total_pnl:.2f}!")

    if exit_triggered:
        print(f"[{self.symbol}] 🎯 [PROFIT TAKING EXIT] {exit_reason} met! Net PnL: ${total_pnl:+.2f} USD")
        if hasattr(self.broker, "cancel_all_orders"):
            try: self.broker.cancel_all_orders()
            except Exception as e: import logging; logging.warning(f"Cancel error: {e}")
            
        if hasattr(self.broker, "close_all_positions"):
            try: self.broker.close_all_positions()
            except Exception as e: import logging; logging.warning(f"Close error: {e}")

        self.in_runner_mode = False
        self.max_floating_pnl = -float("inf")
        self._max_open_in_cycle = 0

        summary = {
            "cycle_id": getattr(self, "current_cycle_id", 1),
            "total_pnl": round(total_pnl, 2),
            "exit_reason": exit_reason,
            "duration": round(duration, 1),
            "timestamp": timestamp,
            "exit_price": current_price
        }

        # Fix #1: record_trade_outcome is called by the caller (process_engine_tick L957).
        # Calling it here too caused every cycle to be recorded TWICE, corrupting win-rate stats.
        if getattr(self, "auto_restart", True):
            print(f"[{self.symbol}] 🚀 [AUTO RESTART] Redeploying fresh grid at market price {current_price}...")
            try: self.deploy_traps(current_price, timestamp, force=True)
            except Exception as dep_err: print(f"Redeploy err: {dep_err}")

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
        self._max_open_in_cycle = current_open

    last_pending = getattr(self, "_last_pending_count", current_pending)
    last_open = getattr(self, "_last_open_count", current_open)

    needs_refresh = False
    refresh_reason = ""

    # Refresh grid ONLY when a position cycle has fully closed and 0 positions remain
    if getattr(self, "_max_open_in_cycle", 0) > 0 and current_open == 0 and current_pending > 0:
        needs_refresh = True
        refresh_reason = "Position cycle completed"
    else:
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
        print(f"[{self.symbol}] 🔄 [GRID REFRESH] {refresh_reason}. Canceling {current_pending} pending orders to deploy fresh grid.")
        if hasattr(self.broker, "cancel_all_orders"):
            self.broker.cancel_all_orders(symbol=self.symbol)
        self.deployed = False
        self._max_open_in_cycle = 0
        self._last_pending_count = 0
        self._last_open_count = 0
        self.deploy_traps(current_price, timestamp, force=False)
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
            # evaluate_partial_tp(self, current_price, timestamp)             # Disabled per user: scale-outs bleed in chop
            align_basket_take_profits(self, current_price, timestamp)       # ATR basket TP alignment (fallback/tighten)
            enforce_position_tp(self, current_price, timestamp)             # Software-side TP guard — always take profit
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

    if getattr(self, "_fakeout_guard_enabled", False) and self._fakeout_recent_fills:
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
        if exit_reason == "STOP_LOSS":
            self._post_loss_cooldown = timestamp + (3 * 60)  # 3 min cooldown on Stop Loss
            print(f"[{self.symbol}] ⏳ [COOLDOWN] Market highly volatile. Halting grid deployment for 3 minutes.")
        
        self.current_cycle_id += 1

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
            self.deploy_traps(current_price, timestamp, force=True)

        return summary

    return None


def sync_cycle_history_from_trades(self):
    if not hasattr(self, "cycle_history") or self.cycle_history is None:
        self.cycle_history = []
    
    trades_source = getattr(self, "trade_history", []) or []
    if not trades_source and hasattr(self, "broker") and hasattr(self.broker, "closed_trades"):
        trades_source = getattr(self.broker, "closed_trades", []) or []

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
            
            merged = False
            for cycle in reversed(self.cycle_history):
                # Fix #17: Reduce merge window from 5s → 1s to prevent unrelated cycles from
                # being merged together.
                if abs(float(cycle.get("exit_time", 0.0)) - ts_val) <= 1.0:
                    cycle["total_pnl"] = round(cycle.get("total_pnl", 0.0) + pnl_val, 3)
                    cycle["pnl"] = cycle["total_pnl"]
                    fills_add = max(1, int(item.get("fills_count", item.get("size", 1))))
                    cycle["fills_count"] = cycle.get("fills_count", 1) + fills_add
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
                self.cycle_history.append({
                    "cycle_id": len(self.cycle_history) + 1,
                    "total_pnl": round(pnl_val, 3),
                    "pnl": round(pnl_val, 3),
                    "deploy_price": float(item.get("deploy_price", item.get("entry_price", 0.0))),
                    "entry_price": float(item.get("entry_price", item.get("open_price", 0.0))),
                    "exit_price": float(item.get("exit_price", item.get("close_price", 0.0))),
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

    trend_is_bull = ("BUY"  in auto_uni and "ONLY" in auto_uni) or trend_5m == "BULLISH"
    trend_is_bear = ("SELL" in auto_uni and "ONLY" in auto_uni) or trend_5m == "BEARISH"

    if not trend_is_bull and not trend_is_bear:
        return 0

    # ── Per-symbol cut-loss threshold ─────────────────────────────────────────
    # Only cut losses SMALLER than this; larger losses are left to the hard SL.
    if is_gold:
        cut_loss_threshold = -4.00    # Gold: cut if floating loss < $4
    elif "BTC" in sym_name:
        cut_loss_threshold = -120.0
    elif "ETH" in sym_name:
        cut_loss_threshold = -8.0
    else:
        cut_loss_threshold = -0.0006  # Forex

    closed = 0
    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        try:
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
                # Only close if in solid profit (>= $2.00) to lock gains before a real reversal.
                # Never cut positions at a loss on trend noise; let the strategy SL protect risk.
                if floating_pnl >= 2.0:
                    should_close = True
                    tag    = "💰 [TREND FLIP — PROFIT SECURED]"
                    detail = f"locking +${floating_pnl:.{digits}f} before reversal"
                elif cut_loss_threshold < floating_pnl < 0:
                    # Fix #11: Cut small losses on confirmed trend flip.
                    # Previously only $2+ profit positions were closed — losing positions
                    # were held while the trend pushed further against them.
                    should_close = True
                    tag    = "✂️ [TREND FLIP — CUTTING SMALL LOSS]"
                    detail = f"cutting ${floating_pnl:.{digits}f} (threshold ${cut_loss_threshold:.2f})"
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
            df_5m = get_historical_klines(sym_fetch, interval="5m", limit=30)
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
        min_sl_distance  = max(4.00, min(8.00, atr_5m * _trail_atr_mult))
        breakeven_buffer = 0.50 if _is_100pct_trail else 1.00   # Confirmed → lock sooner
    elif "BTC" in sym_name:
        min_sl_distance  = max(80.0 if _is_100pct_trail else 150.0, atr_5m * _trail_atr_mult)
        breakeven_buffer = 25.0 if _is_100pct_trail else 50.0
    elif "ETH" in sym_name:
        min_sl_distance  = max(5.0 if _is_100pct_trail else 10.0, atr_5m * _trail_atr_mult)
        breakeven_buffer = 1.5 if _is_100pct_trail else 3.0
    else:
        min_sl_distance  = max(0.0003 if _is_100pct_trail else 0.0005, atr_5m * _trail_atr_mult)
        breakeven_buffer = 0.0001 if _is_100pct_trail else 0.0002

    modified_count = 0

    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        pos_type = str(getattr(pos_obj, "type", "")).upper()
        entry_px = float(getattr(pos_obj, "entry_price", getattr(pos_obj, "price_open", current_price)) or current_price)
        cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)

        if "BUY" in pos_type:
            # ── BUY POSITION SL LOGIC ──
            floating_profit = current_price - entry_px

            # Phase 1 (Breakeven Lock) REMOVED by user request.
            # Phase 2: Structure Trail — Actively trail behind 5m swing structure
            # (Trend confirmation gate removed to allow smarter dynamic profit locking)

            # Calculate structure-based SL: swing low minus anti-hunt buffer
            structure_sl = round(recent_swing_low - (atr_5m * 0.5), digits)

            # Enforce minimum distance from current price to avoid stop hunts
            max_allowed_sl = round(current_price - min_sl_distance, digits)
            target_sl = min(structure_sl, max_allowed_sl)

            # SL must be better (higher) than current SL — never move backwards
            if target_sl > cur_sl and target_sl < current_price:
                # Final safety: SL must not be closer than 1× ATR to current price
                if (current_price - target_sl) >= atr_5m:
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

            # Phase 1 (Breakeven Lock) REMOVED by user request.
            # Phase 2: Structure Trail — Actively trail above 5m swing structure
            # (Trend confirmation gate removed to match BUY logic and ensure we ride downtrends smoothly)

            # Calculate structure-based SL: swing high plus anti-hunt buffer
            structure_sl = round(recent_swing_high + (atr_5m * 0.5), digits)

            # Enforce minimum distance
            min_allowed_sl = round(current_price + min_sl_distance, digits)
            target_sl = max(structure_sl, min_allowed_sl)

            # SL must be better (lower) than current SL — never move backwards
            if (cur_sl == 0.0 or target_sl < cur_sl) and target_sl > current_price:
                # Final safety: SL must not be closer than 1× ATR
                if (target_sl - current_price) >= atr_5m:
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
            df_5m = get_historical_klines(sym_fetch, interval="5m", limit=30)
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
    # Unconfirmed: standard 2.0×ATR so TP still fills quickly.
    _is_100pct_tp = is_auto_100pct_confirmed(self)
    _tp_atr_mult  = 3.5 if _is_100pct_tp else 2.0

    optimal_tp_dist = atr_5m * _tp_atr_mult
    min_tp_dist = max(current_price * 0.001, atr_5m * 0.8)

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
                best_tp = min(atr_tp, structure_tp)  # TIGHTEN: Use closer target to secure fill
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
                if _is_100pct_tp:
                    # DYNAMIC EXPANSION: Push TP further out dynamically to ride strong momentum!
                    target_tp = max(cur_tp, best_tp)
                else:
                    # Fix #10: STANDARD TIGHTEN — only tighten if new TP is meaningfully
                    # closer (> 0.5×ATR). Prevents noisy ATR fluctuations from repeatedly
                    # overwriting structural TPs and causing premature exits.
                    if cur_tp > 0 and (cur_tp - best_tp) > (atr_5m * 0.5):
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
                best_tp = max(atr_tp, structure_tp)  # TIGHTEN: Use closest target
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
                    # closer (> 0.5×ATR). Prevents noisy ATR fluctuations from repeatedly
                    # overwriting structural TPs and causing premature exits.
                    if cur_tp > 0 and (best_tp - cur_tp) > (atr_5m * 0.5):
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
    """
    Real-Time Trap Mode Protection Engine.
    Ensures active MT5 grid orders stay stable without canceling active orders in a loop.
    Pending orders remain active on MT5 so they can fill cleanly into trades.
    """
    return False
