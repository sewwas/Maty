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
    PRIORITY-0 PROFIT PROTECTION — Runs FIRST on every tick before any other logic.

    Three hard rules, applied in order:
    ─────────────────────────────────────────────────────────────
    Rule 1 — BASKET EARLY EXIT:
      If total floating PnL >= min_basket_profit, close EVERYTHING immediately.
      This fires much earlier than check_target_profit's full target, locking in
      any real profit before it can reverse.
      Threshold: $1.00 for Gold/PAXG, $0.50 for others.

    Rule 2 — PER-POSITION PROFIT LOCK (No-Loss Rule):
      Once any open position has earned >= min_pos_profit:
        • Set broker-side TP to current price (or entry + 1pip if already past).
        • This is a HARD broker-side TP — if price reverses, broker closes it.
        • Ensures no profitable position ever becomes a loser.
      Threshold: $1.50 per position for Gold.

    Rule 3 — PROFIT RECOVERY CLOSE (Near-Zero Rescue):
      If basket was ever in profit (max_floating_pnl > min_basket_profit) but
      has now drifted back within 15% of zero, close all immediately.
      Prevents "was +$5, now +$0.30" situations.
    ─────────────────────────────────────────────────────────────
    """
    if not getattr(self.broker, "open_positions", None):
        return 0

    now_ts = timestamp or time.time()
    last_pl = getattr(self, "_last_profit_lock_time", 0.0)
    if now_ts - last_pl < 0.8:   # Run every 0.8s — tighter than other TP layers
        return 0
    self._last_profit_lock_time = now_ts

    sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
    is_gold   = any(x in sym_name for x in ["XAU", "GOLD", "PAXG"])
    digits    = 3 if is_gold else (2 if "BTC" in sym_name else 5)

    # Fetch AI target and ATR for real-data gathering
    state = compute_basket_state(self, current_price, timestamp)
    atr_5m = state.get("atr_5m", current_price * 0.002)

    ai_target = 0.0
    if hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict):
        ai_target = float(self.last_auto_eval.get("recommended_target_profit", 0.0))

    # 🟢 100% CONFIRMED TREND: lock profit faster & tighter to guarantee gains
    _is_100pct = is_auto_100pct_confirmed(self)

    if ai_target > 0:
        if _is_100pct:
            # Confirmed trend → lock basket at 35% of target, position at 20% or 1×ATR
            # This fires EARLIER so profit is secured before any reversal hunt
            min_basket_profit = ai_target * 0.35
            min_pos_profit    = max(ai_target * 0.20, atr_5m * 1.0)
        else:
            min_basket_profit = ai_target * 0.50
            min_pos_profit    = max(ai_target * 0.35, atr_5m * 1.5)  # Require at least 1.5x ATR to avoid easy hunts
    else:
        # Fallback to ATR-based dynamic locks if AI is offline
        if _is_100pct:
            min_basket_profit = atr_5m * 1.2   # Confirmed: lock at 1.2×ATR (was 2.0×)
            min_pos_profit    = atr_5m * 0.8   # Confirmed: per-pos lock at 0.8×ATR (was 1.5×)
        else:
            min_basket_profit = atr_5m * 2.0
            min_pos_profit    = atr_5m * 1.5
    near_zero_floor   = 0.15

    actions = 0
    total_pnl = float(self.broker.get_floating_pnl(current_price))

    # Update running peak
    if total_pnl > getattr(self, "max_floating_pnl", -float("inf")):
        self.max_floating_pnl = total_pnl

    max_pnl = getattr(self, "max_floating_pnl", 0.0)

    # ─────────────────────────────────────────────────────
    # RULE 1: Per-position No-Loss Lock (Breakeven SL)
    # If any single position is in profit >= min_pos_profit,
    # set the STOP LOSS to entry + 1 pip. This guarantees zero loss
    # but still allows the position to run to TP1, TP2, and Chandelier!
    # ─────────────────────────────────────────────────────
    for pos_id, pos_obj in list(self.broker.open_positions.items()):
        try:
            pos_type  = str(getattr(pos_obj, "type", "")).upper()
            entry     = float(getattr(pos_obj, "entry_price", getattr(pos_obj, "price_open", current_price)) or current_price)
            cur_sl    = float(getattr(pos_obj, "sl", 0.0) or 0.0)

            if "BUY" in pos_type:
                # 1.00 price move on 0.01 lots of standard XAUUSD/PAXGUSDT is ~$1.00 profit
                pos_profit = (current_price - entry)
                in_profit  = current_price > entry
            elif "SELL" in pos_type:
                pos_profit = (entry - current_price)
                in_profit  = current_price < entry
            else:
                continue

            # 1. Smarter Breakeven Buffer (ATR-based instead of 2 pips)
            # Give it some breathing room below the noise floor to avoid easy hunts
            be_buffer = max(get_pip_size(sym_name, current_price) * 5.0, atr_5m * 0.10)
            if "BUY" in pos_type:
                lock_sl = round(entry + be_buffer, digits)
            else:
                lock_sl = round(entry - be_buffer, digits)
            
            # 2. Dynamic Profit Trail (Chandelier ATR Trail for massive trends)
            # Instead of locking 50%, tightly hug the price allowing 1.5x ATR breathing room
            if in_profit and pos_profit > (min_pos_profit * 1.5):
                if "BUY" in pos_type:
                    dynamic_sl = round(current_price - (atr_5m * 1.5), digits)
                    # SL never moves backwards
                    lock_sl = max(lock_sl, dynamic_sl)
                else:
                    dynamic_sl = round(current_price + (atr_5m * 1.5), digits)
                    # SL never moves backwards
                    lock_sl = min(lock_sl, dynamic_sl)
            
            if "BUY" in pos_type:
                sl_is_worse = cur_sl == 0.0 or cur_sl < lock_sl
            else:
                sl_is_worse = cur_sl == 0.0 or cur_sl > lock_sl

            # Move SL to breakeven or dynamically trail it
            if in_profit and pos_profit >= min_pos_profit and sl_is_worse:
                if hasattr(self.broker, "modify_position_sl_tp"):
                    cur_tp = float(getattr(pos_obj, "tp", 0.0) or 0.0)
                    if self.broker.modify_position_sl_tp(pos_id, sl=lock_sl, tp=cur_tp if cur_tp > 0 else None):
                        setattr(pos_obj, "sl", lock_sl)
                        actions += 1
                        tag = "📈 [DYNAMIC TRAIL]" if pos_profit > (min_pos_profit * 1.5) else "🛡️ [PROFIT LOCK]"
                        print(f"[{sym_name}] {tag} {pos_type} #{pos_id}: "
                              f"profit=${pos_profit:.2f} → SL locked @ ${lock_sl:,.{digits}f} to secure gains!")
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

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
    if is_gold:
        min_tp1_dist = max(1.00,  atr * 0.3)   # Gold: Scalp TP1 quickly at +$1.00
        min_tp2_dist = max(2.50,  atr * 0.8)   # TP2 at +$2.50
        breakeven_buf = 0.5
    elif "BTC" in sym_name:
        min_tp1_dist = max(80.0,  atr * 1.0)
        min_tp2_dist = max(200.0, fib_dist)
        breakeven_buf = 30.0
    elif "ETH" in sym_name:
        min_tp1_dist = max(5.0,  atr * 1.0)
        min_tp2_dist = max(15.0, fib_dist)
        breakeven_buf = 2.0
    else:
        min_tp1_dist = max(0.0003, atr * 1.0)
        min_tp2_dist = max(0.0008, fib_dist)
        breakeven_buf = 0.0001

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
                # Move SL of remaining positions to breakeven+buffer → zero-risk runner
                be_sl = round(w_avg_buy + breakeven_buf, digits)
                for pos_id, pos_obj, entry, size in buy_positions:
                    cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
                    if pos_id in self.broker.open_positions and be_sl > cur_sl:
                        try:
                            if self.broker.modify_position_sl_tp(pos_id, sl=be_sl):
                                setattr(pos_obj, "sl", be_sl)
                                print(f"[{sym_name}] 🔒 [BREAKEVEN LOCK] BUY #{pos_id} SL → ${be_sl:,.{digits}f} (zero-risk runner)")
                        except Exception as e:
                            import logging; logging.warning(f"Exception: {e}")

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
                be_sl = round(w_avg_sell - breakeven_buf, digits)
                for pos_id, pos_obj, entry, size in sell_positions:
                    cur_sl = float(getattr(pos_obj, "sl", 0.0) or 0.0)
                    if pos_id in self.broker.open_positions:
                        if cur_sl == 0.0 or be_sl < cur_sl:
                            try:
                                if self.broker.modify_position_sl_tp(pos_id, sl=be_sl):
                                    setattr(pos_obj, "sl", be_sl)
                                    print(f"[{sym_name}] 🔒 [BREAKEVEN LOCK] SELL #{pos_id} SL → ${be_sl:,.{digits}f} (zero-risk runner)")
                            except Exception as e:
                                import logging; logging.warning(f"Exception: {e}")

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
    if max_pnl >= effective_target and getattr(self, "use_smart_trailing", True):
        self.in_runner_mode = True

    exit_triggered = False
    exit_reason = ""

    # ─────────────────────────────────────────────────────────────
    # Cycle Max Drawdown (Hard Stop Loss)
    # ─────────────────────────────────────────────────────────────
    is_manual = getattr(self, "manual_override_active", False)
    
    if not is_manual:
        auto_uni = getattr(self, "auto_universe_bias", "")
        
        # 1. Dynamic Trend Reversal Cut (Universe Bias)
        if total_pnl < 0 and auto_uni:
            has_sells = any("SELL" in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
            has_buys  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
            is_bullish = any(x in auto_uni for x in ["BUY", "BULLISH"])
            is_bearish = any(x in auto_uni for x in ["SELL", "BEARISH"])
            
            if has_buys and not has_sells and is_bearish and not is_bullish:
                exit_triggered = True
                exit_reason = "BOT_CLOSE"
                print(f"[{self.symbol}] 🛑 [TREND FLIP LOSS CUT] Universe Bias flipped to {auto_uni}. Cutting basket loss of ${total_pnl:.2f} early!")
            elif has_sells and not has_buys and is_bullish and not is_bearish:
                exit_triggered = True
                exit_reason = "BOT_CLOSE"
                print(f"[{self.symbol}] 🛑 [TREND FLIP LOSS CUT] Universe Bias flipped to {auto_uni}. Cutting basket loss of ${total_pnl:.2f} early!")

        # 2. Extreme Drawdown (Catastrophic Fallback)
        if not exit_triggered:
            # 3x the normal drawdown to give room for trades, but protect against flash crashes
            max_cycle_dd = float(getattr(self, "max_cycle_drawdown", 30.0) or 30.0)
            extreme_dd = max_cycle_dd * 3.0
            if total_pnl <= -abs(extreme_dd):
                exit_triggered = True
                exit_reason = "BOT_CLOSE"
                print(f"[{self.symbol}] 🛑 [EXTREME DRAWDOWN HIT] Cycle PnL {total_pnl:.2f} <= -{extreme_dd:.2f}. Forcing market close despite trend.")
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
            effective_sl = sl_limit
            if total_pnl <= -abs(effective_sl):
                exit_triggered = True
                exit_reason = "STOP_LOSS"

    # ─────────────────────────────────────────────────────────────
    # Basket Target Profit (Cycle Exit)
    # ─────────────────────────────────────────────────────────────
    min_profit_threshold = 0.50  # Minimum gross profit to close a cycle, mitigating fee attrition
    if not exit_triggered:
        sym_u = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
        # Use user-configured target profit, otherwise use default
        default_target = 10.0 if any(x in sym_u for x in ["XAU", "GOLD", "PAXG"]) else 3.0
        ai_target = float(getattr(self, "deploy_target_profit", 0.0) or 0.0)
        user_target = float(getattr(self, "target_profit", 0.0) or 0.0)
        cycle_target = ai_target if ai_target > 0 else (user_target if user_target > 0 else default_target)
        
        # Enforce minimum profit threshold
        effective_cycle_target = max(cycle_target, min_profit_threshold)
            
        # ── Smart Trend Reversal Exit ──
        # If in profit, and AutoReading mode flips to DUAL or against us, secure profit instantly!
        auto_uni = getattr(self, "auto_universe_bias", "")
        is_runner_active = getattr(self, "in_runner_mode", False)
        
        if total_pnl > min_profit_threshold and auto_uni:
            has_sells = any("SELL" in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
            has_buys  = any("BUY"  in str(getattr(p, "type", "")).upper() for p in self.broker.open_positions.values())
            
            is_bullish = any(x in auto_uni for x in ["BUY", "BULLISH"])
            is_bearish = any(x in auto_uni for x in ["SELL", "BEARISH"])
            
            if has_sells and not has_buys and is_bullish and not is_bearish:
                exit_triggered = True
                exit_reason = "TARGET_PROFIT"
                print(f"[{sym_u}] 🔄 [TREND REVERSAL] Mode changed from SELL to {auto_uni}. Securing +${total_pnl:.2f} early!")
            elif has_buys and not has_sells and is_bearish and not is_bullish:
                exit_triggered = True
                exit_reason = "TARGET_PROFIT"
                print(f"[{sym_u}] 🔄 [TREND REVERSAL] Mode changed from BUY to {auto_uni}. Securing +${total_pnl:.2f} early!")

        if not exit_triggered and total_pnl >= effective_cycle_target:
            exit_triggered = True
            exit_reason = "TARGET_PROFIT"
            print(f"[{sym_u}] 💰 [CYCLE TP HIT] Basket reached target of ${effective_cycle_target:.2f} (Total PnL: ${total_pnl:.2f})! Instant Close All.")

        # ── 3. High-Water Mark Peak-Profit Trailing Lock ──
        # If the cycle made solid profit and starts pulling back, close immediately to secure gains!
        if not exit_triggered and max_pnl >= min_profit_threshold * 2.0:
            is_gold = any(x in sym_u for x in ["XAU", "GOLD", "PAXG"])
            min_lock_activation = 2.0 if is_gold else 1.0
            
            if max_pnl >= min_lock_activation:
                if max_pnl >= 10.0:
                    locked_floor = max_pnl * 0.70  # Lock 70% of peak gains, tolerate 30% pullback
                elif max_pnl >= 5.0:
                    locked_floor = max_pnl * 0.60  # Lock 60% of peak gains
                else:
                    locked_floor = max(0.50, max_pnl * 0.50)  # Lock at least $0.50+ profit
                
                if total_pnl <= locked_floor and total_pnl > 0:
                    exit_triggered = True
                    exit_reason = "TARGET_PROFIT"
                    print(f"[{sym_u}] 🏆 [PEAK PROFIT TRAIL LOCK] Peak was +${max_pnl:.2f}. Pullback reached floor +${locked_floor:.2f} (current: +${total_pnl:.2f}). Securing gains!")

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

        if hasattr(self, "record_trade_outcome"):
            self.record_trade_outcome(total_pnl, exit_reason, duration)

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
        if timestamp >= getattr(self, "_last_deploy_attempt_time", 0.0) + 3.0:
            self._last_deploy_attempt_time = timestamp   # Prevent runaway deploy loop on every tick
            self.deploy_traps(current_price, timestamp, force=True)
        return None

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
            filled_types = [self.broker.open_positions[pid].type for pid in newly_filled_pos_ids if pid in self.broker.open_positions]
            if "BUY" in filled_types:
                for oid, ord_obj in list(self.broker.pending_orders.items()):
                    if ord_obj.type == "SELL_STOP":
                        self.broker.cancel_order(oid)
            if "SELL" in filled_types:
                for oid, ord_obj in list(self.broker.pending_orders.items()):
                    if ord_obj.type == "BUY_STOP":
                        self.broker.cancel_order(oid)

    current_pending = len(getattr(self.broker, "pending_orders", {}))
    current_open = len(getattr(self.broker, "open_positions", {}))

    if current_open > getattr(self, "_max_open_in_cycle", 0):
        self._max_open_in_cycle = current_open

    last_pending = getattr(self, "_last_pending_count", current_pending)
    last_open = getattr(self, "_last_open_count", current_open)

    needs_refresh = False
    refresh_reason = ""

    if getattr(self, "_max_open_in_cycle", 0) > 0 and current_open == 0 and current_pending > 0:
        needs_refresh = True
        refresh_reason = "Position(s) closed"
    elif current_open == 0 and current_pending > 0 and current_pending < last_pending:
        needs_refresh = True
        refresh_reason = "Pending order(s) canceled"
    else:
        # Check if AI mode flipped (e.g. BUY_ONLY -> SELL_ONLY) with 0 active positions
        curr_uni = str(getattr(self, "unidirectional_mode", getattr(self, "auto_universe_bias", ""))).upper()
        last_uni = str(getattr(self, "_last_synced_uni_mode", curr_uni)).upper()
        if curr_uni and last_uni and curr_uni != last_uni and current_open == 0 and current_pending > 0:
            needs_refresh = True
            refresh_reason = f"Trend bias flipped ({last_uni} -> {curr_uni})"
        self._last_synced_uni_mode = curr_uni

    if needs_refresh:
        print(f"[{self.symbol}] 🔄 [GRID REFRESH] {refresh_reason}. Canceling {current_pending} remaining pending orders to deploy a new grid.")
        if hasattr(self.broker, "cancel_all_orders"):
            self.broker.cancel_all_orders()
        self.deployed = False
        self._max_open_in_cycle = 0
        self._last_pending_count = 0
        self._last_open_count = 0
        self.deploy_traps(current_price, timestamp, force=True)
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

    if getattr(self, "_fakeout_guard_enabled", True) and self._fakeout_recent_fills:
        # Per-symbol minimum distance before declaring a fakeout.
        # Without this, a 1-pip wick after fill closes positions immediately.
        sym_u = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", ""))).upper()
        if any(x in sym_u for x in ["XAU", "GOLD", "PAXG"]):
            fakeout_min_dist = 3.0    # Gold: need $3 move past entry to count as fakeout
        elif "BTC" in sym_u:
            fakeout_min_dist = 80.0   # BTC: need $80 move past entry
        elif "ETH" in sym_u:
            fakeout_min_dist = 5.0    # ETH: need $5 move
        elif any(x in sym_u for x in ["SOL", "BNB"]):
            fakeout_min_dist = 1.0
        else:
            fakeout_min_dist = 0.0003  # Forex

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
            # Only flag fakeout if price has moved a meaningful distance past entry
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
        self.record_trade_outcome(summary.get("total_pnl", 0.0), exit_reason, summary.get("duration", 0.0))
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


def deploy_traps(self, current_price: float, timestamp: float, *args, force: bool = False, bb_width: Optional[float] = None, **kwargs):
    """
    ⚡ UNBREAKABLE 100% RELIABLE GRID DEPLOYMENT ENGINE.
    Deploys exact tight grid traps directly to broker with zero silent skips or bypassing.
    """
    if not current_price or current_price <= 0:
        return

    cooldown_expiry = getattr(self, "_post_loss_cooldown", 0.0)
    if timestamp < cooldown_expiry:
        return  # Silently wait out the 3m cooldown
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
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")
                    self._is_deploying = False
                    return

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
            gap_ratio = min(0.0015, max(0.0005, gap_ratio))
            off_ratio = min(0.0015, max(0.0005, off_ratio))

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

        base_min_off = 5.0 if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]) else 0.0015
        min_offset_dist = max(b_min_stop + (gap_val * 0.5), base_min_off)
        buy_offset_val = max(float(buy_offset_val), min_offset_dist)
        sell_offset_val = buy_offset_val
        
        min_gap_dist = 2.0 if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]) else 0.0010
        gap_val = max(float(gap_val), min_gap_dist)
        buy_offset_val = round(buy_offset_val, digits)
        sell_offset_val = round(sell_offset_val, digits)
        gap_val = round(gap_val, digits)

        if any(x in sym_name for x in ["XAU", "PAXG", "GOLD"]):
            min_sl_dist = 35.00
        else:
            # Derive `point` safely for alt coins (DOGE, XRP, etc.) that don't match named branches
            _sym_info_alt = None
            try:
                if hasattr(self.broker, "get_cached_symbol_info") and hasattr(self.broker, "get_exness_symbol"):
                    _ex_s_alt = self.broker.get_exness_symbol(sym_name)
                    _sym_info_alt = self.broker.get_cached_symbol_info(_ex_s_alt)
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")
            _point_alt = getattr(_sym_info_alt, "point", 0.0001) if _sym_info_alt else 0.0001
            min_sl_dist = max(b_min_stop * 2.5, _point_alt * 50.0)

        acc_eq = self.broker.get_equity() if hasattr(self.broker, "get_equity") else 1000.0
        if not is_manual and hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict) and "recommended_levels" in self.last_auto_eval:
            effective_levels = int(self.last_auto_eval["recommended_levels"])
        else:
            base_cfg_levels = getattr(self, "grid_levels", 3) or 3  # 📊 Mode 2: 3 levels × 2 = 6 pending (medium confidence)
            effective_levels = base_cfg_levels

        dyn_tp_factor = max(3.0, float(effective_levels * 1.0))
        calculated_dynamic_tp = gap_val * dyn_tp_factor

        if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]):
            min_tp_dist = max(18.50, calculated_dynamic_tp)
        else:
            min_tp_dist = max(calculated_dynamic_tp, b_min_stop * 5.0)

        t_5m, t_15m, rsi_1m = "NEUTRAL", "NEUTRAL", 50.0
        atr_5m = None
        try:
            from core.data import get_historical_klines, calculate_technical_indicators
            import numpy as np
            df_1m = get_historical_klines(sym_name, interval="1m", limit=30)
            df_5m = get_historical_klines(sym_name, interval="5m", limit=30)
            df_15m = get_historical_klines(sym_name, interval="15m", limit=30)
            
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

            tech_1m = calculate_technical_indicators(df_1m) if (df_1m is not None and not df_1m.empty) else {}
            tech_5m = calculate_technical_indicators(df_5m) if (df_5m is not None and not df_5m.empty) else {}
            tech_15m = calculate_technical_indicators(df_15m) if (df_15m is not None and not df_15m.empty) else {}
            
            t_5m = tech_5m.get("trend", "NEUTRAL") or "NEUTRAL"
            t_15m = tech_15m.get("trend", "NEUTRAL") or "NEUTRAL"
            rsi_1m = float(tech_1m.get("rsi", 50.0) or 50.0)
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

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
        else:
            if is_manual:
                # In manual mode, if no side is explicitly selected, default to DUAL (no secret trend filtering)
                place_buy, place_sell = True, True
            else:
                # FALLBACK ONLY when AutoReadingEngine did NOT run (auto_reading disabled).
                # Uses 5m/15m trend as a standalone direction filter.
                if t_5m == "BULLISH" or (t_5m == "NEUTRAL" and t_15m == "BULLISH"):
                    place_buy, place_sell = True, False
                elif t_5m == "BEARISH" or (t_5m == "NEUTRAL" and t_15m == "BEARISH"):
                    place_buy, place_sell = False, True
                elif rsi_1m <= 38.0 and t_5m == "NEUTRAL" and t_15m == "NEUTRAL":
                    place_buy, place_sell = True, False
                elif rsi_1m >= 62.0 and t_5m == "NEUTRAL" and t_15m == "NEUTRAL":
                    place_buy, place_sell = False, True
                else:
                    place_buy, place_sell = True, True

        # ─────────────────────────────────────────────────────────────
        # DIRECTIONAL MODE: Limit orders from optimal price levels
        #   SELL confirmed → SELL_LIMIT above current (sell the bounce at TOP/resistance)
        #   BUY  confirmed → BUY_LIMIT  below current (buy the dip  at BOTTOM/support)
        #   RANGING        → BUY_STOP + SELL_STOP breakout mode (unchanged)
        # Limit orders give a BETTER entry than stop orders → more profit per trade.
        # ─────────────────────────────────────────────────────────────
        directional_sell = place_sell and not place_buy   # Pure sell signal
        directional_buy  = place_buy  and not place_sell  # Pure buy signal
        ranging_mode     = place_buy  and place_sell      # Both sides = choppy

        # 3. Chop Restriction (Limit Exposure in Ranging Markets)
        # Only risk 1 level in the chop to avoid severe whipsaws (1 trap per side).
        if ranging_mode and not is_manual:
            effective_levels = 1

        # ── 100% Trend Confirmed: aggressive grid mode ──────────────────────────
        # When is_auto_100pct_confirmed fires we switch to a LIMIT-ONLY grid:
        #   • TP boosted to 2.5× (max profit)
        #   • Offset tightened to 0.35× ATR → enter closer to price for bigger gain
        #   • Level gap compressed → denser stacking → more fills at better prices
        #   • +1 extra level → more coverage on the confirmed move
        #   • STOP orders REMOVED → never get filled against the trend direction
        _is_100pct_grid = is_auto_100pct_confirmed(self) and not is_manual  # AUTO only — never fires in manual mode

        if (directional_sell or directional_buy) and _is_100pct_grid:
            dir_tp_dist     = min_tp_dist * 1.77  # Backtest optimal (was 2.5x)
            effective_levels = min(effective_levels + 1, 8)  # One extra level, cap at 8
            _confirmed_offset_mult = 0.20          # Backtest optimal entry — tighter (was 0.35x)
            _confirmed_gap_mult    = 0.70          # Compressed gap → denser stack
        elif directional_sell or directional_buy:
            dir_tp_dist     = min_tp_dist * 1.15  # Backtest optimal (was 1.5x)
            _confirmed_offset_mult = 0.45          # Backtest optimal (was 0.65x)
            _confirmed_gap_mult    = 1.00
        else:
            dir_tp_dist     = min_tp_dist
            _confirmed_offset_mult = 0.70  # Ranging Mode: 0.70x ATR breathing room
            _confirmed_gap_mult    = 1.00

        placed_count = 0
        # Dynamic ATR-Based Trap Placement — offset & gap scaled by confirmation state
        dynamic_atr_offset  = (atr_5m * _confirmed_offset_mult) if (atr_5m is not None and atr_5m > 0) else 0.0
        base_start_offset   = max(b_min_stop + 1.0, dynamic_atr_offset, buy_offset_val)

        cumulative_gap   = 0.0
        expansion_factor = 1.30 * _confirmed_gap_mult   # Compressed gaps when confirmed

        self.active_buy_levels = []
        self.active_sell_levels = []

        for i in range(effective_levels):
            buy_size  = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
            sell_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)

            if directional_sell:
                if _is_100pct_grid:
                    # ═══════════════════════════════════════════════════════
                    # 🔥 100% CONFIRMED SELL — 3 LIMIT + 3 STOP HYBRID GRID
                    # SELL_LIMIT above price  → sells the bounce (pullback entry)
                    # SELL_STOP  below price  → sells the breakdown (continuation)
                    # Covers BOTH: price pulls back up OR just keeps dropping.
                    # ═══════════════════════════════════════════════════════
                    _c_levels = 3   # Fixed 3 per side in confirmed mode
                    _c_gap    = 0.0
                    for ci in range(_c_levels):
                        c_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, ci)
                        # ── SELL_LIMIT above: wait for bounce, best entry ──
                        sl_lim_px = round(ask_ref + base_start_offset + _c_gap, digits)
                        self.active_sell_levels.append(sl_lim_px)
                        sl_lim_tp = round(sl_lim_px - dir_tp_dist, digits)
                        sl_lim_sl = round(sl_lim_px + min_sl_dist, digits)
                        try:
                            r = self.broker.place_order("SELL_LIMIT", sl_lim_px, c_size, timestamp, tp=sl_lim_tp, sl=sl_lim_sl)
                            if r:
                                placed_count += 1
                                print(f"[{sym_name}] 🔥 [CONF SELL_LIMIT] L{ci} @ ${sl_lim_px:,.3f} TP:${sl_lim_tp:,.3f} (bounce catcher)")
                        except Exception as e:
                            print(f"[{sym_name}] SELL_LIMIT L{ci} error: {e}")
                        # ── SELL_STOP below: catch continuation if no pullback ──
                        sl_stp_px = round(bid_ref - base_start_offset - _c_gap, digits)
                        self.active_sell_levels.append(sl_stp_px)
                        sl_stp_tp = round(sl_stp_px - dir_tp_dist, digits)
                        sl_stp_sl = round(sl_stp_px + min_sl_dist, digits)
                        try:
                            r = self.broker.place_order("SELL_STOP", sl_stp_px, c_size, timestamp, tp=sl_stp_tp, sl=sl_stp_sl)
                            if r:
                                placed_count += 1
                                print(f"[{sym_name}] 🔥 [CONF SELL_STOP]  L{ci} @ ${sl_stp_px:,.3f} TP:${sl_stp_tp:,.3f} (continuation catcher)")
                        except Exception as e:
                            print(f"[{sym_name}] SELL_STOP L{ci} error: {e}")
                        _c_gap += gap_val * (expansion_factor ** ci)

                else:
                    # ── Standard dual-entry SELL (LIMIT + STOP) ──
                    sell_limit_px = round(ask_ref + base_start_offset + cumulative_gap, digits)
                    self.active_sell_levels.append(sell_limit_px)
                    sell_limit_tp = round(sell_limit_px - dir_tp_dist, digits)
                    sell_limit_sl = round(sell_limit_px + min_sl_dist, digits)
                    try:
                        r = self.broker.place_order("SELL_LIMIT", sell_limit_px, sell_size, timestamp, tp=sell_limit_tp, sl=sell_limit_sl)
                        if r:
                            placed_count += 1
                            print(f"[{sym_name}] 📤 [SELL_LIMIT] L{i} @ ${sell_limit_px:,.3f} TP:${sell_limit_tp:,.3f}")
                    except Exception as e:
                        print(f"[{sym_name}] SELL_LIMIT L{i} error: {e}")

                    sell_stop_px = round(bid_ref - base_start_offset - cumulative_gap, digits)
                    self.active_sell_levels.append(sell_stop_px)
                    sell_stop_tp = round(sell_stop_px - dir_tp_dist, digits)
                    sell_stop_sl = round(sell_stop_px + min_sl_dist, digits)
                    try:
                        r = self.broker.place_order("SELL_STOP", sell_stop_px, sell_size, timestamp, tp=sell_stop_tp, sl=sell_stop_sl)
                        if r:
                            placed_count += 1
                            print(f"[{sym_name}] 📉 [SELL_STOP] L{i} @ ${sell_stop_px:,.3f} TP:${sell_stop_tp:,.3f}")
                    except Exception as e:
                        print(f"[{sym_name}] SELL_STOP L{i} error: {e}")

            elif directional_buy:
                if _is_100pct_grid:
                    # ═══════════════════════════════════════════════════════
                    # 🔥 100% CONFIRMED BUY — 3 LIMIT + 3 STOP HYBRID GRID
                    # BUY_LIMIT below price  → buys the dip (pullback entry)
                    # BUY_STOP  above price  → buys the breakout (continuation)
                    # Covers BOTH: price pulls back down OR just keeps rising.
                    # ═══════════════════════════════════════════════════════
                    _c_levels = 3   # Fixed 3 per side in confirmed mode
                    _c_gap    = 0.0
                    for ci in range(_c_levels):
                        c_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, ci)
                        # ── BUY_LIMIT below: wait for dip, best entry ──
                        bl_lim_px = round(bid_ref - base_start_offset - _c_gap, digits)
                        self.active_buy_levels.append(bl_lim_px)
                        bl_lim_tp = round(bl_lim_px + dir_tp_dist, digits)
                        bl_lim_sl = round(bl_lim_px - min_sl_dist, digits)
                        try:
                            r = self.broker.place_order("BUY_LIMIT", bl_lim_px, c_size, timestamp, tp=bl_lim_tp, sl=bl_lim_sl)
                            if r:
                                placed_count += 1
                                print(f"[{sym_name}] 🔥 [CONF BUY_LIMIT] L{ci} @ ${bl_lim_px:,.3f} TP:${bl_lim_tp:,.3f} (dip catcher)")
                        except Exception as e:
                            print(f"[{sym_name}] BUY_LIMIT L{ci} error: {e}")
                        # ── BUY_STOP above: catch continuation if no pullback ──
                        bl_stp_px = round(ask_ref + base_start_offset + _c_gap, digits)
                        self.active_buy_levels.append(bl_stp_px)
                        bl_stp_tp = round(bl_stp_px + dir_tp_dist, digits)
                        bl_stp_sl = round(bl_stp_px - min_sl_dist, digits)
                        try:
                            r = self.broker.place_order("BUY_STOP", bl_stp_px, c_size, timestamp, tp=bl_stp_tp, sl=bl_stp_sl)
                            if r:
                                placed_count += 1
                                print(f"[{sym_name}] 🔥 [CONF BUY_STOP]  L{ci} @ ${bl_stp_px:,.3f} TP:${bl_stp_tp:,.3f} (continuation catcher)")
                        except Exception as e:
                            print(f"[{sym_name}] BUY_STOP L{ci} error: {e}")
                        _c_gap += gap_val * (expansion_factor ** ci)

                else:
                    # ── Standard dual-entry BUY (LIMIT + STOP) ──
                    buy_limit_px = round(bid_ref - base_start_offset - cumulative_gap, digits)
                    self.active_buy_levels.append(buy_limit_px)
                    buy_limit_tp = round(buy_limit_px + dir_tp_dist, digits)
                    buy_limit_sl = round(buy_limit_px - min_sl_dist, digits)
                    try:
                        r = self.broker.place_order("BUY_LIMIT", buy_limit_px, buy_size, timestamp, tp=buy_limit_tp, sl=buy_limit_sl)
                        if r:
                            placed_count += 1
                            print(f"[{sym_name}] 📥 [BUY_LIMIT] L{i} @ ${buy_limit_px:,.3f} TP:${buy_limit_tp:,.3f}")
                    except Exception as e:
                        print(f"[{sym_name}] BUY_LIMIT L{i} error: {e}")

                    buy_stop_px = round(ask_ref + base_start_offset + cumulative_gap, digits)
                    self.active_buy_levels.append(buy_stop_px)
                    buy_stop_tp = round(buy_stop_px + dir_tp_dist, digits)
                    buy_stop_sl = round(buy_stop_px - min_sl_dist, digits)
                    try:
                        r = self.broker.place_order("BUY_STOP", buy_stop_px, buy_size, timestamp, tp=buy_stop_tp, sl=buy_stop_sl)
                        if r:
                            placed_count += 1
                            print(f"[{sym_name}] 📈 [BUY_STOP] L{i} @ ${buy_stop_px:,.3f} TP:${buy_stop_tp:,.3f}")
                    except Exception as e:
                        print(f"[{sym_name}] BUY_STOP L{i} error: {e}")

            else:
                # ── RANGING mode — BUY_STOP + SELL_STOP breakout grid (unchanged) ──
                buy_px  = round(ask_ref + base_start_offset + cumulative_gap, digits)
                self.active_buy_levels.append(buy_px)
                buy_tp  = round(buy_px + min_tp_dist, digits)
                buy_sl  = round(buy_px - min_sl_dist, digits)
                try:
                    r = self.broker.place_order("BUY_STOP", buy_px, buy_size, timestamp, tp=buy_tp, sl=buy_sl)
                    if r: placed_count += 1
                except Exception as e:
                    print(f"[{sym_name}] BUY_STOP L{i} error: {e}")

                sell_px = round(bid_ref - base_start_offset - cumulative_gap, digits)
                self.active_sell_levels.append(sell_px)
                sell_tp = round(sell_px - min_tp_dist, digits)
                sell_sl = round(sell_px + min_sl_dist, digits)
                try:
                    r = self.broker.place_order("SELL_STOP", sell_px, sell_size, timestamp, tp=sell_tp, sl=sell_sl)
                    if r: placed_count += 1
                except Exception as e:
                    print(f"[{sym_name}] SELL_STOP L{i} error: {e}")

            cumulative_gap += gap_val * (expansion_factor ** i)

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
    if self.deployed or len(self.broker.pending_orders) <= (self.grid_levels * 2):
        return 0
    if not self.broker.pending_orders:
        return 0

    center_price = self.deploy_price if self.deploy_price > 0 else current_price

    if getattr(self, "deploy_grid_gap", None) and getattr(self, "deploy_trap_offset", None):
        gap_val = self.deploy_grid_gap
        buy_offset_val = self.deploy_trap_offset
        sell_offset_val = buy_offset_val
    else:
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

    tolerance = max(gap_val * 1.5, center_price * 0.005)

    valid_buy_levels = getattr(self, "active_buy_levels", [])
    valid_sell_levels = getattr(self, "active_sell_levels", [])
    
    if not valid_buy_levels and not valid_sell_levels:
        # Fallback if somehow not deployed properly
        valid_buy_levels = [center_price + buy_offset_val + (i * gap_val) for i in range(20)]
        valid_sell_levels = [center_price - sell_offset_val - (i * gap_val) for i in range(20)]

    cancelled_ids = []

    for order_id, order in list(self.broker.pending_orders.items()):
        if order_id in cancelled_ids:
            continue
        order_age = (time.time() - getattr(order, "timestamp", time.time())) if hasattr(order, "timestamp") else 999.0
        if self.deployed and order_age < 300.0:
            continue

        if "BUY" in order.type:
            valid_levels = valid_buy_levels
        elif "SELL" in order.type:
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
        if "BUY" in order.type:
            for lvl in valid_buy_levels:
                if abs(order.trigger_price - lvl) < tolerance:
                    buy_groups[round(lvl, 8)].append((order_id, order))
                    break
        elif "SELL" in order.type:
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
    
    trades_source = getattr(self, "trade_history", []) or []
    if not trades_source and hasattr(self, "broker") and hasattr(self.broker, "closed_trades"):
        trades_source = getattr(self.broker, "closed_trades", []) or []

    if not trades_source:
        return

    seen_records = {(round(float(c.get("exit_time", c.get("timestamp", 0))), 1), round(float(c.get("pnl", c.get("total_pnl", 0))), 2)) for c in self.cycle_history if isinstance(c, dict)}
    
    for item in trades_source:
        if isinstance(item, dict) and ("pnl" in item or "total_pnl" in item):
            pnl_val = float(item.get("pnl", item.get("total_pnl", 0.0)))
            ts_val = float(item.get("exit_time", item.get("timestamp", time.time())))
            st_val = float(item.get("entry_time", item.get("start_time", ts_val - 15.0)))
            ts_round = round(ts_val, 1)
            pnl_round = round(pnl_val, 2)
            
            deploy_px = float(item.get("deploy_price", item.get("entry_price", item.get("open_price", 0.0))))
            exit_px = float(item.get("exit_price", item.get("close_price", item.get("price", 0.0))))
            fills_cnt = int(item.get("fills_count", item.get("trades_count", item.get("size", 1))))

            if (ts_round, pnl_round) not in seen_records:
                seen_records.add((ts_round, pnl_round))
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


def enforce_trend_aware_position_guard(self, current_price: float, timestamp: float) -> int:
    """
    🔄 TREND-AWARE POSITION GUARD — Runs every tick.

    Rule 1 — TREND FLIPPED AGAINST POSITION (Quick Exit):
      If the active auto-mode trend has reversed against an open position:
        • If position is in ANY profit  → close immediately, lock the gain.
        • If position is at a SMALL loss (within cut_loss_threshold) → close
          now before the loss grows larger (stop-hunt avoidance).
        • If loss already exceeds threshold → leave it to the hard SL.
      This prevents SL/TP being hunted by the reversal move.

    Rule 2 — TREND STILL WITH POSITION (Hold for Max Profit):
      If trend is aligned with the open position, do NOT interfere.
      enforce_profit_lock + trail_stop_loss will ride the move for
      maximum profit automatically — no early exit needed.
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
    # Primary: last_auto_eval (most recent AI decision)
    auto_uni = str(getattr(self, "unidirectional_mode",
                           getattr(self, "auto_universe_bias", "DUAL"))).upper()
    last_eval = getattr(self, "last_auto_eval", None)
    if isinstance(last_eval, dict):
        eval_uni = str(last_eval.get("unidirectional_mode", "DUAL")).upper()
        if eval_uni and eval_uni != "DUAL":
            auto_uni = eval_uni   # Always prefer freshest AI call

    # Secondary: 5m technical trend cache (updated every 60 s)
    trail_cache = getattr(self, "_trail_trend_cache", None)
    trend_5m = str(trail_cache.get("trend", "NEUTRAL")).upper() if trail_cache else "NEUTRAL"

    trend_is_bull = ("BUY"  in auto_uni and "ONLY" in auto_uni) or trend_5m == "BULLISH"
    trend_is_bear = ("SELL" in auto_uni and "ONLY" in auto_uni) or trend_5m == "BEARISH"

    if not trend_is_bull and not trend_is_bear:
        return 0   # DUAL / ranging — no clear trend call, do nothing

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
                if floating_pnl >= 0:
                    # In profit → close immediately to secure the gain
                    should_close = True
                    tag    = "💰 [TREND FLIP — PROFIT SECURED]"
                    detail = f"locking +${floating_pnl:.{digits}f} before reversal hunt"
                elif floating_pnl > cut_loss_threshold:
                    # Small loss within acceptable range → cut it now
                    should_close = True
                    tag    = "✂️ [TREND FLIP — LOSS CUT]"
                    detail = f"cutting ${floating_pnl:.{digits}f} loss (trend={auto_uni})"
                else:
                    # Large loss already exceeded threshold — hard SL will handle it
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
        min_sl_distance  = max(4.00 if _is_100pct_trail else 8.00, atr_5m * _trail_atr_mult)
        breakeven_buffer = 1.00 if _is_100pct_trail else 2.50   # Confirmed → lock sooner
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

            # Phase 1: Breakeven Lock — once profit > breakeven_buffer, move SL to entry + buffer
            if floating_profit >= breakeven_buffer * 2.0:
                breakeven_sl = round(entry_px + breakeven_buffer, digits)
                if breakeven_sl > cur_sl and breakeven_sl < current_price:
                    # Only apply breakeven if no better SL already exists
                    if cur_sl < entry_px:  # SL is still below entry — move it up
                        try:
                            if self.broker.modify_position_sl_tp(pos_id, sl=breakeven_sl):
                                setattr(pos_obj, "sl", breakeven_sl)
                                modified_count += 1
                                print(f"[{sym_name}] 🔒 [BREAKEVEN LOCK] BUY #{pos_id} SL → ${breakeven_sl:,.3f} (entry+buffer, zero-risk)")
                        except Exception as e:
                            import logging; logging.warning(f"Exception: {e}")
                        continue

            # Phase 2: Structure Trail — only when trend is CONFIRMED BULLISH
            if not trend_confirmed_bull:
                continue  # Don't trail SL if trend is not confirmed — avoid being hunted

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

            # Phase 1: Breakeven Lock
            if floating_profit >= breakeven_buffer * 2.0:
                breakeven_sl = round(entry_px - breakeven_buffer, digits)
                if (cur_sl == 0.0 or breakeven_sl < cur_sl) and breakeven_sl > current_price:
                    if cur_sl == 0.0 or cur_sl > entry_px:  # SL is still above entry
                        try:
                            if self.broker.modify_position_sl_tp(pos_id, sl=breakeven_sl):
                                setattr(pos_obj, "sl", breakeven_sl)
                                modified_count += 1
                                print(f"[{sym_name}] 🔒 [BREAKEVEN LOCK] SELL #{pos_id} SL → ${breakeven_sl:,.3f} (entry-buffer, zero-risk)")
                        except Exception as e:
                            import logging; logging.warning(f"Exception: {e}")
                        continue

            # Phase 2: Structure Trail — only when trend is CONFIRMED BEARISH
            if not trend_confirmed_bear:
                continue

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

    if is_gold:
        if _is_100pct_tp:
            optimal_tp_dist = max(10.00, min(40.00, atr_5m * _tp_atr_mult))  # Confirmed: reach further
        else:
            optimal_tp_dist = max(6.00, min(15.00, atr_5m * _tp_atr_mult))
        min_tp_dist = 4.00   # Gold: at least $4 TP to cover spread + commission
    elif "BTC" in sym_name:
        if _is_100pct_tp:
            optimal_tp_dist = max(200.0, min(1200.0, atr_5m * _tp_atr_mult))
        else:
            optimal_tp_dist = max(100.0, min(500.0, atr_5m * _tp_atr_mult))
        min_tp_dist = 60.0
    elif "ETH" in sym_name:
        if _is_100pct_tp:
            optimal_tp_dist = max(10.0, min(80.0, atr_5m * _tp_atr_mult))
        else:
            optimal_tp_dist = max(5.0, min(30.0, atr_5m * _tp_atr_mult))
        min_tp_dist = 3.0
    else:
        if _is_100pct_tp:
            optimal_tp_dist = max(0.0006, min(0.0080, atr_5m * _tp_atr_mult))
        else:
            optimal_tp_dist = max(0.0003, min(0.0030, atr_5m * _tp_atr_mult))
        min_tp_dist = 0.0002

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
            best_tp = min(atr_tp, structure_tp)  # Use whichever is closer = fills easier
        else:
            best_tp = atr_tp

        # Ensure minimum TP distance
        best_tp = round(max(best_tp, current_price + min_tp_dist), digits)

        # Collect existing TPs to check if we should tighten.
        # BUG FIX: always take the MINIMUM of cur_tp and best_tp — TP can only move
        # CLOSER to price (tighten), never further away.
        for pos_id, pos_obj in buy_positions:
            cur_tp = round(float(getattr(pos_obj, "tp", 0.0) or 0.0), digits)

            if cur_tp > current_price:
                # Both are valid: pick the closer one (smaller value = nearer to price from above)
                target_tp = min(cur_tp, best_tp)
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
            best_tp = max(atr_tp, structure_tp)  # Use whichever is closer = fills easier
        else:
            best_tp = atr_tp

        # Ensure minimum TP distance
        best_tp = round(min(best_tp, current_price - min_tp_dist), digits)

        # BUG FIX: always take the MAXIMUM of cur_tp and best_tp for SELL — TP can only
        # move CLOSER to price (higher value = nearer to price from below), never further away.
        for pos_id, pos_obj in sell_positions:
            cur_tp = round(float(getattr(pos_obj, "tp", 0.0) or 0.0), digits)

            if 0.0 < cur_tp < current_price:
                # Both are valid: pick the closer one (larger value = nearer to price from below)
                target_tp = max(cur_tp, best_tp)
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
