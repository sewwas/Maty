import time
from typing import Dict, List, Optional, Any, Tuple

PAIR_PRIORITY_REGISTRY = [
    ("PAXGUSDT",  "GOLD",  True,          5,          0.05,         0.02,            0.01,    0.07),
    ("XAUUSD",    "GOLD",  True,          5,          0.05,         0.02,            0.01,    0.07),
    ("EURUSD",    "MAJOR", False,         5,          0.04,         0.02,            0.02,    1.00),
    ("USDJPY",    "MAJOR", False,         5,          0.04,         0.02,            0.02,    1.00),
    ("GBPUSD",    "MINOR", False,         3,          0.04,         0.02,            0.02,    0.50),
    ("BTCUSDT",   "MAJOR", False,         4,          0.06,         0.02,            0.004,   0.05),
    ("BTCUSD",    "MAJOR", False,         4,          0.06,         0.02,            0.004,   0.05),
    ("ETHUSDT",   "MINOR", False,         3,          0.05,         0.02,            0.15,    0.50),
    ("ETHUSD",    "MINOR", False,         3,          0.05,         0.02,            0.15,    0.50),
    ("SOLUSDT",   "ALT",   False,         2,          0.05,         0.02,            1.50,    3.00),
    ("BNBUSDT",   "ALT",   False,         2,          0.05,         0.02,            0.20,    0.50),
    ("DOGEUSDT",  "ALT",   False,         2,          0.04,         0.02,            10.0,    50.0),
]

_ORDERS_PER_SLOT = {"GOLD": 5, "MAJOR": 5, "MINOR": 3, "ALT": 2}

PAIR_SWEET_SPOTS = {
    "XAUUSD":   {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 0.01,   "min_tp": 3.50, "lot_mult": 1.25},
    "PAXGUSDT": {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 0.01,   "min_tp": 3.50, "lot_mult": 1.25},
    "GOLD":     {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 0.01,   "min_tp": 3.50, "lot_mult": 1.25},
    "BTCUSD":   {"quiet_gap": 0.06, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.004,  "min_tp": 3.50, "lot_mult": 1.25},
    "BTCUSDT":  {"quiet_gap": 0.06, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.004,  "min_tp": 3.50, "lot_mult": 1.25},
    "ETHUSD":   {"quiet_gap": 0.06, "std_gap": 0.08, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.15,   "min_tp": 3.50, "lot_mult": 1.25},
    "ETHUSDT":  {"quiet_gap": 0.06, "std_gap": 0.08, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.15,   "min_tp": 3.50, "lot_mult": 1.25},
    "SOLUSD":   {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 1.50,   "min_tp": 3.00, "lot_mult": 1.25},
    "SOLUSDT":  {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 1.50,   "min_tp": 3.00, "lot_mult": 1.25},
    "BNBUSD":   {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 0.20,   "min_tp": 3.00, "lot_mult": 1.25},
    "BNBUSDT":  {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 0.20,   "min_tp": 3.00, "lot_mult": 1.25},
    "DOGEUSD":  {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 1000.0, "min_tp": 2.50, "lot_mult": 1.25},
    "DOGEUSDT": {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 1000.0, "min_tp": 2.50, "lot_mult": 1.25},
    "XRPUSD":   {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 100.0,  "min_tp": 2.50, "lot_mult": 1.25},
    "XRPUSDT":  {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.02, "std_offset": 0.05, "base_lot": 100.0,  "min_tp": 2.50, "lot_mult": 1.25},
    "GBPUSD":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.02, "std_offset": 0.04, "base_lot": 0.05,   "min_tp": 1.50, "lot_mult": 1.25},
    "EURUSD":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.02, "std_offset": 0.04, "base_lot": 0.05,   "min_tp": 1.50, "lot_mult": 1.25},
    "USDJPY":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.02, "std_offset": 0.04, "base_lot": 0.05,   "min_tp": 1.50, "lot_mult": 1.25},
}


def clamp_symbol_lot_size(symbol: str, raw_size: float) -> float:
    """Clamps lot size strictly according to symbol category limits."""
    clean_sym = symbol.upper()
    if any(x in clean_sym for x in ["PAXG", "XAU", "GOLD"]):
        return min(0.03, max(0.01, round(raw_size, 2)))
    elif any(x in clean_sym for x in ["BTC"]):
        return min(0.05, max(0.01, round(raw_size, 3)))
    elif any(x in clean_sym for x in ["ETH"]):
        return min(0.50, max(0.10, round(raw_size, 2)))
    elif any(x in clean_sym for x in ["SOL"]):
        return min(3.00, max(0.10, round(raw_size, 2)))
    elif any(x in clean_sym for x in ["BNB"]):
        return min(0.50, max(0.05, round(raw_size, 2)))
    elif any(x in clean_sym for x in ["DOGE"]):
        return min(1000.0, max(10.0, round(raw_size, 1)))
    elif any(x in clean_sym for x in ["GBP", "EUR", "JPY"]):
        return min(0.20, max(0.01, round(raw_size, 2)))
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
        tech = dict(tech_indicators) if tech_indicators else {}
        ob = dict(orderbook_depth) if orderbook_depth else {}
        news = list(macro_news) if macro_news else []

        if not tech:
            try:
                from core.data import get_historical_klines, calculate_technical_indicators
                df_klines = get_historical_klines(symbol, interval="1m", limit=100)
                if df_klines is not None and not df_klines.empty:
                    tech = calculate_technical_indicators(df_klines) or {}
            except Exception:
                pass

        if not ob:
            try:
                from core.data import get_order_book_depth
                ob = get_order_book_depth(symbol) or {}
            except Exception:
                pass

        if not news:
            try:
                from core.data import get_economic_calendar
                news = get_economic_calendar() or []
            except Exception:
                pass

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
        combined_bias = (
            0.40 * ema_bias
            + 0.25 * htf_macro_bias
            + 0.20 * vwap_bias
            + 0.10 * ob_delta
            + 0.05 * rsi_signal
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
            is_overbought_rally = (rsi >= 65.0 or vwap_dev >= 0.25)
            is_oversold_dip = (rsi <= 35.0 or vwap_dev <= -0.25)
            
            if adx >= 35.0 and not (rsi >= 75.0 or rsi <= 25.0):
                if combined_bias >= 0.20:
                    unidirectional_mode = "BUY_ONLY"
                elif combined_bias <= -0.20:
                    unidirectional_mode = "SELL_ONLY"
                else:
                    unidirectional_mode = "DUAL"
            elif is_overbought_rally and combined_bias < 0.30:
                top_bottom_status = "RALLY_SELL_OVERBOUGHT"
                unidirectional_mode = "SELL_ONLY"
            elif is_oversold_dip and combined_bias > -0.30:
                top_bottom_status = "DIP_BUY_OVERSOLD"
                unidirectional_mode = "BUY_ONLY"
            elif combined_bias >= 0.20:
                unidirectional_mode = "BUY_ONLY"
            elif combined_bias <= -0.20:
                unidirectional_mode = "SELL_ONLY"
            else:
                unidirectional_mode = "DUAL"

        now_ts = time.time()
        news_risk_mult = 1.0
        for ev in news:
            if ev.get("impact") == "HIGH":
                ev_ts = float(ev.get("timestamp", 0))
                if abs(ev_ts - now_ts) <= 900:
                    news_risk_mult = 2.5
                    break

        gap_session_mult, size_session_mult, session_name = self._get_session_multiplier()
        confidence = self._confidence_score(ema_bias, ob_delta, vwap_bias, rsi, regime)

        sym_u = (symbol or "").upper()
        clean_sym = sym_u
        for s_token in PAIR_SWEET_SPOTS.keys():
            if s_token in sym_u:
                clean_sym = s_token
                break

        pair_config = PAIR_SWEET_SPOTS.get(clean_sym, {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.01, "min_tp": 3.00, "lot_mult": 1.25})

        equity_ratio = max(0.10, account_equity / 1000.0)
        capital_tier = f"${account_equity:,.0f} Dynamic Tier"
        raw_base_size = pair_config["base_lot"] * equity_ratio
        
        base_size = clamp_symbol_lot_size(clean_sym, raw_base_size)

        base_target_profit = max(1.50, round(4.50 * equity_ratio, 2))
        stop_loss = max(25.0, round(account_equity * 0.10, 2))
        lot_multiplier = 1.25
        max_levels = 10

        base_gap = 0.05
        base_offset = 0.02

        if regime == "RANGING":
            regime_gap_mult = 0.65
        elif regime == "TRENDING":
            regime_gap_mult = 0.90
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
        min_gap_val = pair_config["quiet_gap"] if is_quiet_market else pair_config["std_gap"]
        min_offset_val = pair_config["quiet_offset"] if is_quiet_market else pair_config["std_offset"]

        dynamic_gap = max(min_gap_val * profile_gap_mult, dynamic_gap)
        buy_offset = max(min_offset_val * profile_offset_mult, buy_offset)
        sell_offset = buy_offset
        lot_multiplier = pair_config.get("lot_mult", 1.25)
        base_target_profit = pair_config.get("min_tp", 3.00)

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
            except Exception:
                pass

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
        except Exception:
            pass

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
            "recommended_levels": max_levels,
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
            "buy_liquidity":     smc_result.get("buy_liquidity",  0.0),
            "sell_liquidity":    smc_result.get("sell_liquidity", 0.0),
        }
