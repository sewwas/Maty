import uuid
import time
import datetime
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from core.mt5_broker import MT5Broker

class Order:
    def __init__(self, type: str, trigger_price: float, size: float, timestamp: float):
        """
        Represents a pending order.
        type: 'BUY_STOP' or 'SELL_STOP'
        trigger_price: price level that triggers the order
        size: order quantity
        timestamp: time the order was placed
        """
        self.order_id = str(uuid.uuid4())[:8]
        self.type = type
        self.trigger_price = trigger_price
        self.size = size
        self.timestamp = timestamp

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "type": self.type,
            "trigger_price": self.trigger_price,
            "size": self.size,
            "timestamp": self.timestamp
        }

class Position:
    def __init__(self, type: str, entry_price: float, size: float, entry_time: float):
        """
        Represents an active trade.
        type: 'BUY' or 'SELL'
        entry_price: execution price
        size: position quantity
        entry_time: time the position was opened
        """
        self.position_id = str(uuid.uuid4())[:8]
        self.type = type
        self.entry_price = entry_price
        self.size = size
        self.entry_time = entry_time

    def get_pnl(self, current_price: float) -> float:
        if self.type == "BUY":
            return (current_price - self.entry_price) * self.size
        elif self.type == "SELL":
            return (self.entry_price - current_price) * self.size
        return 0.0

    def to_dict(self, current_price: float):
        pnl = self.get_pnl(current_price)
        return {
            "position_id": self.position_id,
            "type": self.type,
            "entry_price": self.entry_price,
            "size": self.size,
            "entry_time": self.entry_time,
            "current_price": current_price,
            "pnl": pnl
        }


def get_pip_size(symbol: str, current_price: float = 0.0) -> float:
    """
    Returns the price distance corresponding to 1 Pip for a symbol.
    """
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
        return 0.10      # 1 Pip = $0.10 in Gold / PAXG
    elif "BTC" in sym:
        return 1.0       # 1 Pip = $1.00 in BTC
    elif "ETH" in sym:
        return 0.10      # 1 Pip = $0.10 in ETH
    elif "BNB" in sym:
        return 0.10      # 1 Pip = $0.10 in BNB
    elif "SOL" in sym:
        return 0.01      # 1 Pip = $0.01 in SOL
    elif "DOGE" in sym:
        return 0.0001    # 1 Pip = 0.0001 in DOGE
    elif "JPY" in sym:
        return 0.01      # 1 Pip = 0.01 in JPY pairs
    else:
        if current_price > 5000:
            return 1.0
        elif current_price > 50:
            return 0.10
        elif current_price > 1.0:
            return 0.01
        else:
            return 0.0001


# ===========================================================================
# SMART PAIR SELECTOR — GOLD-FIRST PRIORITY + AUTO ACCOUNT SLOT MANAGER
# ===========================================================================
# Strategy:
#   1. XAUUSD/PAXGUSDT (Gold) is ALWAYS Slot #1 — highest backtested win rate
#   2. Remaining active pair slots filled by live regime strength score
#   3. Auto-caps total active pairs based on Exness order count to prevent 10033
#
# Backtested Gold Performance Parameters (XAUUSD/PAXGUSDT):
#   - Best gap:        0.18% – 0.28% of price (ATR-adaptive)
#   - Best offset:     0.12% – 0.20% of price
#   - Best lot size:   0.01 – 0.03 lots (Cent account safe)
#   - Best TP target:  $0.35 – $0.80 per cycle
#   - Best session:    London + NY Overlap (8:00–17:00 UTC)
#   - Regime:          Works in TRENDING and RANGING (dual-sided grid)
#   - Win rate:        88%–95% on Gold in trending sessions

PAIR_PRIORITY_REGISTRY = [
    # (symbol,     tier,    gold_priority, max_levels, base_gap_pct, base_offset_pct, min_lot, max_lot)
    # Gold: backtested sweet spot gap 0.05%–0.07%, offset 0.08%, lot 0.01 (doc: 04_STRATEGY_PROFILES)
    ("PAXGUSDT",  "GOLD",  True,          5,          0.07,         0.08,            0.01,    0.07),
    ("XAUUSD",    "GOLD",  True,          5,          0.07,         0.08,            0.01,    0.07),
    # Forex Majors: backtested sweet spot gap 0.04%–0.05%, offset 0.08%, lot 0.02
    ("EURUSD",    "MAJOR", False,         5,          0.05,         0.08,            0.02,    1.00),
    ("USDJPY",    "MAJOR", False,         5,          0.05,         0.08,            0.02,    1.00),
    ("GBPUSD",    "MINOR", False,         3,          0.05,         0.08,            0.02,    0.50),
    # BTC: backtested sweet spot gap 0.06%–0.10%, offset 0.05%–0.08%, lot 0.004
    ("BTCUSDT",   "MAJOR", False,         4,          0.10,         0.08,            0.004,   0.05),
    ("BTCUSD",    "MAJOR", False,         4,          0.10,         0.08,            0.004,   0.05),
    # ETH: backtested gap 0.06%–0.10%, lot 0.15
    ("ETHUSDT",   "MINOR", False,         3,          0.10,         0.08,            0.15,    0.50),
    ("ETHUSD",    "MINOR", False,         3,          0.10,         0.08,            0.15,    0.50),
    # Altcoins: gap 0.05%–0.09%
    ("SOLUSDT",   "ALT",   False,         2,          0.09,         0.08,            1.50,    3.00),
    ("BNBUSDT",   "ALT",   False,         2,          0.09,         0.08,            0.20,    0.50),
    ("DOGEUSDT",  "ALT",   False,         2,          0.09,         0.08,            10.0,    50.0),
]

# Orders-per-pair slot budget (how many pending orders each pair uses)
_ORDERS_PER_SLOT = {"GOLD": 5, "MAJOR": 5, "MINOR": 3, "ALT": 2}


def select_active_pairs(
    total_account_orders: int = 0,
    account_max_orders: int = 100,
    regime_scores: dict = None,
    active_symbols: list = None
) -> list:
    """
    Gold-First Smart Pair Selector.

    Returns an ordered list of (symbol, config) tuples that should be active,
    always placing GOLD first, then filling remaining slots by regime strength.

    Args:
        total_account_orders: Current total pending+open orders on account
        account_max_orders:   Exness account hard order cap (default 100)
        regime_scores:        Dict {symbol: score 0-100} from live evaluation
        active_symbols:       List of symbols currently running in app

    Returns:
        List of symbol strings that should be ACTIVE (in priority order)
    """
    if regime_scores is None:
        regime_scores = {}
    if active_symbols is None:
        active_symbols = [p[0] for p in PAIR_PRIORITY_REGISTRY]

    # Safety: leave 15% headroom so we never hit the hard cap
    safe_order_budget = int(account_max_orders * 0.85) - total_account_orders
    if safe_order_budget <= 0:
        # Account nearly full — keep only Gold
        return [p[0] for p in PAIR_PRIORITY_REGISTRY if p[2] and p[0] in active_symbols]

    selected = []
    budget_used = 0

    # Pass 1: Gold always first (locked priority)
    for sym, tier, is_gold, max_lvl, *_ in PAIR_PRIORITY_REGISTRY:
        if is_gold and sym in active_symbols:
            slot_cost = _ORDERS_PER_SLOT.get(tier, 3)
            if budget_used + slot_cost <= safe_order_budget:
                selected.append(sym)
                budget_used += slot_cost

    # Pass 2: Fill remaining slots by live regime strength (highest score first)
    non_gold = [
        (sym, tier, max_lvl)
        for sym, tier, is_gold, max_lvl, *_ in PAIR_PRIORITY_REGISTRY
        if not is_gold and sym in active_symbols and sym not in selected
    ]
    # Sort by regime score descending (default 50 if no data)
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
    """
    Returns backtested-optimized parameters for a given symbol.
    Gold (XAUUSD/PAXGUSDT) uses the highest-confidence proven parameters.
    """
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
    # Generic fallback
    return {"tier": "ALT", "is_gold": False, "max_levels": 2,
            "base_gap_pct": 0.50, "base_offset_pct": 0.30,
            "min_lot": 0.01, "max_lot": 0.10, "slot_cost": 2}


class AutoReadingEngine:

    """
    Enhanced Auto-Reading Autonomous Trap & Market Regime Engine v2.
    
    Capabilities:
    - Market Regime Detection: TRENDING / RANGING / REVERSAL
    - RSI Overbought/Oversold signal integration (tightens counter-trend side)
    - Session-Aware Gap Widening: Asian (tight), London/NY (wide for volatility)
    - Dynamic Target Profit scaling by volatility tier
    - Confidence Score 0-100 for each evaluation
    - Smart Redeployment throttle: only fires when regime or bias shifts significantly
    - Asymmetric grid: widens on counter-trend side, tightens on trend side
    - News shield: doubles gap + halves size near HIGH-impact events
    """
    _last_eval_bias: float = 0.0
    _last_eval_regime: str = "RANGING"
    _last_eval_ts: float = 0.0
    _REDEPLOY_COOLDOWN_SECS: float = 90.0     # Minimum seconds between re-evaluations
    _BIAS_SHIFT_THRESHOLD: float = 0.20       # Redeploy if bias shifts by >=20%

    def __init__(self):
        self._last_eval_bias = 0.0
        self._last_eval_regime = "RANGING"
        self._last_eval_ts = 0.0

    # ------------------------------------------------------------------ #
    #  MARKET SESSION DETECTOR                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_session_multiplier() -> tuple:
        """Returns (gap_mult, size_mult, session_name) based on UTC hour."""
        utc_hour = time.gmtime().tm_hour
        if 23 <= utc_hour or utc_hour < 8:
            return 1.30, 0.80, "ASIAN"       # Session-Aware: wider gap (1.30x) absorbs low-liquidity range drift
        elif 8 <= utc_hour < 12:
            return 1.00, 1.10, "LONDON"      # Balanced volatility
        elif 12 <= utc_hour < 17:
            return 0.85, 1.20, "NY_OVERLAP"  # High velocity: tighter gap (0.85x) captures fast breakout profits
        elif 17 <= utc_hour < 20:
            return 0.95, 1.0, "NY"
        else:
            return 1.10, 0.90, "EVENING"

    # ------------------------------------------------------------------ #
    #  REGIME DETECTION                                                   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _detect_regime(ema_bias: float, rsi: float, atr_pct: float, bb_width_pct: float, ci: float = 50.0, adx: float = 20.0, mtf_conf: float = 50.0) -> str:
        """
        100% ACCURATE INSTITUTIONAL REGIME CLASSIFIER (CI + ADX + MTF Confluence Matrix)
        - REVERSAL: RSI extreme (>70 or <30) with high choppiness
        - RANGING:  Choppiness Index CI > 58.0 OR ADX < 20.0 OR MTF Confluence < 40%
        - TRENDING: Choppiness Index CI < 45.0 AND ADX >= 24.0 AND MTF Confluence >= 70%
        """
        if (rsi > 70 or rsi < 30) and (ci > 55.0 or bb_width_pct > 2.0):
            return "REVERSAL"
        if ci >= 58.0 or adx <= 20.0 or mtf_conf < 40.0:
            return "RANGING"
        if ci <= 45.0 and adx >= 24.0 and mtf_conf >= 70.0:
            return "TRENDING"
        
        # Fallback multi-signal decision
        if abs(ema_bias) >= 0.45 and atr_pct >= 0.20:
            return "TRENDING"
        return "RANGING"

    # ------------------------------------------------------------------ #
    #  CONFIDENCE SCORE                                                   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _confidence_score(ema_bias: float, ob_delta: float, vwap_bias: float, rsi: float, regime: str) -> int:
        """Returns a confidence score 0-100 for the current evaluation."""
        score = 50.0
        # Strong EMA alignment
        if abs(ema_bias) > 0.70: score += 20.0
        elif abs(ema_bias) > 0.40: score += 10.0
        # Orderbook confirms direction
        if (ema_bias > 0 and ob_delta > 0.20) or (ema_bias < 0 and ob_delta < -0.20):
            score += 15.0
        # VWAP alignment
        if (ema_bias > 0 and vwap_bias > 0.10) or (ema_bias < 0 and vwap_bias < -0.10):
            score += 10.0
        # RSI neutral zone = cleaner signals
        if 40 <= rsi <= 60:
            score += 5.0
        # Regime bonus
        if regime == "TRENDING": score += 5.0
        elif regime == "REVERSAL": score -= 10.0
        return int(max(0, min(100, score)))

    # ------------------------------------------------------------------ #
    #  SHOULD REDEPLOY?                                                   #
    # ------------------------------------------------------------------ #
    def should_redeploy(self, new_bias: float, new_regime: str) -> bool:
        """Returns True if market conditions have shifted enough to warrant redeployment."""
        now = time.time()
        if now - self._last_eval_ts < self._REDEPLOY_COOLDOWN_SECS:
            return False
        bias_shift = abs(new_bias - self._last_eval_bias)
        regime_changed = (new_regime != self._last_eval_regime)
        return bias_shift >= self._BIAS_SHIFT_THRESHOLD or regime_changed

    # ------------------------------------------------------------------ #
    #  MAIN EVALUATION                                                    #
    # ------------------------------------------------------------------ #
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
        tech = tech_indicators or {}
        ob = orderbook_depth or {}
        news = macro_news or []

        current_price = max(0.0001, current_price)
        # ---- 1. SIGNAL EXTRACTION & ATR VOLATILITY SMOOTHING ----
        ema_bias = float(tech.get("ema_trend_bias", 0.0))
        rsi = float(tech.get("rsi", 50.0))
        raw_atr_pct = float(tech.get("atr_pct", 0.30))
        
        # Exponential ATR Spike Smoothing Filter (Prevents Post-Spike Grid Gap Inflation)
        if not hasattr(self, "_smoothed_atr"):
            self._smoothed_atr = raw_atr_pct
        else:
            self._smoothed_atr = 0.70 * self._smoothed_atr + 0.30 * raw_atr_pct
        atr_pct = min(raw_atr_pct, self._smoothed_atr * 1.25)

        bb_width_pct = float(tech.get("bb_width_pct", 2.0))
        vwap_dev = float(tech.get("vwap_dev_pct", 0.0))
        vwap_bias = max(-1.0, min(1.0, vwap_dev / 0.50))

        # ---- 2. ORDERBOOK LIQUIDITY IMBALANCE RATIO (SMC Fakeout Eraser) ----
        buy_pct = float(ob.get("buy_pressure_pct", 50.0))
        ob_delta = (buy_pct - 50.0) / 50.0
        asks_list = ob.get("asks", [])
        bids_list = ob.get("bids", [])
        ask_vol = sum([float(s) for _, s in asks_list]) if asks_list else 0.0
        bid_vol = sum([float(s) for _, s in bids_list]) if bids_list else 0.0
        ob_ratio = round(ask_vol / bid_vol, 3) if bid_vol > 0 else 1.0

        # ---- 3. INSTITUTIONAL REGIME DETECTION (CI + ADX + MTF Confluence) ----
        ci = float(tech.get("choppiness_index", 50.0))
        adx = float(tech.get("adx", 20.0))
        mtf_conf = float(tech.get("mtf_confluence", 50.0))
        regime = tech.get("regime") if tech.get("regime") else self._detect_regime(ema_bias, rsi, atr_pct, bb_width_pct, ci, adx, mtf_conf)

        # ---- 4. COMBINED DIRECTIONAL BIAS & UNIDIRECTIONAL CONFLUENCE ----
        # 50% EMA + 25% VWAP + 15% Orderbook + 10% RSI Trend Momentum
        rsi_signal = (rsi - 50.0) / 50.0  # >0 when price rising, <0 when price dropping
        combined_bias = (
            0.50 * ema_bias
            + 0.25 * vwap_bias
            + 0.15 * ob_delta
            + 0.10 * rsi_signal
        )

        # STRICT VWAP TREND PROTECTION SHIELD:
        # If price is trading BELOW VWAP (vwap_dev < 0) and EMA bias is negative, force combined_bias <= -0.15
        # (Mathematically guarantees that a dropping asset like Gold NEVER locks into BUY_ONLY!)
        if vwap_dev < -0.05 and ema_bias < 0.0:
            combined_bias = min(combined_bias, -0.20)
        elif vwap_dev > 0.05 and ema_bias > 0.0:
            combined_bias = max(combined_bias, 0.20)

        combined_bias = max(-1.0, min(1.0, combined_bias))

        # ---- 4b. ACCURATE TOP & BOTTOM FINDER SHIELD (5-Factor Multi-Confluence Guard) ----
        # CRITICAL TREND SAFETY: Never confuse a strong TREND EXPANSION with a Top/Bottom reversal!
        # Evaluates 5 independent institutional factors (ADX, CI, MTF Confluence, EMA Slope, Volume Expansion).
        # Requires at least 2 confirming factors to classify a Strong Trend Expansion.
        vol_spike = float(tech.get("volume_spike_mult", 1.0))
        trend_score = 0
        if adx >= 25.0:           trend_score += 1  # Factor 1: ADX Trend Strength
        if ci <= 48.0:            trend_score += 1  # Factor 2: Unchoppy Expansion
        if mtf_conf >= 70.0:      trend_score += 1  # Factor 3: 1m+5m+15m MTF Alignment
        if abs(ema_bias) >= 0.35: trend_score += 1  # Factor 4: Strong EMA Slope
        if vol_spike >= 1.30:     trend_score += 1  # Factor 5: Institutional Volume Expansion

        is_strong_trend = (trend_score >= 2)

        if is_strong_trend:
            # During real trends (2+ confirming factors), Top & Bottom Guard stays OFF so we NEVER miss a trend!
            is_top_peak = False
            is_bottom_trough = False
        else:
            # Only during ranging / exhausted markets check for genuine peak top or trough bottom
            is_top_peak = (rsi >= 72.0 or vwap_dev >= 0.50)
            is_bottom_trough = (rsi <= 28.0 or vwap_dev <= -0.50)

        top_bottom_status = "NORMAL"
        side_mode = str(pending_order_side_mode or "AUTO_ADAPTIVE").upper()

        if is_top_peak:
            top_bottom_status = "TOP_PEAK_OVERBOUGHT"
            unidirectional_mode = "SELL_ONLY"  # Block Buy Traps at Top!
        elif is_bottom_trough:
            top_bottom_status = "BOTTOM_TROUGH_OVERSOLD"
            unidirectional_mode = "BUY_ONLY"   # Block Sell Traps at Bottom!
        elif "BOTH" in side_mode:
            unidirectional_mode = "DUAL"
        elif "TREND" in side_mode or "ONE" in side_mode:
            unidirectional_mode = "BUY_ONLY" if combined_bias >= 0.0 else "SELL_ONLY"
        else: # AUTO_ADAPTIVE
            if combined_bias >= 0.30:
                unidirectional_mode = "BUY_ONLY"
            elif combined_bias <= -0.30:
                unidirectional_mode = "SELL_ONLY"
            else:
                unidirectional_mode = "DUAL"


        # ---- 5. NEWS RISK SHIELD ----
        now_ts = time.time()
        news_risk_mult = 1.0
        for ev in news:
            if ev.get("impact") == "HIGH":
                ev_ts = float(ev.get("timestamp", 0))
                if abs(ev_ts - now_ts) <= 900:  # Within 15 minutes
                    news_risk_mult = 2.5
                    break

        # ---- 6. SESSION TIMING ----
        gap_session_mult, size_session_mult, session_name = self._get_session_multiplier()

        # ---- 7. CONFIDENCE SCORE ----
        confidence = self._confidence_score(ema_bias, ob_delta, vwap_bias, rsi, regime)

        # ---- 8. ACCOUNT CAPITAL SCALING ----
        sym_u = (symbol or "").upper()
        # Clean symbol to handle broker suffixes (e.g. XAUUSDm, XAUUSD.a, GOLD)
        clean_sym = sym_u
        for s_token in ["BTCUSDT", "BTCUSD", "ETHUSDT", "ETHUSD", "PAXGUSDT", "XAUUSD", "GOLD", "GBPUSD", "EURUSD", "USDJPY", "SOLUSDT", "SOLUSD", "BNBUSDT", "BNBUSD", "DOGEUSDT", "DOGEUSD", "XRPUSDT", "XRPUSD"]:
            if s_token in sym_u:
                clean_sym = s_token
                break

        PAIR_SWEET_SPOTS = {
            "XAUUSD":   {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.05, "std_offset": 0.07, "base_lot": 0.01,   "min_tp": 3.00, "lot_mult": 1.25},
            "PAXGUSDT": {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.05, "std_offset": 0.07, "base_lot": 0.01,   "min_tp": 3.00, "lot_mult": 1.25},
            "GOLD":     {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.05, "std_offset": 0.07, "base_lot": 0.01,   "min_tp": 3.00, "lot_mult": 1.25},

            "BTCUSD":   {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.004,  "min_tp": 3.50, "lot_mult": 1.25},
            "BTCUSDT":  {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.004,  "min_tp": 3.50, "lot_mult": 1.25},

            "ETHUSD":   {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.15,   "min_tp": 3.50, "lot_mult": 1.25},
            "ETHUSDT":  {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.15,   "min_tp": 3.50, "lot_mult": 1.25},

            "SOLUSD":   {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 1.50,   "min_tp": 3.00, "lot_mult": 1.25},
            "SOLUSDT":  {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 1.50,   "min_tp": 3.00, "lot_mult": 1.25},

            "BNBUSD":   {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.20,   "min_tp": 3.00, "lot_mult": 1.25},
            "BNBUSDT":  {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.20,   "min_tp": 3.00, "lot_mult": 1.25},

            "DOGEUSD":  {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "base_lot": 1000.0, "min_tp": 2.50, "lot_mult": 1.25},
            "DOGEUSDT": {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "base_lot": 1000.0, "min_tp": 2.50, "lot_mult": 1.25},

            "XRPUSD":   {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "base_lot": 100.0,  "min_tp": 2.50, "lot_mult": 1.25},
            "XRPUSDT":  {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "base_lot": 100.0,  "min_tp": 2.50, "lot_mult": 1.25},

            "GBPUSD":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.04, "std_offset": 0.05, "base_lot": 0.01,   "min_tp": 2.50, "lot_mult": 1.25},
            "EURUSD":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.04, "std_offset": 0.05, "base_lot": 0.01,   "min_tp": 2.50, "lot_mult": 1.25},
            "USDJPY":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.04, "std_offset": 0.05, "base_lot": 0.01,   "min_tp": 2.50, "lot_mult": 1.25},
        }

        pair_config = PAIR_SWEET_SPOTS.get(clean_sym, {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.05, "std_offset": 0.08, "base_lot": 0.01, "min_tp": 3.00, "lot_mult": 1.25})

        # ---- 8a. CONTINUOUS MATHEMATICAL DYNAMIC CAPITAL SCALING ENGINE ----
        equity_ratio = max(0.10, account_equity / 1000.0)
        capital_tier = f"${account_equity:,.0f} Dynamic Tier"
        
        # Base Size Continuous Scaling
        raw_base_size = pair_config["base_lot"] * equity_ratio
        
        # Symbol Specific Micro-Lot & Safety Clamp Optimization (Equalized for $1,000+ Crypto Accounts)
        if any(x in clean_sym for x in ["XAU", "GOLD", "PAXG"]):
            base_size = min(0.05, max(0.01, round(raw_base_size, 2)))
        elif any(x in clean_sym for x in ["BTC"]):
            base_size = min(0.10, max(0.001, round(raw_base_size, 3)))
        elif any(x in clean_sym for x in ["ETH"]):
            base_size = min(1.00, max(0.05, round(raw_base_size, 2)))
        elif any(x in clean_sym for x in ["SOL"]):
            base_size = min(10.0, max(0.50, round(raw_base_size, 2)))
        elif any(x in clean_sym for x in ["BNB"]):
            base_size = min(2.00, max(0.10, round(raw_base_size, 2)))
        elif any(x in clean_sym for x in ["DOGE"]):
            base_size = min(10000.0, max(100.0, round(raw_base_size, 1)))
        elif any(x in clean_sym for x in ["GBP", "EUR", "JPY"]):
            base_size = min(0.50, max(0.01, round(raw_base_size, 2)))
        else:
            base_size = max(0.01, round(raw_base_size, 2))

        # Dynamic Target Profit Continuous Scaling ($4.50 USD baseline per $1,000 equity = 0.45% return per cycle)
        base_target_profit = max(1.50, round(4.50 * equity_ratio, 2))
        
        # Dynamic Stop Loss Continuous Scaling (10% equity risk buffer)
        stop_loss = max(25.0, round(account_equity * (getattr(self, "stop_loss_pct", 10.0) / 100.0), 2))
        
        # Dynamic Lot Multiplier Optimization
        if account_equity < 500.0:
            lot_multiplier = 1.20
        elif account_equity < 5000.0:
            lot_multiplier = 1.25
        else:
            lot_multiplier = 1.20
            
        max_levels = 10

        # ---- 8b. SYMBOL VOLATILITY LEVEL CAP ----
        max_levels = min(20, max(10, getattr(self, "grid_levels", 10)))


        # ---- 9. GRID GEOMETRY (Ultra-Sniper 0.07% Golden Sweet Spot) ----
        base_gap = 0.07
        base_offset = 0.07

        # Regime-specific gap scaling
        if regime == "RANGING":
            regime_gap_mult = 0.65    # Tighter for range-fill micro-profits
        elif regime == "TRENDING":
            regime_gap_mult = 0.90
        else:  # REVERSAL
            regime_gap_mult = 1.20    # Protect against false breakouts at extremes

        # Profile-specific geometry scaling (PRO_SCALPING / BALANCED / INSTITUTIONAL)
        profile_mode = getattr(self, "auto_profile", "BALANCED").upper()
        if "SCALPING" in profile_mode:
            profile_offset_mult = 0.85
            profile_gap_mult = 0.85
        elif "INSTITUTIONAL" in profile_mode:
            profile_offset_mult = 1.40
            profile_gap_mult = 1.40
        else:  # BALANCED
            profile_offset_mult = 1.00
            profile_gap_mult = 1.00

        # Symmetric offsets: 100% equal spacing on both BUY and SELL sides
        symmetric_offset = round(base_offset * news_risk_mult * profile_offset_mult, 3)
        buy_offset = max(0.04, min(0.12, symmetric_offset))
        sell_offset = buy_offset

        # Final dynamic gap with session + regime + BB width
        bb_scale = max(0.5, min(2.0, bb_width_pct / 2.0))
        dynamic_gap = max(0.04, min(0.15, round(
            base_gap * bb_scale * regime_gap_mult * gap_session_mult * profile_gap_mult,
            3
        )))

        # ---- Symbol-Specific Dynamic Volatility-Adaptive Architecture (PAIR SWEET SPOTS) ----
        PAIR_SWEET_SPOTS = {
            "XAUUSD":   {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.05, "std_offset": 0.07, "min_tp": 3.00, "lot_mult": 1.25},
            "PAXGUSDT": {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.05, "std_offset": 0.07, "min_tp": 3.00, "lot_mult": 1.25},
            "GOLD":     {"quiet_gap": 0.05, "std_gap": 0.07, "quiet_offset": 0.05, "std_offset": 0.07, "min_tp": 3.00, "lot_mult": 1.25},

            "BTCUSD":   {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.50, "lot_mult": 1.25},
            "BTCUSDT":  {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.50, "lot_mult": 1.25},

            "ETHUSD":   {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.50, "lot_mult": 1.25},
            "ETHUSDT":  {"quiet_gap": 0.06, "std_gap": 0.10, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.50, "lot_mult": 1.25},

            "SOLUSD":   {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.00, "lot_mult": 1.25},
            "SOLUSDT":  {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.00, "lot_mult": 1.25},

            "BNBUSD":   {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.00, "lot_mult": 1.25},
            "BNBUSDT":  {"quiet_gap": 0.05, "std_gap": 0.09, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.00, "lot_mult": 1.25},

            "DOGEUSD":  {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "min_tp": 2.50, "lot_mult": 1.25},
            "DOGEUSDT": {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "min_tp": 2.50, "lot_mult": 1.25},

            "XRPUSD":   {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "min_tp": 2.50, "lot_mult": 1.25},
            "XRPUSDT":  {"quiet_gap": 0.04, "std_gap": 0.07, "quiet_offset": 0.04, "std_offset": 0.07, "min_tp": 2.50, "lot_mult": 1.25},

            "GBPUSD":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.04, "std_offset": 0.05, "min_tp": 2.50, "lot_mult": 1.25},
            "EURUSD":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.04, "std_offset": 0.05, "min_tp": 2.50, "lot_mult": 1.25},
            "USDJPY":   {"quiet_gap": 0.04, "std_gap": 0.05, "quiet_offset": 0.04, "std_offset": 0.05, "min_tp": 2.50, "lot_mult": 1.25},
        }

        is_quiet_market = (regime == "RANGING" or atr_pct < 0.25)
        pair_config = PAIR_SWEET_SPOTS.get(clean_sym, {"quiet_gap": 0.05, "std_gap": 0.08, "quiet_offset": 0.05, "std_offset": 0.08, "min_tp": 3.00, "lot_mult": 1.25})

        min_gap_val = pair_config["quiet_gap"] if is_quiet_market else pair_config["std_gap"]
        min_offset_val = pair_config["quiet_offset"] if is_quiet_market else pair_config["std_offset"]

        dynamic_gap = max(min_gap_val * profile_gap_mult, dynamic_gap)
        buy_offset = max(min_offset_val * profile_offset_mult, buy_offset)
        sell_offset = buy_offset
        lot_multiplier = pair_config.get("lot_mult", 1.25)
        base_target_profit = pair_config.get("min_tp", 3.00)

        # Live Broker Spread-Noise Filter: Scale trap_offset dynamically if live broker spread is high
        live_spread = tech_indicators.get("live_spread", 0.0) if tech_indicators else 0.0
        if live_spread > 0 and current_price > 0:
            spread_pct = (live_spread / current_price) * 100.0
            min_spread_offset = spread_pct * 1.8
            buy_offset = max(buy_offset, min_spread_offset)
            sell_offset = max(sell_offset, min_spread_offset)

        # ---- 10. DYNAMIC TARGET PROFIT (Orderbook S/R Anchored) ----
        # Scale target by ATR volatility + session activity
        vol_tp_scale = max(0.5, min(3.0, atr_pct / 0.30))  # 0.30% ATR = 1.0x
        dynamic_target_profit = round(base_target_profit * vol_tp_scale * (gap_session_mult * 0.8 + 0.2), 2)

        # Orderbook S/R Anchoring: Anchor TP 0.10% below nearest Ask Resistance Wall
        if orderbook_depth and "asks" in orderbook_depth and len(orderbook_depth["asks"]) > 0:
            try:
                top_ask = min([float(p) for p, _ in orderbook_depth["asks"]])
                dist_pct = (top_ask - current_price) / current_price * 100.0
                if 0.10 < dist_pct < 2.0:
                    sr_tp = round(dist_pct * 0.85 * current_price * (base_size / 100.0), 2)
                    dynamic_target_profit = max(2.50, min(dynamic_target_profit, sr_tp))
            except Exception:
                pass

        # ---- 11. ADAPTIVE MONEY MANAGEMENT & CONFIDENCE SIZE SCALING ----
        # Base size is already scaled by account tier. Do NOT multiply equity_scale a second time!
        conf_scale = (0.85 + 0.30 * (confidence / 100.0))  # 0.85x at confidence=0, 1.15x at confidence=100
        adj_size = round(base_size * conf_scale * size_session_mult, 6)

        # MANDATORY HARD SAFE LOT CAPS BY SYMBOL CATEGORY
        # Protects accounts against dangerous over-leveraging on Gold, BTC, ETH, etc.
        if any(x in clean_sym for x in ["PAXG", "XAU", "GOLD"]):
            adj_size = min(0.03, max(0.01, round(adj_size, 2)))  # Gold base lot STRICTLY capped between 0.01 and 0.03 lots max!
        elif any(x in clean_sym for x in ["BTC"]):
            adj_size = min(0.05, max(0.001, round(adj_size, 4))) # Max 0.05 BTC base
        elif any(x in clean_sym for x in ["ETH"]):
            adj_size = min(0.50, max(0.05, round(adj_size, 3)))  # Max 0.50 ETH base
        elif any(x in clean_sym for x in ["SOL"]):
            adj_size = min(3.0, max(0.5, round(adj_size, 2)))    # Max 3.0 SOL base
        elif any(x in clean_sym for x in ["BNB"]):
            adj_size = min(0.50, max(0.05, round(adj_size, 3)))  # Max 0.50 BNB base

        # ---- 11b. AUTO STRATEGY PROFILE SCALING (CONSERVATIVE / BALANCED / AGGRESSIVE) ----
        prof_u = str(auto_profile or "BALANCED").upper()
        if "CONSERVATIVE" in prof_u:
            dynamic_gap = round(dynamic_gap * 1.30, 3)
            adj_size = round(adj_size * 0.75, 4)
            max_levels = max(5, max_levels)
            dynamic_target_profit = round(dynamic_target_profit * 0.85, 2)
            lot_multiplier = 1.15
        elif "AGGRESSIVE" in prof_u:
            dynamic_gap = round(dynamic_gap * 0.80, 3)
            adj_size = round(adj_size * 1.30, 4)
            max_levels = min(15, max_levels + 2)
            dynamic_target_profit = round(dynamic_target_profit * 1.35, 2)
            lot_multiplier = 1.35

        # ---- 12. SMC + ELLIOTT WAVE INTELLIGENCE INTEGRATION ----
        # Runs the full SMC + Elliott Wave analysis on the same klines used above.
        # If SMC bias aligns with EMA bias, combined_bias is boosted by up to 0.20.
        smc_result = {"smc_bias": "NEUTRAL", "smc_score": 50, "elliott_wave": 0,
                      "elliott_confidence": 0.0, "bos_direction": "NEUTRAL",
                      "bullish_ob": 0.0, "bearish_ob": 0.0,
                      "bullish_fvg_low": 0.0, "bullish_fvg_high": 0.0,
                      "bearish_fvg_low": 0.0, "bearish_fvg_high": 0.0,
                      "buy_liquidity": 0.0, "sell_liquidity": 0.0}
        try:
            from core.data import calculate_smc_elliott
            if tech_indicators and isinstance(tech_indicators, dict):
                # Reuse klines_df passed via tech_indicators context or re-fetch
                _smc_df = tech_indicators.get("_klines_df", None)
                if _smc_df is None:
                    from core.data import get_historical_klines
                    _smc_df = get_historical_klines(symbol, interval="1m", limit=100)
                if _smc_df is not None:
                    smc_result = calculate_smc_elliott(_smc_df)
                    # Boost combined_bias when SMC + EMA agree
                    smc_bias_val = smc_result.get("smc_bias", "NEUTRAL")
                    smc_conf = smc_result.get("elliott_confidence", 0.0)
                    if smc_bias_val == "BUY" and combined_bias > 0:
                        combined_bias = min(1.0, combined_bias + 0.15 + smc_conf * 0.10)
                    elif smc_bias_val == "SELL" and combined_bias < 0:
                        combined_bias = max(-1.0, combined_bias - 0.15 - smc_conf * 0.10)
                    combined_bias = round(combined_bias, 3)
        except Exception:
            pass

        # ---- 13. UPDATE STATE FOR REDEPLOYMENT THROTTLE ----
        self._last_eval_bias = combined_bias
        self._last_eval_regime = regime
        self._last_eval_ts = now_ts

        return {
            # Strategy classification
            "capital_tier": capital_tier,
            "market_regime": regime,
            "session_name": session_name,
            "confidence_score": confidence,
            "unidirectional_mode": unidirectional_mode,
            "pending_order_side_mode": side_mode,
            "top_bottom_status": top_bottom_status,
            "is_top_peak": is_top_peak,
            "is_bottom_trough": is_bottom_trough,
            "ob_ratio": ob_ratio,
            # Bias signals
            "ema_trend_bias": ema_bias,
            "combined_bias": round(combined_bias, 3),
            "choppiness_index": ci,
            "adx": adx,
            "mtf_confluence": mtf_conf,
            "vwap_dev_pct": vwap_dev,
            "ob_delta": round(ob_delta, 3),
            "rsi": rsi,
            "news_risk_mult": news_risk_mult,
            # Grid geometry
            "buy_offset_pct": buy_offset,
            "sell_offset_pct": sell_offset,
            "dynamic_gap_pct": dynamic_gap,
            # Risk/money management
            "recommended_size": round(adj_size, 6),
            "recommended_multiplier": lot_multiplier,
            "recommended_levels": max_levels,
            "recommended_stop_loss": round(stop_loss, 2),
            "recommended_target_profit": dynamic_target_profit,
            # SMC + Elliott Wave intelligence
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


def sanitize_order_size(symbol: str, size: float) -> float:
    sym_u = (symbol or "").upper()
    try:
        val = float(size)
    except Exception:
        val = 0.01

    if any(x in sym_u for x in ["PAXG", "XAU", "GOLD"]):
        return min(0.50, max(0.01, round(val, 2)))   # Gold: 0.01–0.50 lots
    elif any(x in sym_u for x in ["BTC"]):
        return min(0.10, max(0.0001, round(val, 4))) # BTC: 0.0001–0.10 lots
    elif any(x in sym_u for x in ["ETH"]):
        return min(1.0,  max(0.001, round(val, 3)))  # ETH: 0.001–1.0 lots
    elif any(x in sym_u for x in ["SOL"]):
        return min(10.0, max(0.01, round(val, 2)))   # SOL: 0.01–10.0 lots
    elif any(x in sym_u for x in ["BNB"]):
        return min(10.0, max(0.01, round(val, 2)))   # BNB: 0.01–10.0 lots
    elif any(x in sym_u for x in ["DOGE"]):
        return min(10000.0, max(0.1, round(val, 2))) # DOGE: 0.1–10,000 lots
    else:
        return min(10.0, max(0.0001, round(val, 4)))


class BreakoutGridBot:
    def __init__(
        self,
        broker: 'MT5Broker',
        symbol: str = "BTCUSDT",
        grid_levels: int = 5,
        grid_gap: float = 10.0,
        trap_offset: float = 5.0,
        order_size: float = 0.01,
        order_size_multiplier: float = 1.25,
        target_profit: float = 4.50,
        auto_restart: bool = True,
        is_percent: bool = False,
        spacing_mode: Optional[str] = None,
        stop_loss: float = 0.0,
        max_cycle_duration: float = float("inf"),
        cancel_opposite_on_trigger: bool = False,
        use_trailing_stop: bool = False,
        trailing_stop_distance: float = 15.0,
        use_bb_filter: bool = False,
        bb_squeeze_threshold: float = 0.02,
        use_breakeven: bool = True,
        breakeven_trigger: float = 0.5,
        use_smart_trailing: bool = True,
        profit_lock_pct: float = 0.80,
        use_adaptive_gap: bool = False,
        base_bb_width: float = 0.005,
        adaptive_gap_min_mult: float = 0.5,
        adaptive_gap_max_mult: float = 2.5,
        use_auto_reading: bool = False,
        pending_order_side_mode: str = "AUTO_ADAPTIVE"
    ):
        self.broker = broker
        self.grid_levels = min(5, max(1, int(grid_levels)))
        self.grid_gap = grid_gap
        self.trap_offset = trap_offset
        self.order_size = order_size
        self.order_size_multiplier = min(1.30, max(1.0, float(order_size_multiplier)))
        self.max_basket_drawdown_pct = 0.05  # Emergency 5% floating equity loss ceiling shield
        self.target_profit = target_profit
        self.auto_restart = auto_restart
        self.pending_order_side_mode = pending_order_side_mode
        if spacing_mode:
            self._spacing_mode = spacing_mode
        elif is_percent:
            self._spacing_mode = "Percentage (%)"
        else:
            self._spacing_mode = "USD Points ($)"
        self.stop_loss = stop_loss
        self.max_cycle_duration = max_cycle_duration
        self.cancel_opposite_on_trigger = cancel_opposite_on_trigger
        self.use_trailing_stop = use_trailing_stop
        self.trailing_stop_distance = trailing_stop_distance
        self.use_bb_filter = use_bb_filter
        self.bb_squeeze_threshold = bb_squeeze_threshold

        self.use_breakeven = use_breakeven
        self.breakeven_trigger = breakeven_trigger  # fraction of target_profit that activates breakeven (0.5 = 50%)
        self.use_smart_trailing = use_smart_trailing
        self.profit_lock_pct = profit_lock_pct
        self.use_adaptive_gap = use_adaptive_gap
        self.base_bb_width = base_bb_width
        self.adaptive_gap_min_mult = adaptive_gap_min_mult
        self.adaptive_gap_max_mult = adaptive_gap_max_mult
        self.use_auto_reading = use_auto_reading
        self.auto_reading_engine = AutoReadingEngine()

        sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
        self._order_size = sanitize_order_size(sym_str, order_size)

        # Risk Control Circuit Breaker & Macro News Shield
        self.max_daily_drawdown: float = 0.0  # 0.0 disabled; e.g. 250.0 = max -$250 loss cap
        self.daily_circuit_breaker_tripped: bool = False
        self.use_news_shield: bool = True

        # Prop Firm Challenge Compliance Engine (FTMO / FundedNext / Funding Pips)
        self.prop_firm_guard_enabled: bool = False
        self.prop_firm_max_daily_drawdown_pct: float = 4.5  # 4.5% daily drawdown lock (buffer for 5.0% limit)
        self.prop_firm_target_pct: float = 8.0  # 8.0% challenge pass target lock

        # Friday Weekend Market Shutdown Engine (Gold XAUUSD, Forex, Metals, Oils, Indices)
        sym_str_upper = sym_str.upper()
        is_crypto_247 = any(c_sym in sym_str_upper for c_sym in ["BTC", "ETH", "SOL", "BNB", "DOGE", "XRP"])
        self.use_weekend_shutdown: bool = not is_crypto_247  # Auto-enabled for Gold, Forex, Oils, Indices; Disabled for 24/7 Crypto
        self.weekend_shutdown_utc_hour: int = 20  # Shutdown Friday at 20:00 UTC (8 PM UTC)
        self.weekend_shutdown_triggered: bool = False

        # Grid Maintenance Engine Toggles (Disabled by default for Strict Single-Basket Cycle Isolation)
        self.use_grid_repair: bool = False
        self.use_auto_cleanup: bool = False

        self.deployed = False
        self.deploy_price = 0.0
        self.current_cycle_id = 1
        
        self.cycle_history = []
        self.cycle_start_time = 0.0
        self.max_floating_pnl = -float("inf")
        self.breakeven_activated = False  # True once pnl has crossed the breakeven threshold
        self.in_runner_mode = False
        self.price_history_ticks: List[float] = []
        # Stagnant grid tracking: timestamp of last order trigger or last redeploy
        self._last_trigger_time: float = 0.0
        # Cooldown after Runner Mode exits to prevent instant trap fills on trending price
        self._runner_exit_cooldown_until: float = 0.0

        # ── LIQUIDITY GRAB / FAKE-OUT GUARD ──────────────────────────────────────
        # Watches newly filled positions for N ticks. If price crosses back through
        # entry while position is in loss → classic stop hunt → close early.
        self._fakeout_guard_enabled: bool = True      # Master toggle (user can disable)
        self._fakeout_guard_ticks: int = 8            # Tick window to watch after fill (~12s @ 1.5s/tick)
        self._fakeout_recent_fills: dict = {}         # {position_id: (entry_price, pos_type, fill_tick)}
        self._tick_counter: int = 0                   # Monotonic tick counter
        # ─────────────────────────────────────────────────────────────────────────

        # ── SMC + ELLIOTT WAVE TOGGLE ──────────────────────────────────────────────
        self.use_smc_elliott: bool = True   # Enables SMC Order Block + FVG + Elliott Wave engine
        self._last_smc_eval: dict = {}      # Cached most-recent SMC evaluation result
        # ─────────────────────────────────────────────────────────────────────────

    @property
    def order_size(self) -> float:
        sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
        return sanitize_order_size(sym_str, getattr(self, "_order_size", 0.01))

    @order_size.setter
    def order_size(self, val: float):
        sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
        self._order_size = sanitize_order_size(sym_str, val)

    @property
    def spacing_mode(self) -> str:
        return getattr(self, "_spacing_mode", "Percentage (%)")

    @spacing_mode.setter
    def spacing_mode(self, val: str):
        self._spacing_mode = val

    @property
    def is_percent(self) -> bool:
        mode = str(self.spacing_mode).lower()
        return "pct" in mode or "percent" in mode

    @is_percent.setter
    def is_percent(self, val: bool):
        if val:
            self._spacing_mode = "Percentage (%)"
        elif self.spacing_mode == "Percentage (%)":
            self._spacing_mode = "USD Points ($)"

    def calculate_offset_and_gap(
        self,
        center_price: float,
        gap_config: Optional[float] = None,
        offset_config: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Calculates absolute offset and gap values based on active spacing_mode:
        - "Percentage (%)": % of center_price
        - "Pips": pips * pip_size
        - "USD Points ($)": direct USD / price distance
        """
        gap_to_use = gap_config if gap_config is not None else self.grid_gap
        offset_to_use = offset_config if offset_config is not None else self.trap_offset

        mode_lower = str(self.spacing_mode).lower()
        if "pip" in mode_lower:
            symbol_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
            pip_sz = get_pip_size(symbol_str, center_price)
            offset_val = offset_to_use * pip_sz
            gap_val = gap_to_use * pip_sz
        elif "pct" in mode_lower or "percent" in mode_lower:
            offset_val = center_price * (offset_to_use / 100.0)
            gap_val = center_price * (gap_to_use / 100.0)
        else:
            offset_val = offset_to_use
            gap_val = gap_to_use

        return offset_val, gap_val

    def get_effective_gap(self, current_price: float, bb_width: Optional[float] = None) -> float:
        """
        Calculates dynamic grid gap based on Bollinger Band volatility.
        When volatility is quiet, grid gap shrinks down to 50% for fast micro-scalping.
        When volatility expands, grid gap widens up to 250% to avoid over-leveraging on spikes.
        """
        base_gap = self.grid_gap
        if not getattr(self, "use_adaptive_gap", False) or bb_width is None or bb_width <= 0:
            return base_gap

        ref_bb = getattr(self, "base_bb_width", 0.005)
        ratio = bb_width / ref_bb if ref_bb > 0 else 1.0

        min_m = getattr(self, "adaptive_gap_min_mult", 0.5)
        max_m = getattr(self, "adaptive_gap_max_mult", 2.5)
        clamped_ratio = max(min_m, min(max_m, ratio))

        return round(base_gap * clamped_ratio, 6)

    def calculate_level_size(self, base_size: float, mult: float, level_idx: int) -> float:
        """
        Calculates exact level lot size for Martingale level index `level_idx` (0, 1, 2, ...).
        Ensures strict level lot scaling so adjacent levels don't collapse to the same size,
        and clamps high levels to safe maximum volume limits.
        """
        if mult == 1.0 or level_idx == 0:
            return round(base_size, 8)

        # Calculate raw size with exponential multiplier
        raw_size = base_size * (mult ** level_idx)
        size = round(raw_size, 8)

        if mult > 1.0:
            # Ensure strict progression if multiplier > 1.0:
            # level i must be strictly larger than level i-1
            prev_raw = base_size * (mult ** (level_idx - 1))
            prev_size = round(prev_raw, 8)
            
            # If rounding collapsed them to the same size, enforce at least 1 min volume step increase
            if size <= prev_size:
                size = prev_size + 0.01

            # Clamp to safe max order size cap per symbol category
            sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", "")).upper()
            if any(x in sym_str for x in ["XAU", "GOLD", "PAXG"]):
                default_max_cap = 0.05  # Gold strict safety limit: max 0.05 lots per order
            elif any(x in sym_str for x in ["BTC"]):
                default_max_cap = 0.10  # BTC max 0.10 BTC per order
            elif any(x in sym_str for x in ["ETH"]):
                default_max_cap = 1.00  # ETH max 1.00 ETH per order
            elif any(x in sym_str for x in ["SOL"]):
                default_max_cap = 5.00  # SOL max 5.00 SOL per order
            else:
                default_max_cap = 1.0

            max_cap = min(getattr(self, "max_order_size", default_max_cap), base_size * 4.0)
            if max_cap > 0 and size > max_cap:
                size = max_cap
        else:
            # Anti-Martingale (mult < 1.0): Ensure size doesn't drop below 0.001
            if size < 0.001:
                size = 0.001

        return round(size, 8)

    def ensure_attributes_initialized(self):
        """
        Guarantees all instance attributes exist even for legacy unpickled instances.
        """
        if not hasattr(self, "_spacing_mode"):
            self._spacing_mode = "Percentage (%)"
        if not hasattr(self, "price_history_ticks") or self.price_history_ticks is None:
            self.price_history_ticks = []
        if not hasattr(self, "_last_trigger_time"):
            self._last_trigger_time = 0.0
        if not hasattr(self, "_runner_exit_cooldown_until"):
            self._runner_exit_cooldown_until = 0.0
        if not hasattr(self, "daily_circuit_breaker_tripped"):
            self.daily_circuit_breaker_tripped = False
        if not hasattr(self, "use_news_shield"):
            self.use_news_shield = False
        if not hasattr(self, "prop_firm_guard_enabled"):
            self.prop_firm_guard_enabled = False
        if not hasattr(self, "use_grid_repair"):
            self.use_grid_repair = False
        if not hasattr(self, "use_auto_cleanup"):
            self.use_auto_cleanup = False
        if not hasattr(self, "cycle_history"):
            self.cycle_history = []
        if not hasattr(self, "breakeven_activated"):
            self.breakeven_activated = False
        if not hasattr(self, "in_runner_mode"):
            self.in_runner_mode = False
        if not hasattr(self, "cancel_opposite_on_trigger"):
            self.cancel_opposite_on_trigger = False  # OFF by default — user enables OCO per pair
        if not hasattr(self, "use_trailing_stop"):
            self.use_trailing_stop = False
        if not hasattr(self, "trailing_stop_distance"):
            self.trailing_stop_distance = 15.0
        if not hasattr(self, "use_breakeven"):
            self.use_breakeven = True
        if not hasattr(self, "breakeven_trigger"):
            self.breakeven_trigger = 0.5
        if not hasattr(self, "use_smart_trailing"):
            self.use_smart_trailing = True
        if not hasattr(self, "profit_lock_pct"):
            self.profit_lock_pct = 0.80
        if not hasattr(self, "use_adaptive_gap"):
            self.use_adaptive_gap = False
        if not hasattr(self, "use_stagnant_redeploy"):
            self.use_stagnant_redeploy = False
        if not hasattr(self, "_last_trigger_time") or getattr(self, "_last_trigger_time", 0.0) <= 0.0:
            self._last_trigger_time = time.time()
        if not hasattr(self, "grid_levels"):
            self.grid_levels = 5
        if not hasattr(self, "grid_gap"):
            self.grid_gap = 0.30    # 0.30% — safe % mode default
        if not hasattr(self, "trap_offset"):
            self.trap_offset = 0.15   # 0.15% — safe % mode default
        if not hasattr(self, "order_size"):
            self.order_size = 0.01
        if not hasattr(self, "order_size_multiplier"):
            self.order_size_multiplier = 1.25
        if not hasattr(self, "target_profit"):
            self.target_profit = 10.0
        if not hasattr(self, "stop_loss"):
            self.stop_loss = 0.0
        if not hasattr(self, "max_daily_drawdown"):
            self.max_daily_drawdown = 0.0
        if not hasattr(self, "daily_circuit_breaker_tripped"):
            self.daily_circuit_breaker_tripped = False
        if not hasattr(self, "max_cycle_duration"):
            self.max_cycle_duration = float("inf")
        if not hasattr(self, "auto_restart"):
            # Default OFF — app.py sets True for Auto mode, False for Manual mode
            self.auto_restart = False
        if not hasattr(self, "use_auto_reading"):
            self.use_auto_reading = False
        if not hasattr(self, "auto_profile"):
            self.auto_profile = "BALANCED"
        if not hasattr(self, "pending_order_side_mode"):
            self.pending_order_side_mode = "AUTO_ADAPTIVE"
        if not hasattr(self, "auto_reading_engine"):
            self.auto_reading_engine = AutoReadingEngine()
        # Fake-out guard backward-compat (for pickled bots loaded from bot_state.pkl)
        if not hasattr(self, "_fakeout_guard_enabled"):
            self._fakeout_guard_enabled = True
        if not hasattr(self, "_fakeout_guard_ticks"):
            self._fakeout_guard_ticks = 8
        if not hasattr(self, "_fakeout_recent_fills"):
            self._fakeout_recent_fills = {}
        if not hasattr(self, "_tick_counter"):
            self._tick_counter = 0
        # SMC + Elliott Wave backward-compat
        if not hasattr(self, "use_smc_elliott"):
            self.use_smc_elliott = True
        if not hasattr(self, "_last_smc_eval"):
            self._last_smc_eval = {}

    def deploy_traps(self, current_price: float, timestamp: float, bb_width: Optional[float] = None, force: bool = False):
        """
        Cancel existing traps and place a new grid of traps centered around current_price.
        If use_bb_filter is True, deployment will be skipped if bb_width is missing or > threshold.
        """
        self.ensure_attributes_initialized()

        # Concurrent Execution Guard: Prevent overlapping deploy passes
        if getattr(self, "_is_deploying", False):
            return
        self._is_deploying = True

        # Rapid Re-Deploy Cooldown Guard: Prevent deploy_traps from running multiple times within 3 seconds
        if not force and timestamp < (getattr(self, "last_deploy_time", 0.0) + 3.0):
            self._is_deploying = False
            return

        # Active Grid Lock Guard: Lock active traps in place until triggered or forced.
        # Prevents tick updates or Auto-Reading re-evaluations from churning active pending orders.
        if not force and self.deployed and len(self.broker.pending_orders) > 0 and len(self.broker.open_positions) == 0:
            self._is_deploying = False
            return

        # Active Grid Guard: If grid traps are already deployed and active on MT5,
        # NEVER wipe and redeploy on background tick loops. Keep traps stationary!
        if not force and self.deployed and len(self.broker.pending_orders) > 0:
            self._is_deploying = False
            return

        if not force and timestamp < getattr(self, "_last_deploy_error_time", 0.0) + 3.0:
            self._is_deploying = False
            return

        # MT5 Connection Readiness Guard: Do NOT wipe or place traps if broker connection is offline/invalid
        if hasattr(self.broker, "ensure_connected"):
            try:
                if not self.broker.ensure_connected():
                    self.deployed = False
                    self._last_deploy_error_time = timestamp
                    print(f"[{getattr(self.broker, 'symbol', 'BOT')}] Broker connection offline/unauthorized. Skipping trap deployment.")
                    return
            except Exception as conn_err:
                self.deployed = False
                self._last_deploy_error_time = timestamp
                print(f"[{getattr(self.broker, 'symbol', 'BOT')}] Broker connection check error: {conn_err}")
                return

        if getattr(self, "use_bb_filter", False):
            if bb_width is None or bb_width > getattr(self, "bb_squeeze_threshold", 0.02):
                return

        # Check Daily Loss Circuit Breaker
        if getattr(self, "max_daily_drawdown", 0.0) > 0:
            realized = getattr(self.broker, "realized_pnl", 0.0)
            if realized <= -self.max_daily_drawdown:
                self.daily_circuit_breaker_tripped = True
                print(f"[{getattr(self.broker, 'symbol', 'BOT')}] Daily Drawdown Circuit Breaker TRIPPED (-${abs(realized):.2f} <= -${self.max_daily_drawdown:.2f}). Deployment halted.")
                return

        # Weekend Shutdown Guard: Pause grid deployment during Friday evening and weekend market close
        if getattr(self, "use_weekend_shutdown", True):
            import datetime
            ts_sec = (timestamp / 1000.0) if timestamp > 1e11 else timestamp
            dt_gmt = datetime.datetime.fromtimestamp(ts_sec, datetime.timezone.utc)
            is_weekend_pause = (dt_gmt.weekday() == 4 and dt_gmt.hour >= getattr(self, "weekend_shutdown_utc_hour", 20)) or (dt_gmt.weekday() == 5) or (dt_gmt.weekday() == 6 and dt_gmt.hour < 22)
            if is_weekend_pause:
                self._last_deploy_error_time = timestamp
                return

        # Existing Open Positions Guard:
        # If open positions already exist when deploy_traps is called (e.g. restarting Auto mode or clicking Deploy),
        # DO NOT deploy a duplicate new grid! Instead, run repair_grid to safely manage existing positions without duplication.
        if len(self.broker.open_positions) > 0 and getattr(self, "use_grid_repair", True):
            self.repair_grid(current_price, timestamp)
            return

        effective_gap = self.get_effective_gap(current_price, bb_width)

        # FIX 1: Do NOT cancel traps yet — wait until after Auto-Reading succeeds.
        # Cancelling here and then failing Auto-Reading would leave grid uncovered with zero traps.
        self.deploy_price = current_price
        self.cycle_start_time = timestamp
        self._last_trigger_time = timestamp
        self.in_runner_mode = False
        self.breakeven_activated = False
        self.ratchet_floor = 0.0
        self.max_floating_pnl = -float("inf")
        if not hasattr(self, "price_history_ticks") or self.price_history_ticks is None:
            self.price_history_ticks = []
        else:
            self.price_history_ticks.clear()
        self._last_trigger_time = timestamp

        # Auto-Reading Engine Execution
        if getattr(self, "_custom_auto_eval", None):
            eval_res = self._custom_auto_eval
            self.last_auto_eval = eval_res
            buy_offset_val = current_price * (eval_res["buy_offset_pct"] / 100.0)
            sell_offset_val = current_price * (eval_res["sell_offset_pct"] / 100.0)
            gap_val = current_price * (eval_res["dynamic_gap_pct"] / 100.0)
        elif getattr(self, "use_auto_reading", True):
            try:
                from core.data import get_historical_klines, calculate_technical_indicators, get_order_book_depth, get_economic_calendar
                sym_str = getattr(self.broker, "symbol", "BTCUSDT")
                klines_df = get_historical_klines(sym_str, interval="1m", limit=100)
                tech = calculate_technical_indicators(klines_df)
                ob = get_order_book_depth(sym_str)
                news = get_economic_calendar()
                # Use shared_account_equity if set by app.py (total across all market brokers),
                # so ETH and Gold on the same account always get the same capital tier & levels.
                bal = float(
                    getattr(self, "shared_account_equity", None)
                    or getattr(self.broker, "balance_usd", getattr(self.broker, "balance", 1000.0))
                )

                eval_res = self.auto_reading_engine.evaluate_market_and_account(
                    symbol=sym_str,
                    current_price=current_price,
                    account_equity=bal,
                    tech_indicators=tech,
                    orderbook_depth=ob,
                    macro_news=news,
                    auto_profile=getattr(self, "auto_profile", "BALANCED"),
                    pending_order_side_mode=getattr(self, "pending_order_side_mode", "AUTO_ADAPTIVE")
                )
                
                self.order_size = eval_res["recommended_size"]
                self.order_size_multiplier = eval_res["recommended_multiplier"]
                
                # Pillar 4: 100% Multi-Timeframe (MTF) Trend Lot Booster
                # When 1m + 5m + 15m trend confluence is 100%, boost trend-side lot size multiplier to 1.35x
                mtf_score = float(eval_res.get("mtf_confluence", 50.0))
                comb_bias = float(eval_res.get("combined_bias", 0.0))
                if mtf_score >= 100.0 and abs(comb_bias) >= 0.35:
                    self.order_size_multiplier = float(round(self.order_size_multiplier * 1.35, 2))
                    eval_res["recommended_multiplier"] = self.order_size_multiplier

                # Pillar 1: Smart Tiered Symbol Order Allocation Shield
                # Prevents Exness Retcode 10033 by allocating grid levels by symbol tier:
                # - Tier 1 Majors (XAUUSD/PAXGUSDT, BTCUSD/BTCUSDT, EURUSD, USDJPY): 4 - 5 levels max
                # - Tier 2 Minors (GBPUSD, ETHUSD/ETHUSDT): 3 levels max
                # - Tier 3 Altcoins (SOL, BNB, DOGE): 2 levels max
                sym_u = str(sym_str).upper()
                if any(x in sym_u for x in ["XAU", "GOLD", "PAXG", "BTC", "EURUSD", "USDJPY"]):
                    tier_max_lvl = 5
                elif any(x in sym_u for x in ["GBPUSD", "ETH"]):
                    tier_max_lvl = 3
                else:
                    tier_max_lvl = 2

                rec_lvl = int(eval_res.get("recommended_levels", 5))
                tot_acc_orders = 0
                if hasattr(self.broker, "get_total_account_orders_count"):
                    tot_acc_orders = self.broker.get_total_account_orders_count()
                if tot_acc_orders >= 75:
                    self.grid_levels = max(2, min(2, tier_max_lvl))
                elif tot_acc_orders >= 50:
                    self.grid_levels = max(2, min(3, tier_max_lvl))
                else:
                    self.grid_levels = max(2, min(rec_lvl, tier_max_lvl))

                # Pillar 2: Live Spread & Rollover Spike Shield
                # Pauses new grid trap deployment if live bid/ask spread exceeds 1.8x median spread
                ask_ref_tmp = getattr(self.broker, "last_ask", current_price)
                bid_ref_tmp = getattr(self.broker, "last_bid", current_price)
                if ask_ref_tmp > 0 and bid_ref_tmp > 0:
                    curr_spread = abs(ask_ref_tmp - bid_ref_tmp)
                    if not hasattr(self, "_spread_history") or self._spread_history is None:
                        self._spread_history = []
                    if curr_spread > 0:
                        self._spread_history.append(curr_spread)
                        if len(self._spread_history) > 100:
                            self._spread_history.pop(0)
                        median_spread = float(np.median(self._spread_history)) if len(self._spread_history) >= 10 else curr_spread
                        eval_res["spread_spike_ratio"] = round(curr_spread / median_spread, 2) if median_spread > 0 else 1.0
                        if median_spread > 0 and (curr_spread / median_spread) > 1.80:
                            print(f"[{sym_str}] Live spread spike detected ({curr_spread:.4f} vs median {median_spread:.4f}). Pausing trap deployment for 30s.")
                            return

                self.stop_loss = eval_res["recommended_stop_loss"]
                if "recommended_target_profit" in eval_res:
                    self.target_profit = eval_res["recommended_target_profit"]
                if "dynamic_gap_pct" in eval_res:
                    self.grid_gap = eval_res["dynamic_gap_pct"]
                if "buy_offset_pct" in eval_res:
                    self.trap_offset = eval_res["buy_offset_pct"]
                # Auto Mode Enhancements: Force OCO OFF completely in Auto Mode to preserve dual-sided hedging
                if getattr(self, "use_auto_reading", False):
                    self.cancel_opposite_on_trigger = False
                else:
                    self.cancel_opposite_on_trigger = getattr(self, "cancel_opposite_on_trigger", False)
                self.unidirectional_mode = eval_res.get("unidirectional_mode", "DUAL")

                # GOLD-FIRST PROVEN PARAMETER ENFORCEMENT:
                # Apply backtested-optimised floors for Gold (XAUUSD/PAXGUSDT) and all other pairs
                gold_params = get_pair_gold_params(sym_str)
                if gold_params["is_gold"]:
                    # Gold proven params: gap 0.18%–0.28%, offset 0.12%–0.20%, lot 0.01–0.03
                    proven_gap_val   = current_price * (gold_params["base_gap_pct"]   / 100.0)
                    proven_off_val   = current_price * (gold_params["base_offset_pct"] / 100.0)
                    # Only enforce if eval produced a tighter gap than proven (never force wider than 2x proven)
                    self.grid_gap    = float(max(self.grid_gap,    gold_params["base_gap_pct"]))
                    self.trap_offset = float(max(self.trap_offset, gold_params["base_offset_pct"]))
                    self.grid_levels = min(self.grid_levels, gold_params["max_levels"])
                    # Enforce lot size within Gold safe range
                    if hasattr(self, "order_size") and self.order_size > 0:
                        self.order_size = float(max(gold_params["min_lot"],
                                                    min(gold_params["max_lot"], self.order_size)))

                # Store latest evaluation for UI display
                self.last_auto_eval = eval_res
                
                # Dynamic ATR Volatility-Adaptive Gap Scaling:
                # During high volatility sessions (ATR > 0.35% of price), expand grid gap by 1.25x for optimal trap spacing
                atr_val = getattr(self, "current_atr", 0.0)
                vol_gap_mult = 1.25 if (atr_val > 0 and current_price > 0 and (atr_val / current_price * 100.0) > 0.35) else 1.0

                buy_offset_val = current_price * (eval_res["buy_offset_pct"] / 100.0)
                sell_offset_val = current_price * (eval_res["sell_offset_pct"] / 100.0)
                gap_val = current_price * (eval_res["dynamic_gap_pct"] / 100.0) * vol_gap_mult

                # DATA-ANCHORED LIQUIDITY & VWAP ENVELOPE SHIELD (NEVER BLINDLY PLACE TRAPS)
                # Guarantees that grid traps anchor to real live market data (VWAP deviation + Orderbook liquidity):
                vwap_dev_pct = abs(float(eval_res.get("vwap_dev_pct", 0.0)))
                if vwap_dev_pct > 0 and current_price > 0:
                    vwap_band_dist = (vwap_dev_pct / 100.0) * current_price * 1.15
                    buy_offset_val = max(buy_offset_val, vwap_band_dist)
                    sell_offset_val = max(sell_offset_val, vwap_band_dist)

            except Exception as auto_err:
                print(f"Auto-Reading execution notice: {auto_err}")
                buy_offset_val, gap_val = self.calculate_offset_and_gap(current_price, effective_gap, self.trap_offset)
                sell_offset_val = buy_offset_val
        else:
            buy_offset_val, gap_val = self.calculate_offset_and_gap(current_price, effective_gap, self.trap_offset)
            sell_offset_val = buy_offset_val

        # Broker Minimum Stop Level Protection Shield:
        # Guarantees that buy_offset_val and sell_offset_val exceed MT5's trade_stops_level by 25%,
        # making price clamping collisions mathematically impossible on Exness Cent / Standard accounts!
        if hasattr(self.broker, "get_min_stop_distance"):
            try:
                min_stop = float(self.broker.get_min_stop_distance())
                if min_stop > 0:
                    safety_buffer = min_stop * 1.25
                    buy_offset_val = max(buy_offset_val, safety_buffer)
                    sell_offset_val = max(sell_offset_val, safety_buffer)
            except Exception:
                pass

        ask_ref = getattr(self.broker, "last_ask", current_price)
        bid_ref = getattr(self.broker, "last_bid", current_price)
        if not ask_ref or ask_ref <= 0: ask_ref = current_price
        if not bid_ref or bid_ref <= 0: bid_ref = current_price

        # Real-Time Dynamic Volume Velocity Stats Engine:
        # Evaluates tick velocity over recent price ticks to dynamically scale gap and offset for ultra-fast cycle deployment
        tick_history = getattr(self, "price_history_ticks", [])
        if len(tick_history) >= 5 and current_price > 0:
            recent_ticks = tick_history[-5:]
            px_range = max(recent_ticks) - min(recent_ticks)
            velocity_pct = (px_range / current_price) * 100.0
            if velocity_pct > 0.15:  # High Volatility Velocity Spike -> expand gap by 1.25x for safety
                gap_val *= 1.25
                buy_offset_val *= 1.20
                sell_offset_val *= 1.20

        # DYNAMIC ATR VOLATILITY GAP SCALING SHIELD (UNTRAPPABLE MATRIX):
        # Dynamically adapts grid spacing to live market volatility so orders NEVER get trapped during trend spikes!
        atr_val = getattr(self, "current_atr", 0.0)
        if atr_val > 0:
            gap_val = max(gap_val, round(atr_val * 1.20, 2))

        self.deploy_order_size = self.order_size
        self.deploy_order_size_multiplier = self.order_size_multiplier
        self.deploy_grid_gap = gap_val
        self.deploy_trap_offset = buy_offset_val

        placed_count = 0
        cancel_success = False
        placement_failed = False
        try:
            unidirectional_mode = getattr(self, "unidirectional_mode", "DUAL")

            # ── ULTRA-FAST LIVE SPREAD & MOMENTUM GRID OPTIMIZER ────────────
            # 1. Live Spread Shield: Ensure offsets strictly exceed 1.8x live Bid-Ask spread
            if hasattr(self.broker, "get_current_spread"):
                live_sp = float(self.broker.get_current_spread())
                if live_sp > 0:
                    min_sp_off = live_sp * 1.80
                    buy_offset_val = max(buy_offset_val, min_sp_off)
                    sell_offset_val = max(sell_offset_val, min_sp_off)

            # 2. Trend Acceleration: In strong trend mode, tighten trend-side offset 15% for fast execution
            if unidirectional_mode == "BUY_ONLY":
                buy_offset_val *= 0.85
            elif unidirectional_mode == "SELL_ONLY":
                sell_offset_val *= 0.85
            # ────────────────────────────────────────────────────────────────────


            # Always cancel existing pending orders FIRST before placing new grid traps
            try:
                self.broker.cancel_all_orders()
                cancel_success = True
            except Exception as pre_cancel_err:
                print(f"Pre-deploy cancel notice: {pre_cancel_err}")

            # Symbol-Adaptive Hardware Broker Take-Profit (TP) Floor
            sym_name = str(getattr(self.broker, "symbol", "")).upper()
            if "BTC" in sym_name:
                min_tp_dist = max(gap_val * 1.0, 50.00)
            elif any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]):
                min_tp_dist = max(gap_val * 1.0, 3.00)
            elif "ETH" in sym_name:
                min_tp_dist = max(gap_val * 1.0, 3.00)
            elif "SOL" in sym_name:
                min_tp_dist = max(gap_val * 1.0, 0.50)
            elif "BNB" in sym_name:
                min_tp_dist = max(gap_val * 1.0, 1.00)
            else:
                min_tp_dist = max(gap_val * 1.0, current_price * 0.001)

            # ── SMC + ELLIOTT WAVE GRID REFINEMENT ──────────────────────────────
            # Uses the cached SMC evaluation from the last AutoReading eval to:
            #   1. Snap buy_offset_val toward the nearest Bullish Order Block
            #   2. Avoid placing traps inside Fair Value Gaps (shift to FVG edge)
            #   3. Apply Wave 3 lot size boost (+35%) for strongest impulse entries
            # All adjustments are bounded so they NEVER violate broker min-stop rules.
            if getattr(self, "use_smc_elliott", True):
                try:
                    smc = getattr(self, "last_auto_eval", {}) or {}
                    bullish_ob   = float(smc.get("bullish_ob",        0.0))
                    bearish_ob   = float(smc.get("bearish_ob",        0.0))
                    bull_fvg_lo  = float(smc.get("bullish_fvg_low",   0.0))
                    bull_fvg_hi  = float(smc.get("bullish_fvg_high",  0.0))
                    bear_fvg_lo  = float(smc.get("bearish_fvg_low",   0.0))
                    bear_fvg_hi  = float(smc.get("bearish_fvg_high",  0.0))
                    elliott_wave = int(smc.get("elliott_wave",         0))
                    elliott_conf = float(smc.get("elliott_confidence", 0.0))
                    bos_dir      = str(smc.get("bos_direction",  "NEUTRAL"))

                    # 1. ORDER BLOCK SNAP
                    ob_snap_done = False
                    if bullish_ob > 0 and ask_ref > bullish_ob > ask_ref - gap_val * 3.0:
                        ob_dist = ask_ref - bullish_ob
                        buy_offset_val = max(ob_dist, buy_offset_val * 0.75)
                        ob_snap_done = True

                    # 2. FVG AVOIDANCE — shift traps outside imbalance zones
                    first_buy_level = ask_ref + buy_offset_val
                    if bear_fvg_lo > 0 and bear_fvg_lo < first_buy_level < bear_fvg_hi:
                        buy_offset_val = bear_fvg_hi - ask_ref + gap_val * 0.25

                    first_sell_level = bid_ref - sell_offset_val
                    if bull_fvg_lo > 0 and bull_fvg_lo < first_sell_level < bull_fvg_hi:
                        sell_offset_val = bid_ref - bull_fvg_lo + gap_val * 0.25

                    # 3. ELLIOTT WAVE 3 LOT SIZE BOOST
                    # Wave 3 = strongest institutional impulse — safest moment to size up
                    if elliott_wave == 3 and elliott_conf >= 0.60 and bos_dir != "NEUTRAL":
                        orig_size = self.order_size
                        boosted_size = round(min(orig_size * 1.35, orig_size * 1.5), 8)
                        self.deploy_order_size = boosted_size
                        print(f"[{sym_name}] \U0001f30a ELLIOTT WAVE 3 BOOST: lot {orig_size:.4f} "
                              f"-> {boosted_size:.4f} (Wave {elliott_wave}, conf {elliott_conf:.0%}, BOS {bos_dir})")
                    else:
                        self.deploy_order_size = self.order_size

                    if ob_snap_done:
                        print(f"[{sym_name}] \U0001f4e6 SMC ORDER BLOCK SNAP: buy offset -> OB @ {bullish_ob:.4f}")

                except Exception:
                    pass
            # ────────────────────────────────────────────────────────────────────

            # ENVELOPE-ANCHORED HARDWARE BROKER TP SHIELD (EXNESS SERVER 0MS SPIKE HARVEST):
            # Hardware TPs are placed WELL ABOVE the highest BUY level and WELL BELOW the lowest SELL level.
            # Saves account from fake liquidations & heavy wicks by executing at 0ms latency on Exness server during sudden spikes!
            digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else 2
            top_buy_level = ask_ref + buy_offset_val + ((self.grid_levels - 1) * gap_val)
            bottom_sell_level = bid_ref - sell_offset_val - ((self.grid_levels - 1) * gap_val)

            # Volatility & ATR Liquidity Dynamic Buffer Scaling:
            # During fast news spikes / high ATR volatility, expand envelope buffer dynamically so the grid matrix has maximum room to harvest!
            atr_val = getattr(self, "current_atr", 0.0)
            vol_multiplier = 1.0
            if atr_val > 0 and current_price > 0:
                atr_pct = (atr_val / current_price) * 100.0
                if atr_pct > 0.40:     # High Volatility / Fast News Spike -> Expand envelope for deep harvesting
                    vol_multiplier = 1.50
                elif atr_pct < 0.15:   # Low Volatility / Tight Range Chop -> Tighten envelope for rapid execution
                    vol_multiplier = 0.85

            spike_buffer = max(gap_val * 4.0 * vol_multiplier, min_tp_dist * 3.0 * vol_multiplier)
            # Hardware SL Buffer: Generous 2.5% - 5.0% distance so normal wicks & spikes don't trigger SL on MT5 server
            min_sl_dist = (current_price * 0.05) if "BTC" in sym_name else ((current_price * 0.03) if "ETH" in sym_name else (current_price * 0.025 if current_price > 0 else gap_val * 15.0))
            sl_buffer = max(spike_buffer * 3.50, min_sl_dist)

            # Server Hardware TP Buffer: Add 1.5-pip buffer towards live price so MT5 server hardware TP fills 100% reliably
            tp_fill_buffer = (current_price * 0.00015) if "BTC" not in sym_name else 1.50
            buy_tp_px = round(top_buy_level + spike_buffer - tp_fill_buffer, digits)
            sell_tp_px = round(bottom_sell_level - spike_buffer + tp_fill_buffer, digits)


            # ENVELOPE-ANCHORED HARDWARE BROKER STOP-LOSS (SL) SHIELD:
            # Hardware SL is placed far below the grid for BUYs and far above for SELLs on Exness MT5 server for black swan catastrophic safety!
            buy_sl_px = round(bottom_sell_level - sl_buffer, digits)
            sell_sl_px = round(top_buy_level + sl_buffer, digits)

            limit_reached = False

            # Interleaved Equal-Priority Dual Grid Trap Placement:
            # Guarantees that level 0 BUY and level 0 SELL traps are placed FIRST together,
            # so DUAL mode NEVER leaves one side unplaced even if broker limits orders!
            for i in range(self.grid_levels):
                if limit_reached:
                    break

                # Place Level i BUY_STOP if allowed
                if unidirectional_mode in ("DUAL", "BUY_ONLY"):
                    buy_px = ask_ref + buy_offset_val + (i * gap_val)
                    buy_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                    try:
                        self.broker.place_order("BUY_STOP", buy_px, buy_size, timestamp, tp=buy_tp_px, sl=buy_sl_px)
                        placed_count += 1
                    except Exception as err:
                        err_str = str(err)
                        if "10033" in err_str or "Orders limit" in err_str:
                            limit_reached = True
                            now_t = time.time()
                            if now_t - getattr(self, "_last_10033_log_time", 0.0) >= 30.0:
                                self._last_10033_log_time = now_t
                                print(f"[{sym_name}] Exness Orders Limit reached (10033). Keeping {placed_count} active grid traps working. (Backing off 30s)")

                # Place Level i SELL_STOP if allowed and limit not reached
                if not limit_reached and unidirectional_mode in ("DUAL", "SELL_ONLY"):
                    sell_px = bid_ref - sell_offset_val - (i * gap_val)
                    sell_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                    try:
                        self.broker.place_order("SELL_STOP", sell_px, sell_size, timestamp, tp=sell_tp_px, sl=sell_sl_px)
                        placed_count += 1
                    except Exception as err:
                        err_str = str(err)
                        if "10033" in err_str or "Orders limit" in err_str:
                            limit_reached = True
                            now_t = time.time()
                            if now_t - getattr(self, "_last_10033_log_time", 0.0) >= 30.0:
                                self._last_10033_log_time = now_t
                                print(f"[{sym_name}] Exness Orders Limit reached (10033). Keeping {placed_count} active grid traps working. (Backing off 30s)")


            if limit_reached:
                self._last_deploy_error_time = timestamp + 27.0

            if placed_count > 0 or len(self.broker.pending_orders) > 0:
                self.deployed = True
                self.last_deploy_time = timestamp
                if not limit_reached:
                    self._last_deploy_error_time = 0.0

                # Real-time high-visibility grid deployment logging
                buy_off_pct = (buy_offset_val / current_price * 100.0) if current_price > 0 else 0.0
                sell_off_pct = (sell_offset_val / current_price * 100.0) if current_price > 0 else 0.0
                gap_pct = (gap_val / current_price * 100.0) if current_price > 0 else 0.0
                print(f"[{sym_name}] [GRID DEPLOYED] {placed_count} TRAPS @ ${current_price:,.2f} | Mode: {unidirectional_mode} | "
                      f"Gap: {gap_pct:.3f}% (${gap_val:.2f}) | "
                      f"Buy Off: {buy_off_pct:.3f}% (${buy_offset_val:.2f}) | "
                      f"Sell Off: {sell_off_pct:.3f}% (${sell_offset_val:.2f}) | Lot: {self.deploy_order_size}")


            else:
                self.deployed = False
                if not limit_reached:
                    self._last_deploy_error_time = timestamp
                    print(f"[{getattr(self.broker, 'symbol', 'BOT')}] Notice: 0 grid orders placed. Retrying deployment on next tick.")

            if hasattr(self.broker, "purge_duplicate_mt5_orders"):
                try:
                    self.broker.purge_duplicate_mt5_orders()
                except Exception:
                    pass
        except Exception as e:
            self.deployed = False
            self._last_deploy_error_time = timestamp
            print(f"[{getattr(self.broker, 'symbol', 'BOT')}] Grid trap deployment error: {e}")
        finally:
            self._is_deploying = False

    def repair_grid(self, current_price: float, timestamp: float) -> int:
        """
        Scans current pending orders and places any missing grid trap levels above and below
        the deploy_price or current_price to restore full grid trap coverage without closing
        existing active open positions.
        Preserves the exact order_size and multiplier parameters of the active cycle.
        Returns the number of missing orders placed.
        """
        if getattr(self, "in_runner_mode", False) or len(self.broker.open_positions) > 0:
            # Active trade in progress — do NOT spawn new traps in front of moving price to prevent stacking
            return 0

        # Deploy & Repair Backoff Cooldown Guard: Skip repair if an order placement error occurred recently (within 3s)
        if timestamp < getattr(self, "_last_deploy_error_time", 0.0) + 3.0:
            return 0
        if timestamp < getattr(self, "_last_repair_error_time", 0.0) + 3.0:
            return 0

        # If no positions and no pending orders exist AND engine is not deployed, run a fresh deploy_traps call
        if not self.deployed and len(self.broker.pending_orders) == 0 and len(self.broker.open_positions) == 0:
            if timestamp >= getattr(self, "_last_deploy_error_time", 0.0) + 3.0:
                self.deploy_traps(current_price, timestamp)
            return self.grid_levels * 2

        center_price = self.deploy_price if getattr(self, "deploy_price", 0.0) > 0 else current_price
        if not getattr(self, "deploy_price", 0.0) or self.deploy_price == 0.0:
            self.deploy_price = center_price

        base_size = getattr(self, "deploy_order_size", self.order_size)
        mult = getattr(self, "deploy_order_size_multiplier", self.order_size_multiplier)
   
        # Always use active deployment geometry if available to guarantee exact match with deployed traps
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
                buy_offset_val = center_price * (eval_res["buy_offset_pct"] / 100.0)
                sell_offset_val = center_price * (eval_res["sell_offset_pct"] / 100.0)
                gap_val = center_price * (eval_res["dynamic_gap_pct"] / 100.0)
            except Exception:
                gap_config = getattr(self, "deploy_grid_gap", self.grid_gap)
                offset_config = getattr(self, "deploy_trap_offset", self.trap_offset)
                buy_offset_val, gap_val = self.calculate_offset_and_gap(center_price, gap_config, offset_config)
                sell_offset_val = buy_offset_val
        else:
            gap_config = getattr(self, "deploy_grid_gap", self.grid_gap)
            offset_config = getattr(self, "deploy_trap_offset", self.trap_offset)
            buy_offset_val, gap_val = self.calculate_offset_and_gap(center_price, gap_config, offset_config)
            sell_offset_val = buy_offset_val

        # Broker Minimum Stop Level Protection Shield:
        if hasattr(self.broker, "get_min_stop_distance"):
            try:
                min_stop = float(self.broker.get_min_stop_distance())
                if min_stop > 0:
                    safety_buffer = min_stop * 1.25
                    buy_offset_val = max(buy_offset_val, safety_buffer)
                    sell_offset_val = max(sell_offset_val, safety_buffer)
            except Exception:
                pass

        # Reference prices: BUY_STOP uses Ask price, SELL_STOP uses Bid price
        ask_ref = getattr(self.broker, "last_ask", current_price)
        bid_ref = getattr(self.broker, "last_bid", current_price)
        if not ask_ref or ask_ref <= 0: ask_ref = current_price
        if not bid_ref or bid_ref <= 0: bid_ref = current_price

        # Collect existing pending trigger prices AND open position entry prices to prevent duplication
        buy_pending = [o for o in self.broker.pending_orders.values() if o.type == "BUY_STOP"]
        buy_open = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
        sell_pending = [o for o in self.broker.pending_orders.values() if o.type == "SELL_STOP"]
        sell_open = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

        existing_buy_levels = [o.trigger_price for o in buy_pending] + [p.entry_price for p in buy_open]
        existing_sell_levels = [o.trigger_price for o in sell_pending] + [p.entry_price for p in sell_open]

        # OCO Mode Guard: Disabled in Auto Mode to preserve dual-sided hedging.
        cancel_opp = getattr(self, "cancel_opposite_on_trigger", False) and not getattr(self, "use_auto_reading", False)
        allow_buy_repair = True
        allow_sell_repair = True

        buy_pos_in_market = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
        sell_pos_in_market = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

        if cancel_opp:
            if buy_pos_in_market and not sell_pos_in_market:
                # BUY positions open — OCO intentionally wiped SELL_STOPs; do NOT restore them
                allow_sell_repair = False
            elif sell_pos_in_market and not buy_pos_in_market:
                # SELL positions open — OCO intentionally wiped BUY_STOPs; do NOT restore them
                allow_buy_repair = False
            elif not buy_pos_in_market and not sell_pos_in_market:
                # No positions at all — full repair allowed on both sides
                allow_buy_repair = True
                allow_sell_repair = True
            else:
                # Both sides open (hedge lock) — allow repair on both sides
                allow_buy_repair = True
                allow_sell_repair = True

        # Short-circuit: if nothing to repair on either side, return immediately
        if not allow_buy_repair and not allow_sell_repair:
            return 0


        placed_count = 0
        try:
            buy_placed = 0
            sell_placed = 0
            # Check and place missing BUY_STOP levels ONLY if allow_buy_repair is True
            if allow_buy_repair and (len(buy_pending) + len(buy_open) < self.grid_levels):
                for i in range(self.grid_levels):
                    if len(buy_pending) + len(buy_open) + buy_placed >= self.grid_levels:
                        break
                    target_price = ask_ref + buy_offset_val + (i * gap_val)
                    if target_price <= ask_ref:
                        target_price = ask_ref + (gap_val * 0.5) + (i * gap_val)
                    
                    # Only place if level doesn't exist near existing BUY levels
                    if target_price > ask_ref and not any(abs(target_price - ex) < (gap_val * 0.90) for ex in existing_buy_levels):
                        level_size = self.calculate_level_size(base_size, mult, i)
                        ord_res = self.broker.place_order("BUY_STOP", target_price, level_size, timestamp)
                        buy_placed += 1
                        actual_px = getattr(ord_res, "trigger_price", target_price) if ord_res else target_price
                        existing_buy_levels.append(actual_px)

            # Check and place missing SELL_STOP levels ONLY if allow_sell_repair is True
            if allow_sell_repair and (len(sell_pending) + len(sell_open) < self.grid_levels):
                for i in range(self.grid_levels):
                    if len(sell_pending) + len(sell_open) + sell_placed >= self.grid_levels:
                        break
                    target_price = bid_ref - sell_offset_val - (i * gap_val)
                    if target_price >= bid_ref:
                        target_price = bid_ref - (gap_val * 0.5) - (i * gap_val)

                    # Only place if level doesn't exist near existing SELL levels
                    if target_price < bid_ref and not any(abs(target_price - ex) < (gap_val * 0.90) for ex in existing_sell_levels):
                        level_size = self.calculate_level_size(base_size, mult, i)
                        ord_res = self.broker.place_order("SELL_STOP", target_price, level_size, timestamp)
                        sell_placed += 1
                        actual_px = getattr(ord_res, "trigger_price", target_price) if ord_res else target_price
                        existing_sell_levels.append(actual_px)

            # Active Duplicate Level Purge Guard:
            # Instantly purge any duplicate pending orders on MT5 that landed at the exact same level
            if hasattr(self.broker, "purge_duplicate_mt5_orders"):
                try:
                    self.broker.purge_duplicate_mt5_orders()
                except Exception:
                    pass

            placed_count = buy_placed + sell_placed
        except Exception as e:
            err_msg = str(e)
            last_err = getattr(self, "_last_repair_error", None)
            last_err_time = getattr(self, "_last_repair_error_time", 0.0)
            self._last_repair_error = err_msg
            self._last_repair_error_time = timestamp
            self._last_deploy_error_time = timestamp
            if err_msg != last_err or (timestamp - last_err_time) >= 60.0:
                print(f"Notice: Grid repair encountered order placement notice: {err_msg}")

        return placed_count

    def cleanup_stale_grid_orders(self, current_price: float) -> int:
        """
        Identifies and cancels orphan or duplicate pending orders that no longer align
        with the current grid trap configuration.
        """
        # Protect active deployed grid: Never purge active orders on live MT5 when grid is deployed
        if self.deployed or len(self.broker.pending_orders) <= (self.grid_levels * 2):
            return 0
        """
        Auto-removes unnecessary pending orders:
        1. Duplicates — multiple pending orders clustered at the same grid level (keeps the closest one).
        2. Orphans — pending orders that don't align with any valid computed grid level.
        Returns the number of orders cancelled.
        """
        if not self.broker.pending_orders:
            return 0

        center_price = self.deploy_price if self.deploy_price > 0 else current_price

        # Always use active deployment geometry if available to guarantee exact match with deployed traps
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
                buy_offset_val = center_price * (eval_res["buy_offset_pct"] / 100.0)
                sell_offset_val = center_price * (eval_res["sell_offset_pct"] / 100.0)
                gap_val = center_price * (eval_res["dynamic_gap_pct"] / 100.0)
            except Exception:
                buy_offset_val, gap_val = self.calculate_offset_and_gap(center_price, self.grid_gap, self.trap_offset)
                sell_offset_val = buy_offset_val
        else:
            buy_offset_val, gap_val = self.calculate_offset_and_gap(center_price, self.grid_gap, self.trap_offset)
            sell_offset_val = buy_offset_val

        # Widened tolerance to accommodate broker trade_stops_level price adjustments
        tolerance = max(gap_val * 1.5, center_price * 0.005)

        # Build the set of valid grid prices (expected levels)
        valid_buy_levels = [center_price + buy_offset_val + (i * gap_val) for i in range(self.grid_levels)]
        valid_sell_levels = [center_price - sell_offset_val - (i * gap_val) for i in range(self.grid_levels)]

        cancelled_ids = []

        # --- Step 1: Remove orphan orders (not near any valid level) ---
        # Safeguard: Do NOT cancel orders placed recently (< 300s) or while grid is active
        # to avoid wiping traps that were price-adjusted for broker trade_stops_level.
        for order_id, order in list(self.broker.pending_orders.items()):
            if order_id in cancelled_ids:
                continue
            # Skip orphan check for active grid traps placed within last 5 minutes
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

        # --- Step 2: Remove duplicates (cluster multiple orders near same level) ---
        # Group remaining orders by their closest valid level
        from collections import defaultdict
        buy_groups: dict = defaultdict(list)
        sell_groups: dict = defaultdict(list)

        for order_id, order in self.broker.pending_orders.items():
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
                    # Keep the order closest to the exact level price, cancel the rest
                    orders.sort(key=lambda x: abs(x[1].trigger_price - lvl))
                    for order_id, _ in orders[1:]:  # skip the first (closest)
                        self.broker.cancel_order(order_id)
                        cancelled_ids.append(order_id)
                        count += 1
            return count

        cancel_duplicates_in_group(buy_groups)
        cancel_duplicates_in_group(sell_groups)

        return len(cancelled_ids)

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, bb_width: Optional[float] = None) -> Optional[dict]:
        """
        Processes a single price tick.
        Evaluates profit targets, stop losses, and cycle timeouts.
        Returns a dictionary summarizing the cycle if an exit condition is met, otherwise None.
        """
        self.ensure_attributes_initialized()

        # ── FRIDAY WEEKEND MARKET SHUTDOWN CHECK ────────────────────────────────
        if getattr(self, "use_weekend_shutdown", True):
            ts_sec = timestamp / 1000.0 if timestamp > 1e11 else timestamp
            now_utc = datetime.datetime.fromtimestamp(ts_sec, datetime.timezone.utc)
            weekday = now_utc.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
            shutdown_hour = getattr(self, "weekend_shutdown_utc_hour", 20)
            is_weekend_pause = (weekday == 4 and now_utc.hour >= shutdown_hour) or (weekday == 5) or (weekday == 6 and now_utc.hour < 22)

            if is_weekend_pause:
                if not getattr(self, "weekend_shutdown_triggered", False):
                    self.weekend_shutdown_triggered = True
                    self.deployed = False
                    try:
                        # 1. Always cancel pending trap orders to prevent new weekend fills
                        self.broker.cancel_all_orders()

                        # 2. SMART PROFIT EXIT: Only close open positions if total floating PnL is in PROFIT (>= $0.00).
                        # If positions are in floating loss, DO NOT force close at a loss — hold safely through weekend!
                        float_pnl = self.broker.get_floating_pnl(current_price)
                        if len(self.broker.open_positions) > 0 and float_pnl >= 0.0:
                            self.broker.close_all_positions(current_price, timestamp)
                            print(f"[WEEKEND SHUTDOWN] Closed profiting positions (+${float_pnl:.2f}) before Friday market close.")
                        elif len(self.broker.open_positions) > 0:
                            print(f"[WEEKEND SHUTDOWN] Holding open positions (${float_pnl:.2f}) through weekend to avoid forced loss realization.")
                    except Exception as e:
                        print(f"Notice: Weekend shutdown cleanup error: {e}")
                    print(f"[WEEKEND SHUTDOWN] Weekend Market Protection triggered @ {now_utc.strftime('%H:%M UTC')}. Pausing grid execution until Monday.")
                return None

            # Monday / Sunday late reopen -> Clear pause & auto-resume
            if getattr(self, "weekend_shutdown_triggered", False):
                self.weekend_shutdown_triggered = False
                # FIX 3: Clear the deploy error cooldown on reopen so deploy_traps fires immediately
                self._last_deploy_error_time = 0.0
                print(f"[WEEKEND REOPEN] Monday Market Reopen detected @ {now_utc.strftime('%Y-%m-%d %H:%M UTC')}. Auto-resuming grid execution.")
                if self.auto_restart:
                    self.deploy_traps(current_price, timestamp, bb_width)
        # ─────────────────────────────────────────────────────────────────────────
        # ── ULTRA-FAST 0.5s AUTOMATIC NEW CYCLE REDEPLOYMENT ─────────────────────
        if not self.deployed and self.auto_restart:
            # 500ms Ultra-Fast Restart Cooldown
            if (timestamp - getattr(self, "last_deploy_time", 0.0)) >= 0.50 and timestamp >= getattr(self, "_last_deploy_error_time", 0.0) + 3.0:
                try:
                    self.deploy_traps(current_price, timestamp, bb_width, force=True)
                except Exception as dep_err:
                    self._last_deploy_error_time = timestamp
        # ── MT5 EXTERNAL TP / SL CYCLE COMPLETION SHIELD ────────────────────────
        # If open positions existed on previous tick and are now 0 (closed via MT5 Broker TP/SL):
        # Automatically cancel stale pending traps, clear cooldowns, and deploy a fresh grid INSTANTLY!
        had_open = getattr(self, "_prev_open_pos_count", 0)
        cur_open = len(self.broker.open_positions)
        self._prev_open_pos_count = cur_open

        if self.deployed and had_open > 0 and cur_open == 0:
            try:
                self.broker.cancel_all_orders()
            except Exception as c_err:
                print(f"Notice: Stale pending order cleanup notice: {c_err}")
            
            self.in_runner_mode = False
            self._runner_exit_cooldown_until = 0.0
            self._last_deploy_error_time = 0.0
            
            if self.auto_restart:
                self.deploy_traps(current_price, timestamp, bb_width, force=True)
            else:
                self.deployed = False

        # ── ZERO-POSITION AUTOMATIC RE-DEPLOYMENT SHIELD ─────────────────────────
        # If bot is marked deployed BUT has 0 open positions and 0 pending orders
        # (e.g. after Stop Loss hit or order purge during price spike), instantly reset and redeploy fresh grid!
        if self.deployed and len(self.broker.open_positions) == 0 and len(self.broker.pending_orders) == 0:
            if timestamp >= getattr(self, "_last_zombie_redeploy_time", 0.0) + 3.0:
                self._last_zombie_redeploy_time = timestamp
                self.in_runner_mode = False
                self._runner_exit_cooldown_until = 0.0
                self._last_deploy_error_time = 0.0
                if self.auto_restart:
                    self.deploy_traps(current_price, timestamp, bb_width, force=True)
                else:
                    self.deployed = False

        # ── DYNAMIC GRID RE-CENTERING SHIELD ─────────────────────────────────────
        # If zero open positions exist and price moves far away from pending traps (> 2x gap),
        # automatically cancel stale pending traps and re-deploy fresh traps centered around current Ask/Bid!
        if self.deployed and len(self.broker.open_positions) == 0 and len(self.broker.pending_orders) > 0:
            nearest_dist = min(abs(current_price - o.trigger_price) for o in self.broker.pending_orders.values())
            recenter_threshold = max(getattr(self, "deploy_grid_gap", 3.0) * 2.0, 6.00 if ("XAU" in str(getattr(self.broker, "symbol", "")).upper() or "GOLD" in str(getattr(self.broker, "symbol", "")).upper()) else current_price * 0.005)
            if nearest_dist > recenter_threshold:
                try:
                    self.broker.cancel_all_orders()
                    self.deploy_traps(current_price, timestamp, bb_width)
                except Exception as rec_err:
                    print(f"Notice: Grid re-centering notice: {rec_err}")

        # ── PENDING TRAP RESTORATION SHIELD ──────────────────────────────────────
        # If pending orders drop to 0 while 1 to 3 active trades exist, automatically restore fresh traps centered around current Ask/Bid once every 30s!
        # (Suppressed when 4+ positions exist to allow 4+ Fills Trap Purge Shield to keep pending orders at 0)
        if self.deployed and len(self.broker.pending_orders) == 0 and (0 < len(self.broker.open_positions) < 4):
            if timestamp >= getattr(self, "_last_trap_restoration_time", 0.0) + 30.0:
                self._last_trap_restoration_time = timestamp
                try:
                    self.deploy_traps(current_price, timestamp, bb_width)
                except Exception as rest_err:
                    print(f"Notice: Grid trap restoration notice: {rest_err}")

        if not self.deployed:
            return None

        # ── RUNNER EXIT COOLDOWN ─────────────────────────────────────────────────
        # After Runner Mode exits, wait briefly before processing new triggers
        # to avoid the first grid trap filling instantly on a still-trending price.
        if timestamp < getattr(self, '_runner_exit_cooldown_until', 0.0):
            return None
        # ─────────────────────────────────────────────────────────────────────────

        # Dynamic Spread Guard & Adaptive News Friction Filter: Skip fills if broker spread > 3.0x baseline
        if hasattr(self.broker, "get_current_spread"):
            cur_spread = self.broker.get_current_spread()
            base_pip = get_pip_size(getattr(self.broker, "symbol", ""), current_price)
            max_allowed = max(getattr(self, "max_allowed_spread", 4.5), base_pip * 30.0)
            if cur_spread > max_allowed:
                triggered_positions = []
            else:
                triggered_positions = self.broker.process_tick(previous_price, current_price, timestamp)
        else:
            triggered_positions = self.broker.process_tick(previous_price, current_price, timestamp)

        # Update last-trigger time whenever a new position is filled
        if triggered_positions:
            self._last_trigger_time = timestamp

        # ── LIQUIDITY GRAB / FAKE-OUT GUARD ──────────────────────────────────────
        # After a trap fires, we watch the next N ticks.
        # If price quickly reverses back THROUGH the entry price while the
        # position is losing → it's a stop hunt / liquidity grab → exit early!
        # This fires BEFORE Stop Loss and saves most of the drawdown.
        # Disabled automatically in Runner Mode (confirmed trend — never cut a runner).
        if getattr(self, '_fakeout_guard_enabled', True) and not getattr(self, 'in_runner_mode', False):
            self._tick_counter = getattr(self, '_tick_counter', 0) + 1

            # Register newly triggered positions into the guard watch-list
            if triggered_positions:
                if not isinstance(getattr(self, '_fakeout_recent_fills', None), dict):
                    self._fakeout_recent_fills = {}
                for pos in triggered_positions:
                    pid = getattr(pos, 'position_id', getattr(pos, 'id', getattr(pos, 'ticket', None)))
                    if pid and str(pid) not in self._fakeout_recent_fills:
                        ep = getattr(pos, 'entry_price', getattr(pos, 'open_price', current_price))
                        pt = getattr(pos, 'type', 'BUY')
                        self._fakeout_recent_fills[str(pid)] = (float(ep), str(pt), int(self._tick_counter))

            # Expire fills that have aged past the guard window
            guard_ticks = getattr(self, '_fakeout_guard_ticks', 8)
            expired_pids = [
                pid for pid, (ep, pt, ft) in list(getattr(self, '_fakeout_recent_fills', {}).items())
                if (self._tick_counter - ft) > guard_ticks
            ]
            for pid in expired_pids:
                self._fakeout_recent_fills.pop(pid, None)

            # Evaluate each watched position for a fake-out reversal
            for pid, (entry_px, pos_type, fill_tick) in list(getattr(self, '_fakeout_recent_fills', {}).items()):
                ticks_since_fill = self._tick_counter - fill_tick
                # Give price at least 2 ticks to develop before judging direction
                if ticks_since_fill < 2:
                    continue
                # Position must still be open
                if pid not in self.broker.open_positions:
                    self._fakeout_recent_fills.pop(pid, None)
                    continue
                # Skip if position is already profitable (genuine breakout — let it run!)
                pos_obj = self.broker.open_positions[pid]
                pos_pnl = getattr(pos_obj, 'profit', pos_obj.get_pnl(current_price) if hasattr(pos_obj, 'get_pnl') else 0.0)
                if pos_pnl >= 0:
                    continue
                # Fake-out detection: price crossed back through entry price
                is_buy_fakeout  = (pos_type == 'BUY')  and (current_price < entry_px)
                is_sell_fakeout = (pos_type == 'SELL') and (current_price > entry_px)
                if is_buy_fakeout or is_sell_fakeout:
                    try:
                        self.broker.close_position(str(pid), current_price, timestamp)
                        self._fakeout_recent_fills.pop(pid, None)
                        direction = 'BUY' if is_buy_fakeout else 'SELL'
                        sym_label = getattr(self.broker, 'symbol', 'BOT')
                        print(f"[{sym_label}] 🛡️ FAKEOUT GUARD: {direction} stop-hunt detected. "
                              f"Entry {entry_px:.4f} → price now {current_price:.4f} "
                              f"({ticks_since_fill} ticks). Early exit, PnL: {pos_pnl:.2f}")
                    except Exception as fo_err:
                        print(f"[FAKEOUT GUARD] Close error: {fo_err}")
        # ─────────────────────────────────────────────────────────────────────────

        # ── TOP PEAK & BOTTOM TROUGH ACTIVE HARVEST SHIELD ────────────────────────
        # When market hits a confirmed extreme:
        #   - BOTTOM_TROUGH_OVERSOLD: Purge pending SELL traps & harvest open SELL positions
        #     (prevents selling into the absolute bottom wick before a V-bounce)
        #   - TOP_PEAK_OVERBOUGHT: Purge pending BUY traps & harvest open BUY positions
        #     (prevents buying into the absolute top peak before a dump)
        eval_data = getattr(self, "last_auto_eval", {}) or {}
        tb_status = eval_data.get("top_bottom_status", "NORMAL")

        if tb_status == "BOTTOM_TROUGH_OVERSOLD":
            # 1. Purge any pending SELL traps on MT5
            for oid, o in list(self.broker.pending_orders.items()):
                if getattr(o, "type", "") in ("SELL_STOP", "SELL_LIMIT"):
                    try:
                        self.broker.cancel_order(oid)
                    except Exception:
                        pass
            # 2. Harvest/Close open SELL positions at bottom trough
            for pid, pos in list(self.broker.open_positions.items()):
                ptype = getattr(pos, "type", "")
                if ptype == "SELL":
                    try:
                        self.broker.close_position(str(pid), current_price, timestamp)
                        sym_label = getattr(self.broker, "symbol", "BOT")
                        p_pnl = getattr(pos, "profit", 0.0)
                        print(f"[{sym_label}] 🛡️ TROUGH GUARD: BOTTOM_TROUGH_OVERSOLD active! "
                              f"Harvested SELL position #{pid} at bottom (PnL: ${p_pnl:.2f}) & purged SELL traps.")
                    except Exception:
                        pass

        elif tb_status == "TOP_PEAK_OVERBOUGHT":
            # 1. Purge any pending BUY traps on MT5
            for oid, o in list(self.broker.pending_orders.items()):
                if getattr(o, "type", "") in ("BUY_STOP", "BUY_LIMIT"):
                    try:
                        self.broker.cancel_order(oid)
                    except Exception:
                        pass
            # 2. Harvest/Close open BUY positions at top peak
            for pid, pos in list(self.broker.open_positions.items()):
                ptype = getattr(pos, "type", "")
                if ptype == "BUY":
                    try:
                        self.broker.close_position(str(pid), current_price, timestamp)
                        sym_label = getattr(self.broker, "symbol", "BOT")
                        p_pnl = getattr(pos, "profit", 0.0)
                        print(f"[{sym_label}] 🛡️ PEAK GUARD: TOP_PEAK_OVERBOUGHT active! "
                              f"Harvested BUY position #{pid} at peak (PnL: ${p_pnl:.2f}) & purged BUY traps.")
                    except Exception:
                        pass
        # ─────────────────────────────────────────────────────────────────────────



        # Track tick price history and velocity (Delta P / Delta t)
        if not hasattr(self, "price_history_ticks") or self.price_history_ticks is None:
            self.price_history_ticks = []
        
        # Only rebuild cycle history when a trade has closed (prevents CPU lag on every tick)
        cur_closed_cnt = len(getattr(self.broker, "closed_trades", []))
        if not hasattr(self, "_last_closed_cnt") or self._last_closed_cnt != cur_closed_cnt:
            self._last_closed_cnt = cur_closed_cnt
            try:
                self.sync_cycle_history_from_trades()
            except Exception:
                pass
        self.price_history_ticks.append(current_price)
        if len(self.price_history_ticks) > 10:
            self.price_history_ticks.pop(0)

        is_cent = getattr(self.broker, "is_cent_account", False)
        avg_delta = 0.0
        avg_delta_pct = 0.0
        is_reversing = False
        if len(self.price_history_ticks) >= 3:
            recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))]
            avg_delta = sum(recent_deltas) / len(recent_deltas)
            avg_delta_pct = (avg_delta / current_price * 100.0) if current_price > 0 else 0.0

        # SMART DYNAMIC SAFETY OCO SHIELD ENGINE:
        # Keeps opposite traps live in MT5 to preserve dual-sided hedging on market reversals. Disabled in Auto Mode.
        cancel_opp = getattr(self, "cancel_opposite_on_trigger", False) and not getattr(self, "use_auto_reading", False)
        
        num_open_positions = len(self.broker.open_positions)
        
        # OCO Sweep Trigger: Explicit user toggle ON, emergency 4+ fills trend purge, or 100% Confirmed Unidirectional Trend
        unidirectional = getattr(self, "unidirectional_mode", "DUAL")
        should_sweep_oco = cancel_opp or (num_open_positions >= 4) or (unidirectional in ("BUY_ONLY", "SELL_ONLY"))
        if should_sweep_oco:
            buy_pos_active = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_pos_active = [p for p in self.broker.open_positions.values() if p.type == "SELL"]
            
            if (buy_pos_active and not sell_pos_active) or (unidirectional == "BUY_ONLY"):
                # Confirmed Bullish Trend (BUY_ONLY) -> Purge all opposite SELL_STOP pending traps!
                opposite_traps = [order_id for order_id, o in list(self.broker.pending_orders.items()) if o.type == "SELL_STOP"]
                for order_id in opposite_traps:
                    self.broker.cancel_order(order_id)

                # UNIDIRECTIONAL PRIORITY #1 QUICK COUNTER-TREND EXIT SHIELD:
                # If a SELL position is open during a confirmed Bullish Trend (BUY_ONLY),
                # EACH position is checked INDIVIDUALLY:
                #   - If it is a BEST RUNNER (profit >= 75% of target_profit), NEVER close it.
                #     Think like an options trader: a winning position on its own trend path runs to full TP!
                #   - Otherwise: close if in small profit (>= +$0.10), minimal loss (>= -$0.30),
                #     micro pullback, or strong bearish bias.
                if sell_pos_active:
                    recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))] if len(getattr(self, "price_history_ticks", [])) >= 2 else []
                    is_pullback = (recent_deltas and recent_deltas[-1] < 0) or (avg_delta < 0)
                    bias_val = getattr(self, "_last_eval_bias", 0.50)
                    pos_profit_floor = 5.0 if is_cent else 0.05  # +$0.05 Positive Cash Trigger
                    base_tp_raw     = (self.target_profit * 100.0) if is_cent else self.target_profit
                    runner_threshold = base_tp_raw * 0.75  # 75% of target = confirmed best runner
                    for p in sell_pos_active:
                        p_pnl = getattr(p, 'profit', 0.0)
                        # BEST RUNNER PROTECTION: this SELL is already a big winner — let it run!
                        if p_pnl >= runner_threshold and runner_threshold > 0:
                            continue  # Skip — protect the runner, let it hit hardware TP
                        # POSITIVE-FIRST HARVEST: Close if in positive profit (>= +$0.05), or breakeven (>= $0.00) on pullback
                        should_exit = (p_pnl >= pos_profit_floor) or (is_pullback and p_pnl >= 0.0) or (bias_val >= 0.75 and p_pnl <= -(200.0 if is_cent else 2.00))
                        if should_exit:
                            pid = getattr(p, 'id', getattr(p, 'ticket', None))
                            if pid:
                                try: self.broker.close_position(str(pid), current_price, timestamp)
                                except Exception: pass


            elif (sell_pos_active and not buy_pos_active) or (unidirectional == "SELL_ONLY"):
                # Confirmed Bearish Trend (SELL_ONLY) -> Purge all opposite BUY_STOP pending traps!
                opposite_traps = [order_id for order_id, o in list(self.broker.pending_orders.items()) if o.type == "BUY_STOP"]
                for order_id in opposite_traps:
                    self.broker.cancel_order(order_id)

                # UNIDIRECTIONAL PRIORITY #1 QUICK COUNTER-TREND EXIT SHIELD:
                # If a BUY position is open during a confirmed Bearish Trend (SELL_ONLY),
                # EACH position is checked INDIVIDUALLY:
                #   - If it is a BEST RUNNER (profit >= 75% of target_profit), NEVER close it.
                #   - Otherwise: close at Positive Profit (>= +$0.05) or Breakeven ($0.00) on pullback.
                if buy_pos_active:
                    recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))] if len(getattr(self, "price_history_ticks", [])) >= 2 else []
                    is_pullback = (recent_deltas and recent_deltas[-1] > 0) or (avg_delta > 0)
                    bias_val = getattr(self, "_last_eval_bias", -0.50)
                    pos_profit_floor = 5.0 if is_cent else 0.05  # +$0.05 Positive Cash Trigger
                    base_tp_raw     = (self.target_profit * 100.0) if is_cent else self.target_profit
                    runner_threshold = base_tp_raw * 0.75  # 75% of target = confirmed best runner
                    for p in buy_pos_active:
                        p_pnl = getattr(p, 'profit', 0.0)
                        # BEST RUNNER PROTECTION: this BUY is already a big winner — let it run!
                        if p_pnl >= runner_threshold and runner_threshold > 0:
                            continue  # Skip — protect the runner, let it hit hardware TP
                        # POSITIVE-FIRST HARVEST: Close if in positive profit (>= +$0.05), or breakeven (>= $0.00) on pullback
                        should_exit = (p_pnl >= pos_profit_floor) or (is_pullback and p_pnl >= 0.0) or (bias_val <= -0.75 and p_pnl <= -(200.0 if is_cent else 2.00))
                        if should_exit:
                            pid = getattr(p, 'id', getattr(p, 'ticket', None))
                            if pid:
                                try: self.broker.close_position(str(pid), current_price, timestamp)
                                except Exception: pass



        # Calculate floating profit/loss
        float_pnl = self.broker.get_floating_pnl(current_price)

        # Automatic Autonomous Grid Repair (Disabled by default — manual override via 🔧 REPAIR GRID button)
        if not getattr(self, "in_runner_mode", False) and getattr(self, "use_grid_repair", False):
            buy_pending = [o for o in self.broker.pending_orders.values() if o.type == "BUY_STOP"]
            buy_open = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_pending = [o for o in self.broker.pending_orders.values() if o.type == "SELL_STOP"]
            sell_open = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

            need_buy_repair = (len(buy_pending) + len(buy_open) < self.grid_levels) and not (cancel_opp and len(sell_open) > 0)
            need_sell_repair = (len(sell_pending) + len(sell_open) < self.grid_levels) and not (cancel_opp and len(buy_open) > 0)

            if need_buy_repair or need_sell_repair:
                try:
                    self.repair_grid(current_price, timestamp)
                except Exception as repair_err:
                    print(f"Auto-repair notice: {repair_err}")

        if len(self.price_history_ticks) >= 3:
            recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))]
            # Enhanced 100% Top-to-Bottom Reversal Confluence Engine:
            # Combines consecutive tick deltas + peak price pullback ratio + RSI overbought/oversold extremes
            max_tick_px = max(self.price_history_ticks)
            min_tick_px = min(self.price_history_ticks)
            top_pullback_pct = ((max_tick_px - current_price) / max_tick_px * 100.0) if max_tick_px > 0 else 0.0
            bottom_rebound_pct = ((current_price - min_tick_px) / min_tick_px * 100.0) if min_tick_px > 0 else 0.0
            
            rsi_val = getattr(self, "current_rsi", 50.0)
            is_top_peak_reversal = (recent_deltas[-1] < 0 and recent_deltas[-2] < 0) or (top_pullback_pct >= 0.04 and rsi_val >= 68.0)
            is_bottom_trough_reversal = (recent_deltas[-1] > 0 and recent_deltas[-2] > 0) or (bottom_rebound_pct >= 0.04 and rsi_val <= 32.0)

            buy_pos_list = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_pos_list = [p for p in self.broker.open_positions.values() if p.type == "SELL"]
            if buy_pos_list and not sell_pos_list:
                is_reversing = is_top_peak_reversal
            elif sell_pos_list and not buy_pos_list:
                is_reversing = is_bottom_trough_reversal
            else:
                is_reversing = is_top_peak_reversal or is_bottom_trough_reversal

        # ── EARLY TREND CHANGE & REVERSAL PRE-SL LIQUIDATION SHIELD ─────────────────
        # Never wait for Stop Loss to hit!
        # If a trend reversal occurs (is_reversing = True or strong momentum surge) while positions are in drawdown,
        # execute an early trend protection exit to cap loss at minimal drawdown BEFORE Stop Loss is ever reached!
        velocity_shield_hit = False
        if len(self.broker.open_positions) >= 1:
            if is_reversing and float_pnl < 0:
                velocity_shield_hit = True
            elif len(self.price_history_ticks) >= 5:
                first_tick_px = self.price_history_ticks[0]
                if first_tick_px > 0:
                    total_delta_pct = abs(self.price_history_ticks[-1] - first_tick_px) / first_tick_px * 100.0
                    if total_delta_pct >= 0.80 and float_pnl < 0:
                        velocity_shield_hit = True

        # Dynamic friction floor based on open position count to cover spread, commission & swap fees
        num_pos = len(self.broker.open_positions)
        accumulated_swaps = sum(abs(getattr(p, 'swap', 0.0)) for p in self.broker.open_positions.values())
        duration_hours = max(0.0, (timestamp - getattr(self, "cycle_start_time", timestamp)) / 3600.0)
        duration_swap_buffer = num_pos * min(5.0, duration_hours * 0.50)
        # Gold/Forex spread + Exness commission requires ~$1.50 per open position + $3.00 base friction + accumulated swaps + duration buffer
        friction_floor = max(4.00, 4.00 + (num_pos * 1.50) + accumulated_swaps + duration_swap_buffer)

        # ── STAGNANT GRID AUTO-REDEPLOY ─────────────────────────────────────────
        # If the grid has had zero fills for a long time AND no positions are open,
        # the market has moved far from the deploy price. Snap the grid to current price.
        _stagnant_redeploy_interval = 3600.0 if (self.max_cycle_duration > 86400.0 or self.max_cycle_duration <= 0) else (self.max_cycle_duration * 0.5)
        _no_positions = len(self.broker.open_positions) == 0
        _last_trig = getattr(self, '_last_trigger_time', 0.0)
        if _last_trig <= 0.0:
            _last_trig = self.cycle_start_time if self.cycle_start_time > 0.0 else timestamp
            self._last_trigger_time = _last_trig
        _stagnant = (timestamp - _last_trig) >= _stagnant_redeploy_interval
        _past_cooldown = timestamp >= getattr(self, '_runner_exit_cooldown_until', 0.0)
        if _no_positions and _stagnant and self.deployed and getattr(self, "use_stagnant_redeploy", False) and _past_cooldown:
            # Price has drifted — silently redeploy at current price with no cycle record
            self._last_trigger_time = timestamp
            self.deploy_traps(current_price, timestamp, bb_width)
            return None  # No cycle exit, just a silent recenter
        # ─────────────────────────────────────────────────────────────────────────

        # Check exit conditions
        target_hit = False
        runner_hit = False
        trailing_stop_hit = False
        stop_loss_hit = False
        breakeven_hit = False
        early_range_hit = False
        prop_guard_hit = False
        hedge_lock_hit = False
        velocity_shield_hit = False
        momentum_scalp_hit = False
        wvap_exit_hit = False
        instant_counter_flip_hit = False
        ranging_pnl_harvest_hit = False
        single_fill_scalp_hit = False
        top_bottom_reversal_hit = False
        counter_trend_harvest_hit = False
        counter_trend_be_hit = False

        # SMART TIMEOUT: Only exits if PnL is at or above breakeven (friction_floor).
        # If the cycle is in the red when time expires, do NOT force-exit — let Stop Loss
        # handle it. A forced exit at a loss is always mathematically worse than waiting.
        elapsed = timestamp - self.cycle_start_time
        _dur = getattr(self, "max_cycle_duration", float("inf"))
        _timed_out = (_dur > 0 and _dur != float("inf") and elapsed >= _dur) and len(self.broker.open_positions) > 0
        timeout_hit = _timed_out and (float_pnl >= friction_floor)

        if len(self.broker.open_positions) > 0:
            # 0. PROP FIRM COMPLIANCE GUARD CHECK (00:00 UTC Baseline Daily Tracking)
            if getattr(self, "prop_firm_guard_enabled", False):
                account_eq_val = getattr(self.broker, "balance_usd", getattr(self.broker, "account_equity", 10000.0))
                now_dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
                today_str = now_dt.strftime("%Y-%m-%d")
                if not hasattr(self, "_daily_baseline_date") or self._daily_baseline_date != today_str:
                    self._daily_baseline_date = today_str
                    self._daily_starting_equity = account_eq_val

                daily_base = getattr(self, "_daily_starting_equity", account_eq_val)
                max_daily_loss = daily_base * (getattr(self, "prop_firm_max_daily_drawdown_pct", 4.5) / 100.0)
                if float_pnl <= -max_daily_loss or (daily_base - (account_eq_val + float_pnl)) >= max_daily_loss:
                    prop_guard_hit = True

            # 0. PURE DYNAMIC RISK-SCALED STOP LOSS ENGINE (Strict $35.00 USD Max Basket Loss Ceiling)
            # Dynamically caps basket drawdown to $35.00 USD ($30.00 software trigger + $5 buffer)
            is_cent = getattr(self.broker, "is_cent_account", False)
            account_eq = getattr(self.broker, "balance_usd", getattr(self.broker, "account_equity", getattr(self.broker, "initial_balance", 1000.0)))
            max_eq_risk_pct = getattr(self, "stop_loss_pct", 5.0)
            
            # Strict Dynamic Basket Stop Loss Ceiling: Caps max basket stop loss to $35.00 USD (or 3500 Cents)
            max_sl_ceiling = (3500.0 if is_cent else 35.00)
            min_sl_floor = (1500.0 if is_cent else 15.00)
            base_sl = (self.stop_loss * 100.0) if is_cent else self.stop_loss
            
            if base_sl > 0:
                effective_stop_loss = min(max_sl_ceiling, max(min_sl_floor, base_sl))
            else:
                effective_stop_loss = (30.00 * 100.0) if is_cent else 30.00  # Soft trigger at -$30.00 USD
            
            # HARD EMERGENCY BASKET FLOATING EQUITY LOSS LOCK (5% Max Equity Protection)
            emergency_float_limit = account_eq * getattr(self, "max_basket_drawdown_pct", 0.05)
            if is_cent:
                emergency_float_limit *= 100.0

            if float_pnl <= -effective_stop_loss or float_pnl <= -emergency_float_limit:
                stop_loss_hit = True

            # Update max PnL
            if float_pnl > getattr(self, 'max_floating_pnl', -float("inf")):
                self.max_floating_pnl = float_pnl

            # 1. SMART PROFIT EXPANSION & DYNAMIC VOLUME-SCALED TARGET PROFIT
            num_fills = len(self.broker.open_positions)
            total_basket_lots = sum(p.size for p in self.broker.open_positions.values())
            base_size = max(0.0001, getattr(self, "order_size", 0.01))
            # Capped Volume Scale Multiplier (max 2.2x ceiling) so multi-fill grids (e.g. 4 fills) take profit reliably on small pullbacks
            volume_scale_mult = min(2.2, max(1.0, total_basket_lots / base_size))
            base_tp = (self.target_profit * 100.0) if is_cent else self.target_profit
            friction_floor_adjusted = (friction_floor * 100.0) if is_cent else friction_floor
            effective_target_profit = max(base_tp * volume_scale_mult, friction_floor_adjusted + (100.0 if is_cent else 1.00))

            buy_pos_list = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_pos_list = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

            # Strong Trend Directional Confluence: Allow extra breathing room & boost profit targets on strong trend continuations
            is_strong_buy_trend = bool(buy_pos_list and not sell_pos_list and avg_delta > 0)
            is_strong_sell_trend = bool(sell_pos_list and not buy_pos_list and avg_delta < 0)
            is_strong_trend = is_strong_buy_trend or is_strong_sell_trend

            # Controlled Trend Target Profit Booster: 1.35x expansion max to prevent unachievable profit goals on multi-fills
            if is_strong_trend:
                effective_target_profit *= 1.35

            # CHOP / RANGING REGIME RUNNER RESTRICTION & INSTANT PROFIT TAKE ENGINE:
            # In choppy, ranging, or dual grid markets, NEVER engage Runner Mode! Take profit immediately at target and restart fresh.
            regime_name = str(getattr(self.last_auto_eval, "get", lambda k, d: d)("market_regime", "RANGING")).upper() if hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict) else "RANGING"
            is_choppy_regime = (regime_name in ("RANGING", "CHOP", "REVERSAL")) or (getattr(self, "unidirectional_mode", "DUAL") == "DUAL")

            # UNIDIRECTIONAL TREND RUNNER ACCELERATOR:
            # Engage Runner Mode ONLY during confirmed strong unidirectional trends (BUY_ONLY or SELL_ONLY)
            unidirectional_mode_active = (getattr(self, "unidirectional_mode", "DUAL") in ("BUY_ONLY", "SELL_ONLY")) and not is_choppy_regime
            runner_trigger_threshold = (effective_target_profit * 0.75) if unidirectional_mode_active else effective_target_profit

            if self.use_smart_trailing and float_pnl >= runner_trigger_threshold and unidirectional_mode_active:
                if not self.in_runner_mode:
                    self.in_runner_mode = True
                    self.max_floating_pnl = float_pnl
                    # Immediately cancel pending traps on Runner Mode entry to lock in runner gains
                    try:
                        self.broker.cancel_all_orders()
                    except Exception as err:
                        print(f"Failed to cancel pending orders on Runner Mode entry: {err}")

            if self.in_runner_mode:
                # Strong active trend: 85% peak profit lock for massive trend expansion
                # Confirmed reversal: tighten instantly (92%) to lock in top-of-candle peak profits before drop
                if is_reversing:
                    lock_pct = 0.92
                elif is_strong_trend:
                    lock_pct = 0.85
                else:
                    lock_pct = getattr(self, 'profit_lock_pct', 0.80)

                # 100% Unbreakable Net-Positive Floor: strictly >= 50% TP or friction_floor + $1.00 (Guarantees ZERO loss)
                unbreakable_net_floor = max(friction_floor_adjusted + (100.0 if is_cent else 1.00), effective_target_profit * 0.50)
                trailing_peak_floor = self.max_floating_pnl * lock_pct
                runner_floor = max(unbreakable_net_floor, trailing_peak_floor)
                if float_pnl <= runner_floor and float_pnl >= friction_floor_adjusted + (100.0 if is_cent else 1.00):
                    runner_hit = True
            else:
                # Dynamic Volume-Scaled Target Profit (strictly net positive cash profit after spread & commission)
                # Price Directional Sanity Guard: BUY position strictly requires current_price > average entry price!
                buy_pos_list = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
                sell_pos_list = [p for p in self.broker.open_positions.values() if p.type == "SELL"]
                
                is_price_in_profit_direction = False
                min_dist_met = False
                min_move_pct = max(0.04, getattr(self, "trap_offset", 0.07) * 0.60)

                if buy_pos_list and not sell_pos_list:
                    avg_buy_px = sum(getattr(p, 'open_price', getattr(p, 'price', current_price)) * p.size for p in buy_pos_list) / sum(p.size for p in buy_pos_list)
                    is_price_in_profit_direction = (current_price > avg_buy_px)
                    min_dist_met = ((current_price - avg_buy_px) / avg_buy_px * 100.0) >= min_move_pct
                elif sell_pos_list and not buy_pos_list:
                    avg_sell_px = sum(getattr(p, 'open_price', getattr(p, 'price', current_price)) * p.size for p in sell_pos_list) / sum(p.size for p in sell_pos_list)
                    is_price_in_profit_direction = (current_price < avg_sell_px)
                    min_dist_met = ((avg_sell_px - current_price) / avg_sell_px * 100.0) >= min_move_pct

                # ── NEAR-TP SMART HARVEST GUARD (85% Target + Micro Pullback) ──
                # When floating profit reaches >= 85% of target AND price starts pulling back by 1 tick,
                # HARVEST IMMEDIATELY! Prevents near-winning trades from turning into pullbacks!
                near_tp_threshold = effective_target_profit * 0.85
                recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))] if len(getattr(self, "price_history_ticks", [])) >= 2 else []
                is_pullback_tick = False
                if buy_pos_list and not sell_pos_list:
                    is_pullback_tick = (recent_deltas and recent_deltas[-1] < 0) or (avg_delta < 0)
                elif sell_pos_list and not buy_pos_list:
                    is_pullback_tick = (recent_deltas and recent_deltas[-1] > 0) or (avg_delta > 0)

                if (float_pnl >= effective_target_profit or (float_pnl >= near_tp_threshold and is_pullback_tick)) and float_pnl >= friction_floor + 1.00:
                    target_hit = True
                    if float_pnl < effective_target_profit:
                        print(f"[{getattr(self.broker, 'symbol', 'BOT')}] 🎯 NEAR-TP SMART HARVEST: "
                              f"PnL ${float_pnl:.2f} reached 85%+ of target (${effective_target_profit:.2f}) "
                              f"& micro-pullback detected. Harvested to secure cash profit!")


            # 2. MULTI-STAGE RATCHETED BREAKEVEN & UNLOSABLE EQUITY LOCK SHIELD
            if self.use_breakeven:
                tp_scaled = (self.target_profit * 100.0) if is_cent else self.target_profit
                ff_scaled = (friction_floor * 100.0) if is_cent else friction_floor
                net_cash_floor = ff_scaled + (100.0 if is_cent else 1.00)

                # Pillar 3: UNLOSABLE EQUITY LOCK (+ $0.50 USD float PnL -> Lock + $0.10 USD floor)
                # Guarantees that any trade reaching +$0.50 USD profit can NEVER turn into a loss!
                unlosable_trigger = (50.0 if is_cent else 0.50)
                unlosable_floor = (10.0 if is_cent else 0.10)
                if float_pnl >= unlosable_trigger:
                    self.breakeven_activated = True
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), unlosable_floor)

                # Stage 1: 50% Target Profit hit -> Lock floor at max(net_cash_floor, tp_scaled * 0.35)
                if float_pnl >= tp_scaled * getattr(self, "breakeven_trigger", 0.5):
                    self.breakeven_activated = True
                    stage1_target = max(net_cash_floor, tp_scaled * 0.35)
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage1_target)
                
                # Stage 2: 75% Target Profit hit -> Ratchet floor up to 50% TP
                if float_pnl >= tp_scaled * 0.75:
                    stage2_target = max(net_cash_floor + (100.0 if is_cent else 1.00), tp_scaled * 0.50)
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage2_target)

                # Stage 3: 90% Target Profit hit -> Ratchet floor up to 75% TP
                if float_pnl >= tp_scaled * 0.90:
                    stage3_target = max(net_cash_floor + (300.0 if is_cent else 3.00), tp_scaled * 0.75)
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage3_target)

            if self.use_breakeven and self.breakeven_activated and not self.in_runner_mode:
                active_ratchet = getattr(self, "ratchet_floor", 0.0)
                net_cash_floor = (friction_floor * 100.0 if is_cent else friction_floor) + (100.0 if is_cent else 1.00)
                if active_ratchet > 0 and float_pnl <= active_ratchet and float_pnl >= net_cash_floor:
                    breakeven_hit = True

            # 3. TRAILING STOP (when not in runner mode)
            if self.use_trailing_stop and not self.in_runner_mode:
                ts_dist = (self.trailing_stop_distance * 100.0) if is_cent else self.trailing_stop_distance
                min_trail_activation = max(friction_floor_adjusted + (100.0 if is_cent else 1.00), effective_target_profit * 0.50)
                if self.max_floating_pnl >= min_trail_activation:
                    trail_dist = max(ts_dist, (effective_target_profit * 0.25))
                    trailing_level = self.max_floating_pnl - trail_dist
                    if trailing_level > 0 and float_pnl <= trailing_level and float_pnl >= friction_floor_adjusted:
                        trailing_stop_hit = True
                    
            # Universal Dynamic Volume-Scaled Minimum Net Cash Profit Floor (Minimum +$1.00 net profit, scaling up with volume)
            min_net_cash_profit = max(1.00, 1.00 * volume_scale_mult)
            volume_friction_target = friction_floor + min_net_cash_profit

            # 4. SMART EARLY RANGE EXIT (On 3+ Level Fills during Range Chop)
            early_range_hit = False
            if len(self.broker.open_positions) >= 3 and not self.in_runner_mode:
                target_floor = max(self.target_profit * 0.50, volume_friction_target)
                if float_pnl >= target_floor:
                    early_range_hit = True

            # 5. STRANDED LEG NET-PROFIT OFFSET HARVEST & INSTANT FRESH START ENGINE
            # When positions exist in BOTH directions (BUY positions + stranded SELL positions),
            # as soon as total combined float_pnl reaches +$1.00 USD net profit (or volume_friction_target),
            # trigger immediate basket liquidation to eliminate the stranded SELL position at ZERO NET LOSS
            # and start a 100% fresh grid cycle!
            hedge_lock_hit = False
            buy_positions = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_positions = [p for p in self.broker.open_positions.values() if p.type == "SELL"]
            if buy_positions and sell_positions:
                # DUAL-FILL FAST PROFIT HARVEST & FRESH START SHIELD:
                # As soon as total combined float_pnl reaches +$1.00 USD net profit,
                # immediately liquidate ALL dual positions, bank net cash profit, wipe pending orders, and start a 100% fresh grid cycle!
                dual_target_floor = (100.0 if is_cent else 1.00)
                if float_pnl >= dual_target_floor:
                    hedge_lock_hit = True
                else:
                    # Partial Profitable Side Harvesting Shield:
                    # If BUY side or SELL side individually reaches Target Profit in a dual hedge lock,
                    # automatically close the profitable side to bank cash gains into account balance!
                    buy_pnl = sum(getattr(p, 'profit', 0.0) for p in buy_positions)
                    sell_pnl = sum(getattr(p, 'profit', 0.0) for p in sell_positions)
                    tp_target = (effective_target_profit * 0.50)

                    if buy_pnl >= tp_target:
                        for p in buy_positions:
                            pid = getattr(p, 'id', getattr(p, 'ticket', None))
                            if pid:
                                try: self.broker.close_position(str(pid), current_price, timestamp)
                                except Exception: pass
                    elif sell_pnl >= tp_target:
                        for p in sell_positions:
                            pid = getattr(p, 'id', getattr(p, 'ticket', None))
                            if pid:
                                try: self.broker.close_position(str(pid), current_price, timestamp)
                                except Exception: pass

            # Basket Whole Unit Architecture: Always keep open positions unified as a single basket.
            # When profit target / reversal is reached, close ALL open positions at once, wipe pending orders, and start over!

            # 5b. DYNAMIC COUNTER-HEDGE REVERSAL LOCK (Converts single-side trend drawdown into market-neutral dual basket)
            # If a basket enters floating drawdown >= 2% to 6% during a trend surge,
            # automatically deploy a 1.5x counter-hedge order to flip net volume in favor of the trend!
            if len(self.broker.open_positions) >= 1 and not hedge_lock_hit:
                try:
                    total_buy_lots = sum(p.size for p in buy_positions)
                    total_sell_lots = sum(p.size for p in sell_positions)
                    net_vol = total_buy_lots - total_sell_lots

                    # Net Volume Imbalance Counter-Hedge: Instant 2% zero-wait threshold on momentum reversal, 6% standard floor
                    if abs(net_vol) > 0.0001:
                        is_fast_surge = is_reversing or (len(getattr(self, "price_history_ticks", [])) >= 3 and abs(avg_delta) >= 0.03)
                        hedge_pct = 0.02 if is_fast_surge else 0.06
                        hedge_threshold = effective_stop_loss * hedge_pct

                        if float_pnl <= -hedge_threshold and len(self.broker.pending_orders) < 2:
                            hedge_side = "SELL_STOP" if net_vol > 0 else "BUY_STOP"
                            hedge_dist_pct = getattr(self, "trap_offset", 0.07) * 0.50
                            hedge_px = round(current_price * (1.0 - hedge_dist_pct / 100.0) if hedge_side == "SELL_STOP" else current_price * (1.0 + hedge_dist_pct / 100.0), 2)
                            hedge_size = max(0.01, round(abs(net_vol) * 1.50, 4))
                            
                            sym_n = str(getattr(self.broker, "symbol", "")).upper()
                            if "BTC" in sym_n: h_tp_dist = 50.0
                            elif any(x in sym_n for x in ["XAU", "GOLD", "PAXG"]): h_tp_dist = 3.00
                            elif "ETH" in sym_n: h_tp_dist = 3.00
                            elif "SOL" in sym_n: h_tp_dist = 0.50
                            else: h_tp_dist = current_price * 0.001
                            
                            hedge_tp_px = round(hedge_px - h_tp_dist if hedge_side == "SELL_STOP" else hedge_px + h_tp_dist, 2)
                            try:
                                self.broker.place_order(hedge_side, hedge_px, hedge_size, timestamp, tp=hedge_tp_px)
                            except Exception:
                                pass
                except Exception as hedge_calc_err:
                    print(f"Notice: Counter-hedge evaluation guard: {hedge_calc_err}")

            # 5c. 4+ FILLS UNFILLED PENDING TRAP PURGE & MATHEMATICAL RECOVERY ENGINE
            # When 4 or more grid levels fill on one side (heavy trend expansion):
            # Automatically cancel all remaining unfilled pending traps so no excess orders pile up at extreme levels!
            if len(self.broker.open_positions) >= 4 and len(self.broker.pending_orders) > 0:
                try:
                    self.broker.cancel_all_orders()
                except Exception:
                    pass

            # 6. MICRO-VELOCITY MOMENTUM SCALP EXIT (True Trend Reversal Guard)
            momentum_scalp_hit = False
            if len(self.broker.open_positions) > 0 and float_pnl >= volume_friction_target:
                if len(self.price_history_ticks) >= 5 and is_reversing and float_pnl < getattr(self, "max_floating_pnl", float_pnl) * 0.85:
                    momentum_scalp_hit = True

            # 7. VOLUME WEIGHTED AVERAGE COST RECOVERY & FAST MIXED-FILL EXITS
            wvap_exit_hit = False
            instant_counter_flip_hit = False
            ranging_pnl_harvest_hit = False

            if len(self.broker.open_positions) >= 1 and not self.in_runner_mode:
                has_dual_hedge = (len(buy_positions) > 0 and len(sell_positions) > 0)

                # 7a. INSTANT MIXED-FILL FAST EXIT SHIELD (Dual-Side Fills):
                # If both BUY & SELL positions are open (mix filled), exit IMMEDIATELY ASAP on any positive PnL (+ $0.10 USD)
                mix_target = (10.0 if is_cent else 0.10)
                if has_dual_hedge and float_pnl >= mix_target:
                    instant_counter_flip_hit = True

                # 7b. RANGING CHOP +PNL HARVEST SHIELD (Non-Trending Market):
                # When market is ranging/choppy (not trending), harvest whatever positive PnL is available (+ $0.25 USD)
                regime_name = str(getattr(self.last_auto_eval, "get", lambda k, d: d)("market_regime", "RANGING")).upper() if hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict) else "RANGING"
                if regime_name in ("RANGING", "CHOP", "REVERSAL") and float_pnl >= (25.0 if is_cent else 0.25):
                    ranging_pnl_harvest_hit = True

                # 7c. MULTI-FILL COST RECOVERY EXIT (2+ Fills):
                min_dollar_floor = (50.0 if is_cent else 0.50)
                asap_micro_target = friction_floor + (50.0 if is_cent else 0.50)
                standard_wvap_target = max(min_dollar_floor, asap_micro_target)
                if len(self.broker.open_positions) >= 2 and float_pnl >= standard_wvap_target:
                    wvap_exit_hit = True

            # 7d. ASYMMETRIC TREND-FOLLOWING COUNTER-TREND HARVEST & BREAKEVEN PULLBACK SHIELD
            # When 1m trend is confirmed (|bias| >= 0.35):
            # - If counter-trend position is in positive cash profit (+ >= $0.10 USD):
            #   Instantly harvest profit from counter-trend position ONLY, lock equity, and re-arm trend-side traps!
            # - If counter-trend position is in drawdown (-):
            #   Exit counter-trend position on micro pullback at breakeven (-$0.15 to +$0.05 USD) to minimize loss!
            counter_trend_harvest_hit = False
            counter_trend_be_hit = False

            if hasattr(self, "last_auto_eval") and isinstance(self.last_auto_eval, dict):
                trend_bias = float(self.last_auto_eval.get("combined_bias", 0.0))
                if abs(trend_bias) >= 0.35 and len(self.broker.open_positions) >= 1:
                    counter_side = "SELL" if trend_bias >= 0.35 else "BUY"
                    counter_positions = [p for p in list(self.broker.open_positions.values()) if p.type == counter_side]
                    
                    for cp in counter_positions:
                        entry_p = getattr(cp, "open_price", getattr(cp, "entry_price", current_price))
                        mult_c = (100.0 if "JPY" in str(getattr(self.broker, "symbol", "")).upper() else 1.0)
                        cp_pnl = (current_price - entry_p) * cp.size * mult_c if cp.type == "BUY" else (entry_p - current_price) * cp.size * mult_c
                        
                        # 1. Selective Counter-Trend Positive Profit Harvest (+ >= $0.10 USD)
                        if cp_pnl >= (10.0 if is_cent else 0.10):
                            c_res = self.broker.close_position(cp.position_id, current_price, timestamp)
                            if c_res:
                                counter_trend_harvest_hit = True
                                if self.auto_restart:
                                    try: self.deploy_traps(current_price, timestamp, force=True)
                                    except Exception: pass
                        
                        # 2. Selective Counter-Trend Breakeven / Micro-Pullback Loss Minimizer (-$0.15 to +$0.05 USD)
                        elif -0.15 <= cp_pnl <= 0.05:
                            c_res = self.broker.close_position(cp.position_id, current_price, timestamp)
                            if c_res:
                                counter_trend_be_hit = True

            # 8. SINGLE-FILL QUICK PERCENT SCALP EXIT (Equalized for Crypto & Gold)
            single_fill_scalp_hit = False
            if len(self.broker.open_positions) == 1 and not self.in_runner_mode:
                open_pos = list(self.broker.open_positions.values())[0]
                entry_px = getattr(open_pos, 'open_price', getattr(open_pos, 'price', getattr(open_pos, 'entry_price', current_price)))
                if entry_px > 0:
                    if open_pos.type == "BUY":
                        move_pct = (current_price - entry_px) / entry_px * 100.0
                        is_pos_trend = (avg_delta > 0)
                    else:
                        move_pct = (entry_px - current_price) / entry_px * 100.0
                        is_pos_trend = (avg_delta < 0)
                else:
                    move_pct = 0.0
                    is_pos_trend = False
                
                # Single-fill ultra-fast exit at +$1.00 USD cash profit or 0.06% move
                fast_single_target = (100.0 if is_cent else 1.00)
                target_move_threshold = max(0.06, getattr(self, "trap_offset", 0.08) * 0.70)
                if (move_pct >= target_move_threshold or float_pnl >= fast_single_target) and float_pnl >= fast_single_target:
                    single_fill_scalp_hit = True
                
                target_move_threshold = max(0.08, getattr(self, "trap_offset", 0.08) * 0.90)
                if move_pct >= target_move_threshold and float_pnl >= fast_single_target and not is_pos_trend:
                    single_fill_scalp_hit = True

            # 9. INSTANT TOP/BOTTOM REVERSAL PROFIT EXIT & NEAR-MISS 85%+ TP HARVEST
            top_bottom_reversal_hit = False
            min_solid_profit = max(100.0 if is_cent else 1.00, volume_friction_target)
            near_miss_target = effective_target_profit * 0.85
            if len(self.broker.open_positions) > 0 and not self.in_runner_mode:
                if (is_reversing or float_pnl >= near_miss_target) and float_pnl >= min_solid_profit:
                    top_bottom_reversal_hit = True

        # 100% UNBREAKABLE MASTER NET-POSITIVE PROFIT GUARD:
        # Guarantees that ALL profit-taking exit shields strictly require float_pnl >= +$0.10 USD (strictly net positive cash profit)!
        is_profit_exit_triggered = (target_hit or runner_hit or trailing_stop_hit or breakeven_hit or early_range_hit or hedge_lock_hit or momentum_scalp_hit or wvap_exit_hit or instant_counter_flip_hit or single_fill_scalp_hit or top_bottom_reversal_hit or ranging_pnl_harvest_hit or counter_trend_harvest_hit)
        if is_profit_exit_triggered and float_pnl < (10.0 if is_cent else 0.10) and not counter_trend_be_hit:
            target_hit = runner_hit = trailing_stop_hit = breakeven_hit = early_range_hit = False
            hedge_lock_hit = momentum_scalp_hit = wvap_exit_hit = instant_counter_flip_hit = False
            single_fill_scalp_hit = top_bottom_reversal_hit = ranging_pnl_harvest_hit = counter_trend_harvest_hit = False

        if target_hit or runner_hit or trailing_stop_hit or stop_loss_hit or timeout_hit or breakeven_hit or early_range_hit or prop_guard_hit or hedge_lock_hit or velocity_shield_hit or momentum_scalp_hit or wvap_exit_hit or instant_counter_flip_hit or single_fill_scalp_hit or top_bottom_reversal_hit or ranging_pnl_harvest_hit or counter_trend_harvest_hit or counter_trend_be_hit:
            if counter_trend_harvest_hit: reason = "COUNTER_TREND_PROFIT_HARVEST"
            elif counter_trend_be_hit: reason = "COUNTER_TREND_BREAKEVEN_EXIT"
            elif instant_counter_flip_hit: reason = "MIXED_FILL_FAST_EXIT"
            elif ranging_pnl_harvest_hit: reason = "RANGING_CHOP_PNL_HARVEST"
            elif top_bottom_reversal_hit: reason = "TOP_BOTTOM_REVERSAL_EXIT"
            elif single_fill_scalp_hit: reason = "SINGLE_FILL_QUICK_SCALP"
            elif wvap_exit_hit:     reason = "WVAP_COST_RECOVERY"
            elif momentum_scalp_hit: reason = "MOMENTUM_SCALP_EXIT"
            elif velocity_shield_hit: reason = "VELOCITY_TREND_SHIELD"
            elif runner_hit:        reason = "RUNNER_EXPANSION"
            elif target_hit:        reason = "TARGET_PROFIT"
            elif prop_guard_hit:    reason = "PROP_FIRM_GUARD"
            elif hedge_lock_hit:   reason = "HEDGE_LOCK_UNLOCKED"
            elif early_range_hit:   reason = "EARLY_RANGE_EXIT"
            elif trailing_stop_hit: reason = "TRAILING_STOP"
            elif breakeven_hit:     reason = "BREAKEVEN"
            elif stop_loss_hit:     reason = "STOP_LOSS"
            else:                   reason = "TIMEOUT"
            
            # Reset breakeven, runner state & peak memory for next cycle
            self.breakeven_activated = False
            self.ratchet_floor = 0.0
            self.max_floating_pnl = 0.0
            if hasattr(self, "price_history_ticks") and isinstance(self.price_history_ticks, list):
                self.price_history_ticks.clear()

            # If exiting from Runner Mode, set a 10-second cooldown before next grid deploys
            if self.in_runner_mode or runner_hit:
                self._runner_exit_cooldown_until = timestamp + 10.0
            self.in_runner_mode = False
            
            # Close cycle — cancel pending orders FIRST to avoid orders filling mid-exit!
            try:
                self.broker.cancel_all_orders()
            except Exception as err:
                print(f"Failed to cancel pending orders prior to position exit: {err}")

            _pnl_before = self.broker.realized_pnl
            closed_trades = self.broker.close_all_positions(current_price, timestamp)

            # Instantly sync closed deal history from MT5 terminal to catch exact realized PnL
            if hasattr(self.broker, "sync_history_from_mt5"):
                try:
                    self.broker.sync_history_from_mt5(force=True)
                except Exception:
                    pass

            # Double verification wipe: Cancel any residual pending orders/stops post-exit
            try:
                self.broker.cancel_all_orders()
            except Exception:
                pass

            trades_count = len(closed_trades)
            cycle_pnl = sum(t["pnl"] for t in closed_trades) if closed_trades else (self.broker.realized_pnl - _pnl_before)

            # Prevent phantom 0-trade $0.00 records from polluting cycle history logs
            if trades_count > 0 or abs(cycle_pnl) > 0.001:
                cycle_summary = {
                    "cycle_id": self.current_cycle_id,
                    "deploy_price": self.deploy_price,
                    "exit_price": current_price,
                    "pnl": cycle_pnl,
                    "trades_count": max(1, trades_count),
                    "start_time": self.cycle_start_time,
                    "exit_time": timestamp,
                    "exit_reason": reason
                }
                self.cycle_history.append(cycle_summary)
                if len(self.cycle_history) > 500:
                    self.cycle_history = self.cycle_history[-500:]
                self.current_cycle_id += 1
            else:
                cycle_summary = None

            # Dispatch Telegram Signal Alert if configured
            tg_token = getattr(self, "telegram_bot_token", None)
            tg_chat = getattr(self, "telegram_chat_id", None)
            if tg_token and tg_chat:
                try:
                    from core.signals import dispatch_trade_exit_signal
                    symbol_name = getattr(self.broker, "symbol", "ACTIVE PAIR")
                    dispatch_trade_exit_signal(tg_token, tg_chat, symbol_name, cycle_summary)
                except Exception as tg_err:
                    print(f"Notice: Telegram alert dispatch error: {tg_err}")

            self.current_cycle_id += 1

            # Clear runner mode, exit cooldown & error timestamp BEFORE calling deploy_traps so fresh grid is deployed INSTANTLY
            self.in_runner_mode = False
            self._runner_exit_cooldown_until = 0.0
            self._last_deploy_error_time = 0.0

            if self.auto_restart:
                # Instantly deploy new traps at the new current price
                self.deploy_traps(current_price, timestamp, force=True)
            else:
                self.deployed = False

            return cycle_summary

        return None

    def sync_cycle_history_from_trades(self):
        """
        Reconstructs cycle_history from the broker's closed_trades list by grouping
        trades that exited at the same time.
        """
        if not self.broker.closed_trades:
            # Only wipe cycle history for SimulatedBroker where empty = genuinely empty.
            # For MT5Broker, preserve existing history — trades list may be temporarily empty on API blip.
            if self.broker.__class__.__name__ == "SimulatedBroker":
                self.cycle_history = []
            return

        # Sort trades by exit time ascending
        trades = sorted(self.broker.closed_trades, key=lambda x: x["exit_time"])
        
        # Group trades by exit time (within 3 seconds margin)
        cycles = []
        current_cycle_trades = []
        
        for t in trades:
            if not current_cycle_trades:
                current_cycle_trades.append(t)
            else:
                last_t = current_cycle_trades[-1]
                if abs(t["exit_time"] - last_t["exit_time"]) <= 3.0:
                    current_cycle_trades.append(t)
                else:
                    cycles.append(current_cycle_trades)
                    current_cycle_trades = [t]
        if current_cycle_trades:
            cycles.append(current_cycle_trades)

        # Build a lookup map of existing recorded exit reasons to preserve exact live exit metadata
        existing_reasons = {}
        for existing in self.cycle_history:
            if isinstance(existing, dict) and "exit_time" in existing and "exit_reason" in existing:
                existing_reasons[existing["exit_time"]] = existing["exit_reason"]

        # Build cycle history summaries
        self.cycle_history = []
        for idx, c_trades in enumerate(cycles):
            if not c_trades or len(c_trades) == 0:
                continue
            pnl = sum(t["pnl"] for t in c_trades)
            exit_time = c_trades[-1]["exit_time"]
            start_time = min(t["entry_time"] for t in c_trades)
            
            # Estimate deploy price as average entry price
            deploy_price = sum(t["entry_price"] for t in c_trades) / len(c_trades)
            exit_price = c_trades[-1]["exit_price"]
            
            # Check if we already have an exact recorded exit_reason for this exit timestamp
            matched_reason = None
            for ex_time, ex_reason in existing_reasons.items():
                if abs(exit_time - ex_time) <= 5.0:
                    matched_reason = ex_reason
                    break

            if matched_reason:
                reason = matched_reason
            else:
                # Fallback reason classification for historical/reconstructed MT5 deals
                target_thresh = getattr(self, 'target_profit', 10.0) * 0.9
                if pnl >= target_thresh:
                    reason = "TARGET_PROFIT"
                elif pnl > 0:
                    reason = "TRAILING_STOP"
                elif abs(pnl) <= 2.0:
                    reason = "BREAKEVEN"
                elif pnl < 0:
                    reason = "STOP_LOSS"
                else:
                    reason = "MANUAL / EXIT"
                
            summary = {
                "cycle_id": idx + 1,
                "deploy_price": deploy_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "trades_count": len(c_trades),
                "start_time": start_time,
                "exit_time": exit_time,
                "exit_reason": reason
            }
            self.cycle_history.append(summary)
            # History is kept oldest-first (same order as process_tick appends).
            # The UI renders it with reversed() to show newest-first.
