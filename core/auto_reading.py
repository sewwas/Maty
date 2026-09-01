import time
from typing import Dict, List, Optional, Any, Tuple

PAIR_PRIORITY_REGISTRY = [
    ("PAXGUSDT",  "GOLD",  True,          5,          0.05,         0.02,            0.01,    0.07),
    ("XAUUSD",    "GOLD",  True,          5,          0.05,         0.02,            0.01,    0.07),
]

_ORDERS_PER_SLOT = {"GOLD": 5, "MAJOR": 5, "MINOR": 3, "ALT": 2}

# Hybrid safety bounds: live ATR drives the actual values; these are hard floor/ceiling guards.
# To add a new symbol just add a row here — no gap/offset tuning needed, ATR handles it.
PAIR_SAFETY_BOUNDS = {
    "XAUUSD":   {"min_gap": 0.03, "max_gap": 0.80,  "min_offset": 0.03, "max_offset": 0.60,  "min_tp": 3.00, "max_tp":  40.0, "base_lot": 0.01, "std_gap": 0.07, "std_offset": 0.07, "lot_mult": 1.25},
    "PAXGUSDT": {"min_gap": 0.03, "max_gap": 0.80,  "min_offset": 0.03, "max_offset": 0.60,  "min_tp": 3.00, "max_tp":  40.0, "base_lot": 0.01, "std_gap": 0.07, "std_offset": 0.07, "lot_mult": 1.25},
    "GOLD":     {"min_gap": 0.03, "max_gap": 0.80,  "min_offset": 0.03, "max_offset": 0.60,  "min_tp": 3.00, "max_tp":  40.0, "base_lot": 0.01, "std_gap": 0.07, "std_offset": 0.07, "lot_mult": 1.25},
    "ETHUSDT":  {"min_gap": 0.5,  "max_gap": 3.0,  "min_offset": 0.5,  "max_offset": 25.0,  "min_tp": 2.00, "max_tp":  60.0, "base_lot": 0.15,  "std_gap": 0.10, "std_offset": 0.08, "lot_mult": 1.25},
}
_DEFAULT_SAFETY_BOUNDS = {"min_gap": 0.03, "max_gap": 2.0, "min_offset": 0.03, "max_offset": 1.50, "min_tp": 2.00, "max_tp": 80.0, "base_lot": 0.01}


def clamp_symbol_lot_size(symbol: str, raw_size: float) -> float:
    """Clamps lot size strictly according to symbol category limits."""
    clean_sym = symbol.upper()
    if any(x in clean_sym for x in ["PAXG", "XAU", "GOLD"]):
        return min(0.03, max(0.01, round(raw_size, 2)))
    else:
        return max(0.01, round(raw_size, 2))


def select_active_pairs(
    total_account_orders: int = 0,
    account_max_orders: int = 100,
    regime_scores: dict = None,
    active_symbols: list = None
) -> list:
    if regime_scores is None:
        regime_scores = {}
    if active_symbols is None:
        active_symbols = [p[0] for p in PAIR_PRIORITY_REGISTRY]

    safe_order_budget = int(account_max_orders * 0.85) - total_account_orders
    if safe_order_budget <= 0:
        return [p[0] for p in PAIR_PRIORITY_REGISTRY if p[2] and p[0] in active_symbols]

    selected = []
    budget_used = 0

    for sym, tier, is_gold, max_lvl, *_ in PAIR_PRIORITY_REGISTRY:
        if is_gold and sym in active_symbols:
            slot_cost = _ORDERS_PER_SLOT.get(tier, 3)
            if budget_used + slot_cost <= safe_order_budget:
                selected.append(sym)
                budget_used += slot_cost

    non_gold = [
        (sym, tier, max_lvl)
        for sym, tier, is_gold, max_lvl, *_ in PAIR_PRIORITY_REGISTRY
        if not is_gold and sym in active_symbols and sym not in selected
    ]
    non_gold_scored = sorted(
        non_gold,
        key=lambda x: regime_scores.get(x[0], 50),
        reverse=True
    )
    for sym, tier, max_lvl in non_gold_scored:
        slot_cost = _ORDERS_PER_SLOT.get(tier, 3)
        if budget_used + slot_cost <= safe_order_budget:
            selected.append(sym)
            budget_used += slot_cost

    return selected


def get_pair_gold_params(symbol: str) -> dict:
    sym_u = symbol.upper()
    for sym, tier, is_gold, max_lvl, gap_pct, offset_pct, min_lot, max_lot in PAIR_PRIORITY_REGISTRY:
        if sym in sym_u or sym_u in sym:
            return {
                "tier":           tier,
                "is_gold":        is_gold,
                "max_levels":     max_lvl,
                "base_gap_pct":   gap_pct,
                "base_offset_pct": offset_pct,
                "min_lot":        min_lot,
                "max_lot":        max_lot,
                "slot_cost":      _ORDERS_PER_SLOT.get(tier, 3),
            }
    return {"tier": "ALT", "is_gold": False, "max_levels": 2,
            "base_gap_pct": 0.50, "base_offset_pct": 0.30,
            "min_lot": 0.01, "max_lot": 0.10, "slot_cost": 2}


def _compute_atr_derived_params(symbol: str, current_price: float, atr_pct: float, is_quiet: bool) -> dict:
    """Hybrid core: derive gap/offset/tp from live ATR, then clamp to per-symbol safety bounds.

    Quiet market  (RANGING / low ATR) → tighter values → faster entries & exits.
    Active market (TRENDING / high ATR) → wider values → protection from noise.
    """
    sym_u = symbol.upper()
    bounds = _DEFAULT_SAFETY_BOUNDS
    for token, b in PAIR_SAFETY_BOUNDS.items():
        if token in sym_u:
            bounds = b
            break

    # Convert ATR % to price units (e.g. 0.30% of $2700 gold = $8.10)
    atr_price = (atr_pct / 100.0) * max(current_price, 0.0001)

    # Quiet: tighter for fast execution. Active: wider for noise protection.
    gap_factor    = 0.12 if is_quiet else 0.20
    offset_factor = 0.10 if is_quiet else 0.16
    tp_factor     = 0.60 if is_quiet else 0.90

    raw_gap    = round(atr_price * gap_factor,    3)
    raw_offset = round(atr_price * offset_factor, 3)
    raw_tp     = round(atr_price * tp_factor,     2)

    return {
        "dynamic_gap":    max(bounds["min_gap"],    min(bounds["max_gap"],    raw_gap)),
        "dynamic_offset": max(bounds["min_offset"], min(bounds["max_offset"], raw_offset)),
        "dynamic_tp":     max(bounds["min_tp"],     min(bounds["max_tp"],     raw_tp)),
        "base_lot":       bounds["base_lot"],
    }


class AutoReadingEngine:
    """
    Enhanced Auto-Reading Autonomous Trap & Market Regime Engine v2.
    """
    _last_eval_bias: float = 0.0
    _last_eval_regime: str = "RANGING"
    _last_eval_ts: float = 0.0
    _REDEPLOY_COOLDOWN_SECS: float = 90.0
    _BIAS_SHIFT_THRESHOLD: float = 0.20

    def __init__(self):
        self._last_eval_bias = 0.0
        self._last_eval_regime = "RANGING"
        self._last_eval_ts = 0.0
        self._last_unidirectional_mode = "DUAL"
        self._last_unidirectional_ts = 0.0

    @staticmethod
    def _get_session_multiplier() -> tuple:
        utc_hour = time.gmtime().tm_hour
        if 23 <= utc_hour or utc_hour < 8:
            return 1.30, 0.80, "ASIAN"
        elif 8 <= utc_hour < 12:
            return 1.00, 1.10, "LONDON"
        elif 12 <= utc_hour < 17:
            return 0.85, 1.20, "NY_OVERLAP"
        elif 17 <= utc_hour < 20:
            return 0.95, 1.0, "NY"
        else:
            return 1.10, 0.90, "EVENING"

    @staticmethod
    def _detect_regime(ema_bias: float, rsi: float, atr_pct: float, bb_width_pct: float, ci: float = 50.0, adx: float = 20.0, mtf_conf: float = 50.0) -> str:
        if (rsi > 70 or rsi < 30) and (ci > 55.0 or bb_width_pct > 2.0):
            return "REVERSAL"
        if ci >= 58.0 or adx <= 20.0 or mtf_conf < 40.0:
            return "RANGING"
        if ci <= 45.0 and adx >= 24.0 and mtf_conf >= 70.0:
            return "TRENDING"
        if abs(ema_bias) >= 0.45 and atr_pct >= 0.20:
            return "TRENDING"
        return "RANGING"

    @staticmethod
    def _confidence_score(ema_bias: float, ob_delta: float, vwap_bias: float, rsi: float, regime: str) -> int:
        score = 50.0
        if abs(ema_bias) > 0.70: score += 20.0
        elif abs(ema_bias) > 0.40: score += 10.0
        if (ema_bias > 0 and ob_delta > 0.20) or (ema_bias < 0 and ob_delta < -0.20):
            score += 15.0
        if (ema_bias > 0 and vwap_bias > 0.10) or (ema_bias < 0 and vwap_bias < -0.10):
            score += 10.0
        if 40 <= rsi <= 60:
            score += 5.0
        if regime == "TRENDING": score += 5.0
        elif regime == "REVERSAL": score -= 10.0
        return int(max(0, min(100, score)))

    def should_redeploy(self, new_bias: float, new_regime: str) -> bool:
        now = time.time()
        if now - self._last_eval_ts < self._REDEPLOY_COOLDOWN_SECS:
            return False
        bias_shift = abs(new_bias - self._last_eval_bias)
        regime_changed = (new_regime != self._last_eval_regime)
        return bias_shift >= self._BIAS_SHIFT_THRESHOLD or regime_changed

    def evaluate_market_and_account(
        self,
        symbol: str,
        current_price: float,
        account_equity: float = 1000.0,
        tech_indicators: Optional[dict] = None,
        orderbook_depth: Optional[dict] = None,
        macro_news: Optional[List[dict]] = None,
        auto_profile: str = "BALANCED",
        pending_order_side_mode: str = "AUTO_ADAPTIVE"
    ) -> dict:
        gap_session_mult, size_session_mult, session_name = self._get_session_multiplier()
        tech = dict(tech_indicators) if tech_indicators else {}
        ob = dict(orderbook_depth) if orderbook_depth else {}
        news = list(macro_news) if macro_news else []

        if not tech:
            try:
                from core.data import get_historical_klines, calculate_technical_indicators, detect_fvg, detect_liquidity_sweep, detect_order_blocks
                df_klines = get_historical_klines(symbol, interval="3m", limit=100)
                if df_klines is not None and not df_klines.empty:
                    tech = calculate_technical_indicators(symbol) or {}
                    tech['fvg'] = detect_fvg(df_klines)
                    tech['sweep'] = detect_liquidity_sweep(df_klines)
                    tech['ob'] = detect_order_blocks(df_klines)
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        if not ob:
            try:
                from core.data import get_order_book_depth
                ob = get_order_book_depth(symbol) or {}
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        if not news:
            try:
                from core.data import get_economic_calendar
                news = get_economic_calendar() or []
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        current_price = max(0.0001, current_price)
        ema_bias = float(tech.get("ema_trend_bias", 0.0))
        rsi = float(tech.get("rsi", 50.0))
        raw_atr_pct = float(tech.get("atr_pct", 0.30))
        
        if not hasattr(self, "_smoothed_atr"):
            self._smoothed_atr = raw_atr_pct
        else:
            self._smoothed_atr = 0.70 * self._smoothed_atr + 0.30 * raw_atr_pct
        atr_pct = min(raw_atr_pct, self._smoothed_atr * 1.25)

        bb_width_pct = float(tech.get("bb_width_pct", 2.0))
        vwap_dev = float(tech.get("vwap_dev_pct", 0.0))
        vwap_bias = max(-1.0, min(1.0, vwap_dev / 0.50))

        buy_pct = float(ob.get("buy_pressure_pct", 50.0))
        ob_delta = (buy_pct - 50.0) / 50.0
        asks_list = ob.get("asks", [])
        bids_list = ob.get("bids", [])
        ask_vol = sum([float(s) for _, s in asks_list]) if asks_list else 0.0
        bid_vol = sum([float(s) for _, s in bids_list]) if bids_list else 0.0
        ob_ratio = round(ask_vol / bid_vol, 3) if bid_vol > 0 else 1.0

        ci = float(tech.get("choppiness_index", 50.0))
        adx = float(tech.get("adx", 20.0))
        mtf_conf = float(tech.get("mtf_confluence", 50.0))
        regime = tech.get("regime") if tech.get("regime") else self._detect_regime(ema_bias, rsi, atr_pct, bb_width_pct, ci, adx, mtf_conf)

        htf_macro_bias = float(tech.get("htf_macro_bias", ema_bias))
        rsi_signal = (rsi - 50.0) / 50.0
        fvg = tech.get('fvg', {})
        sweep = tech.get('sweep', {})
        ob = tech.get('ob', {})

        smc_bias = 0.0
        if fvg.get('type') == 'BULLISH_FVG': smc_bias += 0.3
        elif fvg.get('type') == 'BEARISH_FVG': smc_bias -= 0.3
        
        if sweep.get('type') == 'BULLISH_SWEEP': smc_bias += 0.4
        elif sweep.get('type') == 'BEARISH_SWEEP': smc_bias -= 0.4
        
        if ob.get('type') == 'BULLISH_OB': smc_bias += 0.2
        elif ob.get('type') == 'BEARISH_OB': smc_bias -= 0.2

        combined_bias = (
            0.30 * ema_bias
            + 0.20 * htf_macro_bias
            + 0.10 * vwap_bias
            + 0.10 * ob_delta
            + 0.05 * rsi_signal
            + 0.25 * smc_bias
        )

        if vwap_dev < -0.05 and ema_bias < 0.0:
            combined_bias = min(combined_bias, -0.20)
        elif vwap_dev > 0.05 and ema_bias > 0.0:
            combined_bias = max(combined_bias, 0.20)

        combined_bias = max(-1.0, min(1.0, combined_bias))

        vol_spike = float(tech.get("volume_spike_mult", 1.0))
        trend_score = 0
        if adx >= 25.0:           trend_score += 1
        if ci <= 48.0:            trend_score += 1
        if mtf_conf >= 70.0:      trend_score += 1
        if abs(ema_bias) >= 0.35: trend_score += 1
        if vol_spike >= 1.30:     trend_score += 1

        is_strong_trend = (trend_score >= 2)

        if is_strong_trend:
            is_top_peak = False
            is_bottom_trough = False
        else:
            is_top_peak = (rsi >= 72.0 or vwap_dev >= 0.50)
            is_bottom_trough = (rsi <= 28.0 or vwap_dev <= -0.50)

        top_bottom_status = "NORMAL"
        side_mode = str(pending_order_side_mode or "AUTO_ADAPTIVE").upper()

        if "BUY" in side_mode and "DIP" not in side_mode and "AUTO" not in side_mode:
            unidirectional_mode = "BUY_ONLY"
        elif "SELL" in side_mode and "RALLY" not in side_mode and "AUTO" not in side_mode:
            unidirectional_mode = "SELL_ONLY"
        elif "BOTH" in side_mode:
            unidirectional_mode = "DUAL"
        else:
            data_trend = str(tech.get("trend", "NEUTRAL")).upper()
            
            if is_strong_trend:
                is_overbought_rally = False
                is_oversold_dip = False
            else:
                is_overbought_rally = (rsi >= 70.0 or vwap_dev >= 0.35)
                is_oversold_dip = (rsi <= 30.0 or vwap_dev <= -0.35)
            
            # 1. 6-Indicator Weighted Trend (Top Priority)
            if data_trend == "BULLISH":
                unidirectional_mode = "BUY_ONLY"
            elif data_trend == "BEARISH":
                unidirectional_mode = "SELL_ONLY"
            # 2. ADX Trend Breakout (Allow extreme RSI to confirm momentum rather than block it)
            elif adx >= 35.0 or is_strong_trend:
                # In strong momentum, rely on EMA direction if bias is neutral
                if combined_bias >= 0.20 or (combined_bias > -0.15 and (ema_bias > 0.1 or data_trend == "BULLISH")):
                    unidirectional_mode = "BUY_ONLY"
                elif combined_bias <= -0.20 or (combined_bias < 0.15 and (ema_bias < -0.1 or data_trend == "BEARISH")):
                    unidirectional_mode = "SELL_ONLY"
                else:
                    unidirectional_mode = "DUAL"
            # 3. Mean Reversion (Overbought/Oversold)
            elif is_overbought_rally and combined_bias < 0.30:
                top_bottom_status = "RALLY_SELL_OVERBOUGHT"
                unidirectional_mode = "SELL_ONLY"
            elif is_oversold_dip and combined_bias > -0.30:
                top_bottom_status = "DIP_BUY_OVERSOLD"
                unidirectional_mode = "BUY_ONLY"
            # 4. Fallback to Combined Bias
            elif combined_bias >= 0.30:
                unidirectional_mode = "BUY_ONLY"
            elif combined_bias <= -0.30:
                unidirectional_mode = "SELL_ONLY"
            else:
                unidirectional_mode = "DUAL"
            # 5. SMART MONEY CONCEPTS (SMC) OVERRIDE - KILL ZONE FILTERED
            # DISABLED: User requested to stop fading breakouts (trading against momentum).
            # if not is_strong_trend:
            #     if session_name in ["LONDON", "NY", "NY_OVERLAP"]:
            #         if sweep.get('type') == 'BULLISH_SWEEP' or fvg.get('type') == 'BULLISH_FVG' or ob.get('type') == 'BULLISH_OB':
            #             unidirectional_mode = "BUY_ONLY"
            #             top_bottom_status = "SMC_BULLISH_TRAP"
            #         elif sweep.get('type') == 'BEARISH_SWEEP' or fvg.get('type') == 'BEARISH_FVG' or ob.get('type') == 'BEARISH_OB':
            #             unidirectional_mode = "SELL_ONLY"
            #             top_bottom_status = "SMC_BEARISH_TRAP"

        now_ts = time.time()
        
        # 6. Apply responsive trend confirmation with debouncing (switch after 2 verified ticks / 10s)
        if not hasattr(self, "_last_unidirectional_mode"):
            self._last_unidirectional_mode = unidirectional_mode
            self._last_unidirectional_ts = now_ts
            self._pending_unidirectional_mode = unidirectional_mode
            self._pending_unidirectional_count = 0
        else:
            if unidirectional_mode == self._last_unidirectional_mode:
                self._last_unidirectional_ts = now_ts  # Reset timer as long as trend continues
                self._pending_unidirectional_mode = unidirectional_mode
                self._pending_unidirectional_count = 0
            else:
                # Mode disagrees with locked mode.
                if unidirectional_mode == getattr(self, "_pending_unidirectional_mode", None):
                    self._pending_unidirectional_count += 1
                else:
                    self._pending_unidirectional_mode = unidirectional_mode
                    self._pending_unidirectional_count = 1

                # Responsive switch after 2 consecutive confirmed ticks (or 10s) — eliminates 3-minute lag
                if (now_ts - self._last_unidirectional_ts >= 10.0) or self._pending_unidirectional_count >= 2:
                    self._last_unidirectional_mode = unidirectional_mode
                    self._last_unidirectional_ts = now_ts
                    self._pending_unidirectional_count = 0
                else:
                    unidirectional_mode = self._last_unidirectional_mode

        news_risk_mult = 1.0
        for ev in news:
            if ev.get("impact") == "HIGH":
                ev_ts = float(ev.get("timestamp", 0))
                if abs(ev_ts - now_ts) <= 900:
                    news_risk_mult = 2.5
                    break

        # gap_session_mult and size_session_mult were extracted earlier for the SMC Kill Zone
        confidence = self._confidence_score(ema_bias, ob_delta, vwap_bias, rsi, regime)

        sym_u = (symbol or "").upper()
        clean_sym = sym_u
        for s_token in PAIR_SAFETY_BOUNDS.keys():
            if s_token in sym_u:
                clean_sym = s_token
                break

        # Resolve safety bounds for this symbol (used for base_lot + ATR clamping later)
        sym_bounds = PAIR_SAFETY_BOUNDS.get(clean_sym, _DEFAULT_SAFETY_BOUNDS)

        equity_ratio = max(0.10, account_equity / 1000.0)
        capital_tier = f"${account_equity:,.0f} Dynamic Tier"
        raw_base_size = sym_bounds["base_lot"] * equity_ratio

        base_size = clamp_symbol_lot_size(clean_sym, raw_base_size)

        base_target_profit = max(3.00, round(6.00 * equity_ratio, 2))
        stop_loss = max(15.0, round(account_equity * 0.05, 2))
        lot_multiplier = 1.0
        max_levels = 5
        if regime == "TRENDING":
            max_levels = 5
            lot_multiplier = 1.0
        elif regime == "RANGING":
            max_levels = 3
            lot_multiplier = 1.0
            
        if unidirectional_mode == "DUAL":
            max_levels = 1

        base_gap = 0.05
        base_offset = 0.02

        if regime == "RANGING":
            regime_gap_mult = 0.85
        else:
            regime_gap_mult = 1.20

        profile_mode = getattr(self, "auto_profile", "BALANCED").upper()
        if "SCALPING" in profile_mode:
            profile_offset_mult = 0.85
            profile_gap_mult = 0.85
        elif "INSTITUTIONAL" in profile_mode:
            profile_offset_mult = 1.40
            profile_gap_mult = 1.40
        else:
            profile_offset_mult = 1.00
            profile_gap_mult = 1.00

        symmetric_offset = round(base_offset * news_risk_mult * profile_offset_mult, 3)
        buy_offset = max(0.015, min(0.04, symmetric_offset))
        sell_offset = buy_offset

        bb_scale = max(0.5, min(2.0, bb_width_pct / 2.0))
        dynamic_gap = max(0.04, min(0.15, round(
            base_gap * bb_scale * regime_gap_mult * gap_session_mult * profile_gap_mult,
            3
        )))

        is_quiet_market = (regime == "RANGING" or atr_pct < 0.25)
        # Hybrid: ATR-derived values, clamped to per-symbol safety bounds
        atr_params = _compute_atr_derived_params(clean_sym, current_price, atr_pct, is_quiet_market)

        dynamic_gap        = max(atr_params["dynamic_gap"]    * profile_gap_mult,    dynamic_gap)
        buy_offset         = max(atr_params["dynamic_offset"] * profile_offset_mult, buy_offset)
        sell_offset        = buy_offset
        lot_multiplier     = 1.0
        base_target_profit = atr_params["dynamic_tp"]

        live_spread = tech.get("live_spread", 0.0)
        if live_spread > 0 and current_price > 0:
            spread_pct = (live_spread / current_price) * 100.0
            min_spread_offset = spread_pct * 1.8
            buy_offset = max(buy_offset, min_spread_offset)
            sell_offset = max(sell_offset, min_spread_offset)

        vol_tp_scale = max(0.5, min(3.0, atr_pct / 0.30))
        dynamic_target_profit = round(base_target_profit * vol_tp_scale * (gap_session_mult * 0.8 + 0.2), 2)

        if ob and "asks" in ob and len(ob["asks"]) > 0:
            try:
                top_ask = min([float(p) for p, _ in ob["asks"]])
                dist_pct = (top_ask - current_price) / current_price * 100.0
                if 0.10 < dist_pct < 2.0:
                    sr_tp = round(dist_pct * 0.85 * current_price * (base_size / 100.0), 2)
                    dynamic_target_profit = max(2.50, min(dynamic_target_profit, sr_tp))
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")

        conf_scale = (0.85 + 0.30 * (confidence / 100.0))
        raw_adj_size = base_size * conf_scale * size_session_mult
        adj_size = clamp_symbol_lot_size(clean_sym, raw_adj_size)

        if abs(combined_bias) >= 0.50:
            dynamic_target_profit = round(dynamic_target_profit * 1.35, 2)
            lot_multiplier = 1.35

        smc_result = {"smc_bias": "NEUTRAL", "smc_score": 50, "elliott_wave": 0,
                      "elliott_confidence": 0.0, "bos_direction": "NEUTRAL",
                      "bullish_ob": 0.0, "bearish_ob": 0.0,
                      "bullish_fvg_low": 0.0, "bullish_fvg_high": 0.0,
                      "bearish_fvg_low": 0.0, "bearish_fvg_high": 0.0,
                      "buy_liquidity": 0.0, "sell_liquidity": 0.0}
        try:
            from core.data import calculate_smc_elliott, get_historical_klines
            _smc_df = tech.get("_klines_df", None)
            if _smc_df is None:
                _smc_df = get_historical_klines(symbol, interval="1m", limit=100)
            if _smc_df is not None:
                smc_result = calculate_smc_elliott(_smc_df)
                smc_bias = smc_result.get("smc_bias", "NEUTRAL")
                if smc_bias == "BULLISH" and combined_bias > 0:
                    combined_bias = min(1.0, combined_bias + 0.15)
                elif smc_bias == "BEARISH" and combined_bias < 0:
                    combined_bias = max(-1.0, combined_bias - 0.15)
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")

        self._last_eval_bias = combined_bias
        self._last_eval_regime = regime
        self._last_eval_ts = now_ts

        return {
            "market_regime": regime,
            "session_name": session_name,
            "top_bottom_status": top_bottom_status,
            "unidirectional_mode": unidirectional_mode,
            "capital_tier": capital_tier,
            "confidence_score": confidence,
            "combined_bias": round(combined_bias, 3),
            "ema_trend_bias": round(ema_bias, 3),
            "htf_macro_bias": round(htf_macro_bias, 3),
            "mtf_confluence": mtf_conf,
            "vwap_dev_pct": vwap_dev,
            "ob_delta": round(ob_delta, 3),
            "rsi": rsi,
            "choppiness_index": float(tech.get("choppiness_index", 50.0)),
            "adx": float(tech.get("adx", 20.0)),
            "news_risk_mult": news_risk_mult,
            "buy_offset_pct": buy_offset,
            "sell_offset_pct": sell_offset,
            "dynamic_gap_pct": dynamic_gap,
            "recommended_size": round(adj_size, 6),
            "recommended_multiplier": lot_multiplier,
            "recommended_levels": min(max_levels, 10),  # Hard safety cap — never exceed 10 levels regardless of market signals
            "recommended_stop_loss": round(stop_loss, 2),
            "recommended_target_profit": dynamic_target_profit,
            "smc_bias":          smc_result.get("smc_bias", "NEUTRAL"),
            "smc_score":         smc_result.get("smc_score", 50),
            "elliott_wave":      smc_result.get("elliott_wave", 0),
            "elliott_confidence":smc_result.get("elliott_confidence", 0.0),
            "bos_direction":     smc_result.get("bos_direction", "NEUTRAL"),
            "bullish_ob":        smc_result.get("bullish_ob", 0.0),
            "bearish_ob":        smc_result.get("bearish_ob", 0.0),
            "bullish_fvg_low":   smc_result.get("bullish_fvg_low",  0.0),
            "bullish_fvg_high":  smc_result.get("bullish_fvg_high", 0.0),
            "bearish_fvg_low":   smc_result.get("bearish_fvg_low",  0.0),
            "bearish_fvg_high":  smc_result.get("bearish_fvg_high", 0.0),
            "sell_liquidity":    smc_result.get("sell_liquidity", 0.0),
            "recent_fvg":        tech.get("fvg", {}).get("type", "NONE"),
            "recent_sweep":      tech.get("sweep", {}).get("type", "NONE"),
            "recent_ob":         tech.get("ob", {}).get("type", "NONE"),
        }
