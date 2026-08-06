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
        info = mt5_ref.symbol_info(sym)
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
    def _detect_regime(ema_bias: float, rsi: float, atr_pct: float, bb_width_pct: float) -> str:
        """
        Classifies market into TRENDING / RANGING / REVERSAL.
        - TRENDING:   Strong EMA directional bias, normal-to-high ATR
        - RANGING:    Weak EMA bias, low ATR, tight Bollinger Bands
        - REVERSAL:   RSI extreme (>72 or <28) while price near EMA cross
        """
        if rsi > 72 or rsi < 28:
            return "REVERSAL"
        if abs(ema_bias) >= 0.50 and atr_pct >= 0.20:
            return "TRENDING"
        if abs(ema_bias) < 0.25 and atr_pct < 0.30 and bb_width_pct < 2.5:
            return "RANGING"
        return "TRENDING" if abs(ema_bias) >= 0.35 else "RANGING"

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
        macro_news: Optional[List[dict]] = None
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

        # ---- 3. REGIME DETECTION ----
        regime = tech.get("regime") if tech.get("regime") else self._detect_regime(ema_bias, rsi, atr_pct, bb_width_pct)

        # ---- 4. COMBINED DIRECTIONAL BIAS & UNIDIRECTIONAL CONFLUENCE ----
        # 45% EMA + 30% Orderbook + 15% VWAP + 10% RSI signal
        rsi_signal = (rsi - 50.0) / 50.0  # -1.0 (oversold=buy) to +1.0 (overbought=sell)
        combined_bias = (
            0.45 * ema_bias
            + 0.30 * ob_delta
            + 0.15 * vwap_bias
            + 0.10 * (-rsi_signal)  # RSI >70 = negative (fade overbought), <30 = positive
        )
        combined_bias = max(-1.0, min(1.0, combined_bias))

        # Unidirectional Trap Mode: If trend confluence score >= +0.50 -> BUY_ONLY; <= -0.50 -> SELL_ONLY; else DUAL
        if combined_bias >= 0.50:
            unidirectional_mode = "BUY_ONLY"
        elif combined_bias <= -0.50:
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
        for s_token in ["BTCUSDT", "BTCUSD", "ETHUSDT", "ETHUSD", "PAXGUSDT", "XAUUSD", "GOLD", "SOLUSDT", "SOLUSD", "BNBUSDT", "BNBUSD", "DOGEUSDT", "DOGEUSD", "XRPUSDT", "XRPUSD"]:
            if s_token in sym_u:
                clean_sym = s_token
                break

        default_sizes = {
            "BTCUSDT": 0.001, "BTCUSD": 0.001,
            "ETHUSDT": 0.10,  "ETHUSD": 0.10,
            "PAXGUSDT": 0.01, "XAUUSD": 0.01, "GOLD": 0.01,
            "SOLUSDT": 1.0,   "SOLUSD": 1.0,
            "BNBUSDT": 0.10,  "BNBUSD": 0.10,
            "DOGEUSDT": 1000.0,"DOGEUSD": 1000.0,
            "XRPUSDT": 100.0, "XRPUSD": 100.0,
        }
        # ---- 8a. CAPITAL TIER (shared across ALL symbols on same account) ----
        # Note: account_equity here is the TOTAL account equity, not per-symbol.
        # This ensures ETH and Gold on the same $1,000 account BOTH get the same tier level.
        if account_equity < 250.0:
            capital_tier = "$100 Micro"
            base_size = default_sizes.get(clean_sym, 0.001) * 0.5
            lot_multiplier = 1.20
            max_levels = 3
            base_target_profit = 2.00
            stop_loss = max(50.0, account_equity * (getattr(self, "stop_loss_pct", 10.0) / 100.0))
        elif account_equity < 2500.0:
            capital_tier = "$1,000 Golden"
            base_size = default_sizes.get(clean_sym, 0.01)
            # Gold strict lot lock: Base size MUST be 0.01 lots on $1,000 account
            if any(x in clean_sym for x in ["XAU", "GOLD", "PAXG"]):
                base_size = 0.01
            lot_multiplier = 1.25   # Conservative 1.25x for fast recovery & low drawdown
            max_levels = 5
            base_target_profit = 4.50   # Quick Scalp Target Profit for fast exits
            stop_loss = max(50.0, account_equity * (getattr(self, "stop_loss_pct", 10.0) / 100.0))
        else:
            capital_tier = "$10,000 Pro"
            scale = min(3.0, max(1.0, account_equity / 10000.0))
            base_size = default_sizes.get(clean_sym, 0.01) * scale
            if any(x in clean_sym for x in ["XAU", "GOLD", "PAXG"]):
                base_size = min(0.02, base_size)
            lot_multiplier = 1.25
            max_levels = 5 if any(x in clean_sym for x in ["XAU", "GOLD", "PAXG", "BTC"]) else 8
            base_target_profit = 25.0
            stop_loss = max(50.0, account_equity * (getattr(self, "stop_loss_pct", 10.0) / 100.0))

        # ---- 8b. SYMBOL VOLATILITY LEVEL CAP ----
        # High-volatility assets (Gold / BTC) are capped at max 5 levels for risk protection on large accounts
        if any(x in clean_sym for x in ["XAU", "GOLD", "PAXG", "BTC"]):
            max_levels = min(5, max_levels)
        else:
            _sym_max_levels = {
                "ETHUSDT": max_levels, "ETHUSD": max_levels,
                "SOLUSDT": max_levels, "BNBUSDT": max_levels,
                "DOGEUSDT": max_levels, "XRPUSDT": max_levels,
            }
            max_levels = _sym_max_levels.get(clean_sym, max_levels)


        # ---- 9. GRID GEOMETRY ----
        base_gap = max(0.05, round(atr_pct * 0.35, 2))
        base_offset = max(0.08, round(atr_pct * 0.50, 2))

        # Regime-specific gap scaling
        if regime == "RANGING":
            regime_gap_mult = 0.70    # Tighter for range-fill micro-profits
        elif regime == "TRENDING":
            regime_gap_mult = 1.00
        else:  # REVERSAL
            regime_gap_mult = 1.40    # Wider — protect against false breakouts at extremes

        # Asymmetric offsets: tighter toward trend side, wider counter
        buy_offset = round(base_offset * (1.0 - 0.35 * combined_bias) * news_risk_mult, 3)
        sell_offset = round(base_offset * (1.0 + 0.35 * combined_bias) * news_risk_mult, 3)
        buy_offset = max(0.02, buy_offset)
        sell_offset = max(0.02, sell_offset)

        # Final dynamic gap with session + regime + BB width
        bb_scale = max(0.5, min(2.5, bb_width_pct / 2.0))
        dynamic_gap = max(0.03, round(
            base_gap * bb_scale * regime_gap_mult * gap_session_mult,
            3
        ))

        # ---- Symbol-Specific Dynamic Volatility-Adaptive Architecture ----
        # Quiet / Ranging markets: shrink offset & gap down to Ultra-Sniper floors for fast 30-sec micro-profits!
        # High Volatility / Trending markets: expand offset & gap up for maximum trend expansion safety!
        is_quiet_market = (regime == "RANGING" or atr_pct < 0.25)
        
        if any(x in sym_u for x in ["PAXG", "XAU", "GOLD"]):
            # Gold Precision Scalper (0.07% Offset = $2.835 USD, 0.07% Gap = $2.835 USD)
            min_gap = 0.07 if is_quiet_market else 0.12
            min_offset = 0.07 if is_quiet_market else 0.10
            dynamic_gap = max(min_gap, dynamic_gap)
            buy_offset = max(min_offset, buy_offset)
            sell_offset = max(min_offset, sell_offset)
            lot_multiplier = min(1.25, lot_multiplier)
            base_target_profit = 2.50
        elif any(x in sym_u for x in ["BTC"]):
            # BTC Quiet Gap 0.09% (-0.01% reduction)
            min_gap = 0.09 if is_quiet_market else 0.20
            min_offset = 0.09 if is_quiet_market else 0.22
            dynamic_gap = max(min_gap, dynamic_gap)
            buy_offset = max(min_offset, buy_offset)
            sell_offset = max(min_offset, sell_offset)
            lot_multiplier = min(1.25, lot_multiplier)
            base_target_profit = 2.50 if is_quiet_market else 3.50
        elif any(x in sym_u for x in ["ETH"]):
            # ETH Quiet Gap 0.09% (-0.01% reduction)
            min_gap = 0.09 if is_quiet_market else 0.18
            min_offset = 0.09 if is_quiet_market else 0.20
            dynamic_gap = max(min_gap, dynamic_gap)
            buy_offset = max(min_offset, buy_offset)
            sell_offset = max(min_offset, sell_offset)
            lot_multiplier = min(1.25, lot_multiplier)
            base_target_profit = 2.50 if is_quiet_market else 3.50
        elif any(x in sym_u for x in ["SOL", "BNB"]):
            # SOL/BNB Quiet Gap 0.07% (-0.01% reduction)
            min_gap = 0.07 if is_quiet_market else 0.15
            min_offset = 0.07 if is_quiet_market else 0.18
            dynamic_gap = max(min_gap, dynamic_gap)
            buy_offset = max(min_offset, buy_offset)
            sell_offset = max(min_offset, sell_offset)
            lot_multiplier = min(1.25, lot_multiplier)
            base_target_profit = 2.50 if is_quiet_market else 3.00
        elif any(x in sym_u for x in ["DOGE", "XRP"]):
            # DOGE/XRP Quiet Gap 0.05% (-0.01% reduction)
            min_gap = 0.05 if is_quiet_market else 0.12
            min_offset = 0.06 if is_quiet_market else 0.15
            dynamic_gap = max(min_gap, dynamic_gap)
            buy_offset = max(min_offset, buy_offset)
            sell_offset = max(min_offset, sell_offset)
            lot_multiplier = min(1.25, lot_multiplier)
            base_target_profit = 2.00 if is_quiet_market else 2.50

        # Live Broker Spread-Noise Filter: Scale trap_offset dynamically if live broker spread is high
        live_spread = tech_indicators.get("live_spread", 0.0) if tech_indicators else 0.0
        if live_spread > 0 and current_price > 0:
            spread_pct = (live_spread / current_price) * 100.0
            min_spread_offset = spread_pct * 2.5
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

        # ---- 12. UPDATE STATE FOR REDEPLOYMENT THROTTLE ----
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
            "ob_ratio": ob_ratio,
            # Bias signals
            "ema_trend_bias": ema_bias,
            "combined_bias": round(combined_bias, 3),
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
        }


def sanitize_order_size(symbol: str, size: float) -> float:
    sym_u = (symbol or "").upper()
    try:
        val = float(size)
    except Exception:
        val = 0.01

    if any(x in sym_u for x in ["PAXG", "XAU", "GOLD"]):
        return min(0.03, max(0.01, round(val, 2)))  # Gold strictly capped between 0.01 and 0.03 lots max
    elif any(x in sym_u for x in ["BTC"]):
        return min(0.05, max(0.001, round(val, 4))) # BTC max 0.05 BTC
    elif any(x in sym_u for x in ["ETH"]):
        return min(0.50, max(0.05, round(val, 3)))  # ETH max 0.50 ETH
    elif any(x in sym_u for x in ["SOL"]):
        return min(3.0, max(0.5, round(val, 2)))    # SOL max 3.0 SOL
    elif any(x in sym_u for x in ["BNB"]):
        return min(0.50, max(0.05, round(val, 3)))  # BNB max 0.50 BNB
    else:
        return min(5.0, max(0.001, round(val, 4)))


class BreakoutGridBot:
    def __init__(
        self,
        broker: 'MT5Broker',
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
        max_cycle_duration: float = 3600.0,
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
        use_auto_reading: bool = False
    ):
        self.broker = broker
        self.grid_levels = grid_levels
        self.grid_gap = grid_gap
        self.trap_offset = trap_offset
        self.order_size = order_size
        self.order_size_multiplier = order_size_multiplier
        self.target_profit = target_profit
        self.auto_restart = auto_restart
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

    @property
    def order_size(self) -> float:
        sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
        return sanitize_order_size(sym_str, getattr(self, "_order_size", 0.01))

    @order_size.setter
    def order_size(self, val: float):
        sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
        self._order_size = sanitize_order_size(sym_str, val)

        # Risk Control Circuit Breaker & Macro News Shield
        self.max_daily_drawdown: float = 0.0  # 0.0 disabled; e.g. 250.0 = max -$250 loss cap
        self.daily_circuit_breaker_tripped: bool = False
        self.use_news_shield: bool = True

        # Prop Firm Challenge Compliance Engine (FTMO / FundedNext / Funding Pips)
        self.prop_firm_guard_enabled: bool = False
        self.prop_firm_max_daily_drawdown_pct: float = 4.5  # 4.5% daily drawdown lock (buffer for 5.0% limit)
        self.prop_firm_target_pct: float = 8.0  # 8.0% challenge pass target lock

        # Friday Weekend Market Shutdown Engine (Gold XAUUSD & Forex)
        self.use_weekend_shutdown: bool = True  # Auto-enabled for Gold & traditional assets
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

            max_cap = getattr(self, "max_order_size", default_max_cap)
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
            self.cancel_opposite_on_trigger = True
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
            self.grid_levels = 10
        if not hasattr(self, "grid_gap"):
            self.grid_gap = 10.0
        if not hasattr(self, "trap_offset"):
            self.trap_offset = 15.0
        if not hasattr(self, "order_size"):
            self.order_size = 0.01
        if not hasattr(self, "order_size_multiplier"):
            self.order_size_multiplier = 1.25
        if not hasattr(self, "target_profit"):
            self.target_profit = 10.0
        if not hasattr(self, "stop_loss"):
            self.stop_loss = 0.0
        if not hasattr(self, "max_cycle_duration"):
            self.max_cycle_duration = float("inf")
        if not hasattr(self, "auto_restart"):
            self.auto_restart = True
        if not hasattr(self, "use_auto_reading"):
            self.use_auto_reading = False
        if not hasattr(self, "auto_reading_engine"):
            self.auto_reading_engine = AutoReadingEngine()

    def deploy_traps(self, current_price: float, timestamp: float, bb_width: Optional[float] = None):
        """
        Cancel existing traps and place a new grid of traps centered around current_price.
        If use_bb_filter is True, deployment will be skipped if bb_width is missing or > threshold.
        """
        self.ensure_attributes_initialized()
        if getattr(self, "in_runner_mode", False):
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
                    or getattr(self.broker, "balance", 1000.0)
                )

                eval_res = self.auto_reading_engine.evaluate_market_and_account(
                    symbol=sym_str,
                    current_price=current_price,
                    account_equity=bal,
                    tech_indicators=tech,
                    orderbook_depth=ob,
                    macro_news=news
                )
                
                self.order_size = eval_res["recommended_size"]
                self.order_size_multiplier = eval_res["recommended_multiplier"]
                self.grid_levels = eval_res["recommended_levels"]
                self.stop_loss = eval_res["recommended_stop_loss"]
                # Apply dynamic target profit from enhanced AutoReadingEngine
                if "recommended_target_profit" in eval_res:
                    self.target_profit = eval_res["recommended_target_profit"]
                # Store latest evaluation for UI display
                self.last_auto_eval = eval_res
                
                buy_offset_val = current_price * (eval_res["buy_offset_pct"] / 100.0)
                sell_offset_val = current_price * (eval_res["sell_offset_pct"] / 100.0)
                gap_val = current_price * (eval_res["dynamic_gap_pct"] / 100.0)

            except Exception as auto_err:
                print(f"Auto-Reading execution notice: {auto_err}")
                buy_offset_val, gap_val = self.calculate_offset_and_gap(current_price, effective_gap, self.trap_offset)
                sell_offset_val = buy_offset_val
        else:
            buy_offset_val, gap_val = self.calculate_offset_and_gap(current_price, effective_gap, self.trap_offset)
            sell_offset_val = buy_offset_val

        self.deploy_order_size = self.order_size
        self.deploy_order_size_multiplier = self.order_size_multiplier
        self.deploy_grid_gap = gap_val
        self.deploy_trap_offset = buy_offset_val

        placed_count = 0
        cancel_success = False
        try:
            # FIX 1: Cancel ONLY right before placing fresh traps (after Auto-Reading succeeds).
            # This guarantees traps are never wiped unless we are ready to immediately replace them.
            try:
                self.broker.cancel_all_orders()
                cancel_success = True
            except Exception as pre_cancel_err:
                print(f"Pre-deploy cancel notice: {pre_cancel_err}")

            unidirectional_mode = "DUAL"
            if getattr(self, "use_auto_reading", False) and hasattr(self, "last_auto_eval"):
                unidirectional_mode = self.last_auto_eval.get("unidirectional_mode", "DUAL")

            # Orderbook Pressure Imbalance Filter: Pause trap deployment into heavy institutional sell/buy walls
            ob_ratio = self.last_auto_eval.get("ob_ratio", 1.0) if hasattr(self, "last_auto_eval") and self.last_auto_eval else 1.0
            if ob_ratio > 3.0:     # Heavy Ask/Sell Pressure (>75% Asks) -> Suppress BUY_STOP traps into sell wall
                unidirectional_mode = "SELL_ONLY" if unidirectional_mode == "DUAL" else unidirectional_mode
            elif ob_ratio < 0.33:  # Heavy Bid/Buy Pressure (>75% Bids) -> Suppress SELL_STOP traps into buy wall
                unidirectional_mode = "BUY_ONLY" if unidirectional_mode == "DUAL" else unidirectional_mode

            # Place Buy Stop orders above current_price (suppressed if SELL_ONLY)
            if unidirectional_mode != "SELL_ONLY":
                for i in range(self.grid_levels):
                    try:
                        trigger_price = current_price + buy_offset_val + (i * gap_val)
                        level_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                        self.broker.place_order("BUY_STOP", trigger_price, level_size, timestamp)
                        placed_count += 1
                    except Exception as err:
                        print(f"Buy trap level {i+1} placement notice: {err}")
                        break

            # Place Sell Stop orders below current_price (suppressed if BUY_ONLY)
            if unidirectional_mode != "BUY_ONLY":
                for i in range(self.grid_levels):
                    try:
                        trigger_price = current_price - sell_offset_val - (i * gap_val)
                        level_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                        self.broker.place_order("SELL_STOP", trigger_price, level_size, timestamp)
                        placed_count += 1
                    except Exception as err:
                        print(f"Sell trap level {i+1} placement notice: {err}")
                        break

            # FIX: Use ONLY placed_count to determine deployed state.
            # Do NOT use len(pending_orders) — after cancel+sync, MT5 residual orders can
            # make pending_orders appear non-empty even if zero NEW traps were placed.
            if placed_count > 0:
                self.deployed = True
            else:
                self.deployed = False
                self._last_deploy_error_time = timestamp
        except Exception as e:
            if placed_count > 0:
                self.deployed = True
            else:
                self.deployed = False
                self._last_deploy_error_time = timestamp
                print(f"Notice: Grid trap deployment paused: {e}")

    def repair_grid(self, current_price: float, timestamp: float) -> int:
        """
        Scans current pending orders and places any missing grid trap levels above and below
        the deploy_price or current_price to restore full grid trap coverage without closing
        existing active open positions.
        Preserves the exact order_size and multiplier parameters of the active cycle.
        Returns the number of missing orders placed.
        """
        if getattr(self, "in_runner_mode", False):
            # Runner Mode intentionally operates with wiped opposite traps to protect profits
            return 0

        # If no positions and no pending orders exist, run a fresh deploy_traps call
        if len(self.broker.pending_orders) == 0 and len(self.broker.open_positions) == 0:
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

        # Collect existing pending trigger prices AND open position entry prices to prevent duplication
        buy_pending = [o for o in self.broker.pending_orders.values() if o.type == "BUY_STOP"]
        buy_open = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
        sell_pending = [o for o in self.broker.pending_orders.values() if o.type == "SELL_STOP"]
        sell_open = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

        # ---- Idle Grid Dynamic Compression (Post-Spike Gap Compression) ----
        # FIX 2: Only auto-recenter if a fresh deploy can actually proceed.
        # Guard all blocking conditions first before wiping existing traps.
        if len(self.broker.open_positions) == 0 and len(buy_pending) >= 2:
            buy_prices = sorted([o.trigger_price for o in buy_pending])
            existing_gap = buy_prices[1] - buy_prices[0]
            grid_age = timestamp - getattr(self, "last_deploy_time", 0.0)
            if existing_gap > 0 and gap_val < (existing_gap * 0.70) and grid_age >= 180:
                # Pre-check: ensure deploy_traps is not blocked by weekend/circuit-breaker/runner guards
                _in_runner = getattr(self, "in_runner_mode", False)
                _cb_tripped = getattr(self, "daily_circuit_breaker_tripped", False)
                _in_weekend = getattr(self, "weekend_shutdown_triggered", False)
                _past_cooldown = timestamp >= getattr(self, "_runner_exit_cooldown_until", 0.0)
                if not _in_runner and not _cb_tripped and not _in_weekend and _past_cooldown:
                    self.broker.cancel_all_orders()
                    self.deploy_traps(center_price, timestamp)
                return 0

        existing_buy_levels = [o.trigger_price for o in buy_pending] + [p.entry_price for p in buy_open]
        existing_sell_levels = [o.trigger_price for o in sell_pending] + [p.entry_price for p in sell_open]

        # OCO Mode Guard: If cancel_opposite_on_trigger is enabled and positions are open in ONE direction,
        # DO NOT repair or place opposite trap orders to prevent 10-level double-sided hedge lock!
        cancel_opp = getattr(self, "cancel_opposite_on_trigger", True)
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
                    target_price = center_price + buy_offset_val + (i * gap_val)
                    if target_price <= current_price:
                        target_price = current_price + (gap_val * 0.5) + (i * gap_val)
                    
                    # Only place if level doesn't exist near existing BUY levels
                    if target_price > current_price and not any(abs(target_price - ex) < (gap_val * 0.35) for ex in existing_buy_levels):
                        level_size = self.calculate_level_size(base_size, mult, i)
                        self.broker.place_order("BUY_STOP", target_price, level_size, timestamp)
                        buy_placed += 1
                        existing_buy_levels.append(target_price)

            # Check and place missing SELL_STOP levels ONLY if allow_sell_repair is True
            if allow_sell_repair and (len(sell_pending) + len(sell_open) < self.grid_levels):
                for i in range(self.grid_levels):
                    if len(sell_pending) + len(sell_open) + sell_placed >= self.grid_levels:
                        break
                    target_price = center_price - sell_offset_val - (i * gap_val)
                    if target_price >= current_price:
                        target_price = current_price - (gap_val * 0.5) - (i * gap_val)

                    # Only place if level doesn't exist near existing SELL levels
                    if target_price < current_price and not any(abs(target_price - ex) < (gap_val * 0.35) for ex in existing_sell_levels):
                        level_size = self.calculate_level_size(base_size, mult, i)
                        self.broker.place_order("SELL_STOP", target_price, level_size, timestamp)
                        sell_placed += 1
                        existing_sell_levels.append(target_price)

            placed_count = buy_placed + sell_placed
        except Exception as e:
            err_msg = str(e)
            last_err = getattr(self, "_last_repair_error", None)
            last_err_time = getattr(self, "_last_repair_error_time", 0.0)
            if err_msg != last_err or (timestamp - last_err_time) >= 60.0:
                print(f"Notice: Grid repair encountered order placement notice: {err_msg}")
                self._last_repair_error = err_msg
                self._last_repair_error_time = timestamp

        return placed_count

    def cleanup_grid(self, current_price: float) -> int:
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

        tolerance = gap_val * 0.5

        # Build the set of valid grid prices (expected levels)
        valid_buy_levels = [center_price + buy_offset_val + (i * gap_val) for i in range(self.grid_levels)]
        valid_sell_levels = [center_price - sell_offset_val - (i * gap_val) for i in range(self.grid_levels)]

        cancelled_ids = []

        # --- Step 1: Remove orphan orders (not near any valid level) ---
        for order_id, order in list(self.broker.pending_orders.items()):
            if order_id in cancelled_ids:
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
            now_utc = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
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
        if not self.deployed and self.auto_restart:
            if timestamp >= getattr(self, "_last_deploy_error_time", 0.0) + 30.0:
                try:
                    self.deploy_traps(current_price, timestamp, bb_width)
                except Exception as dep_err:
                    self._last_deploy_error_time = timestamp
                    print(f"Notice: Grid deployment on pause (30s cooldown): {dep_err}")

        if not self.deployed:
            return None

        # ── RUNNER EXIT COOLDOWN ─────────────────────────────────────────────────
        # After Runner Mode exits, wait briefly before processing new triggers
        # to avoid the first grid trap filling instantly on a still-trending price.
        if timestamp < getattr(self, '_runner_exit_cooldown_until', 0.0):
            return None
        # ─────────────────────────────────────────────────────────────────────────

        # Dynamic Spread Guard: Skip order fills if broker spread is abnormally wide (> 3x max spread limit)
        if hasattr(self.broker, "get_current_spread"):
            cur_spread = self.broker.get_current_spread()
            max_allowed = getattr(self, "max_allowed_spread", 4.5)
            if cur_spread > max_allowed:
                triggered_positions = []
            else:
                triggered_positions = self.broker.process_tick(previous_price, current_price, timestamp)
        else:
            triggered_positions = self.broker.process_tick(previous_price, current_price, timestamp)

        # Update last-trigger time whenever a new position is filled
        if triggered_positions:
            self._last_trigger_time = timestamp

        # OCO Trap cancellation logic
        if self.cancel_opposite_on_trigger and triggered_positions:
            for pos in triggered_positions:
                opposite_type = "SELL_STOP" if pos.type == "BUY" else "BUY_STOP"
                # Cancel all orders of opposite_type
                orders_to_cancel = [order_id for order_id, o in self.broker.pending_orders.items() if o.type == opposite_type]
                for order_id in orders_to_cancel:
                    self.broker.cancel_order(order_id)

        # Calculate floating profit/loss
        float_pnl = self.broker.get_floating_pnl(current_price)

        # Automatic Autonomous Grid Repair (Disabled by default — manual override via 🔧 REPAIR GRID button)
        if not getattr(self, "in_runner_mode", False) and getattr(self, "use_grid_repair", False):
            buy_pending = [o for o in self.broker.pending_orders.values() if o.type == "BUY_STOP"]
            buy_open = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_pending = [o for o in self.broker.pending_orders.values() if o.type == "SELL_STOP"]
            sell_open = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

            cancel_opp = getattr(self, "cancel_opposite_on_trigger", False)
            need_buy_repair = (len(buy_pending) + len(buy_open) < self.grid_levels) and not (cancel_opp and len(sell_open) > 0)
            need_sell_repair = (len(sell_pending) + len(sell_open) < self.grid_levels) and not (cancel_opp and len(buy_open) > 0)

            if need_buy_repair or need_sell_repair:
                try:
                    self.repair_grid(current_price, timestamp)
                except Exception as repair_err:
                    print(f"Auto-repair notice: {repair_err}")

        # Automatic Pending Trap Cleanup (Disabled by default — manual override via 🧹 CLEAN UP button)
        if getattr(self, "use_auto_cleanup", False) and len(self.broker.pending_orders) > 0:
            try:
                self.cleanup_grid(current_price)
            except Exception:
                pass

        # Track tick price history and velocity (Delta P / Delta t)
        if not hasattr(self, "price_history_ticks") or self.price_history_ticks is None:
            self.price_history_ticks = []
        self.price_history_ticks.append(current_price)
        if len(self.price_history_ticks) > 10:
            self.price_history_ticks.pop(0)

        avg_delta = 0.0
        avg_delta_pct = 0.0
        is_reversing = False
        if len(self.price_history_ticks) >= 3:
            recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))]
            avg_delta = sum(recent_deltas) / len(recent_deltas)
            avg_delta_pct = (avg_delta / current_price * 100.0) if current_price > 0 else 0.0
            is_reversing = (recent_deltas[-1] < 0 and recent_deltas[-2] < 0)

        # Velocity Circuit Breaker (Black Swan Trend Shield)
        # If price moves parabolically in one direction (> 1.2% move in 10 ticks) with 2+ open positions,
        # execute early trend protection exit to cap drawdown at minimal loss!
        velocity_shield_hit = False
        if len(self.broker.open_positions) >= 2 and len(self.price_history_ticks) >= 5:
            total_delta_pct = abs(self.price_history_ticks[-1] - self.price_history_ticks[0]) / self.price_history_ticks[0] * 100.0
            if total_delta_pct >= 1.2 and float_pnl < 0:
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
        momentum_scalp_hit = False
        wvap_exit_hit = False
        single_fill_scalp_hit = False

        # SMART TIMEOUT: Only exits if PnL is at or above breakeven (friction_floor).
        # If the cycle is in the red when time expires, do NOT force-exit — let Stop Loss
        # handle it. A forced exit at a loss is always mathematically worse than waiting.
        elapsed = timestamp - self.cycle_start_time
        _timed_out = elapsed >= self.max_cycle_duration and len(self.broker.open_positions) > 0
        timeout_hit = _timed_out and (float_pnl >= friction_floor)

        if len(self.broker.open_positions) > 0:
            # 0. PROP FIRM COMPLIANCE GUARD CHECK
            if getattr(self, "prop_firm_guard_enabled", False):
                daily_limit = 10000.0 * (getattr(self, "prop_firm_max_daily_drawdown_pct", 4.5) / 100.0)
                if float_pnl <= -daily_limit:
                    prop_guard_hit = True

            # 0. PURE DYNAMIC RISK-SCALED STOP LOSS ENGINE (Zero Hardcoded Stop Loss)
            # Dynamically scales Stop Loss based on account balance/equity and open grid basket volume
            account_eq = getattr(self.broker, "account_equity", getattr(self.broker, "initial_balance", 1000.0))
            max_eq_risk_pct = getattr(self, "stop_loss_pct", 10.0)
            
            # Basket Volume Multiplier: 1 fill = 1.0x, 2 fills = 1.25x, 3 fills = 1.50x, 4+ fills = 1.75x
            num_open = len(self.broker.open_positions)
            volume_risk_scale = 1.0 + (max(0, num_open - 1) * 0.25)
            
            dynamic_sl_dollar = max(50.0, account_eq * (max_eq_risk_pct / 100.0) * volume_risk_scale)
            effective_stop_loss = max(self.stop_loss, dynamic_sl_dollar) if self.stop_loss > 0 else dynamic_sl_dollar

            if float_pnl <= -effective_stop_loss:
                stop_loss_hit = True

            # Update max PnL
            if float_pnl > getattr(self, 'max_floating_pnl', -float("inf")):
                self.max_floating_pnl = float_pnl

            # 1. SMART PROFIT EXPANSION & DYNAMIC VOLUME-SCALED TARGET PROFIT
            num_fills = len(self.broker.open_positions)
            total_basket_lots = sum(p.size for p in self.broker.open_positions.values())
            base_size = max(0.0001, getattr(self, "order_size", 0.01))
            volume_scale_mult = max(1.0, total_basket_lots / base_size)
            effective_target_profit = max(self.target_profit * volume_scale_mult, friction_floor + 1.00)

            if self.use_smart_trailing and float_pnl >= effective_target_profit:
                if not self.in_runner_mode:
                    self.in_runner_mode = True
                    self.max_floating_pnl = float_pnl
                    # Immediately cancel pending traps on Target Profit reach to lock in runner gains
                    try:
                        self.broker.cancel_all_orders()
                    except Exception as err:
                        print(f"Failed to cancel pending orders on Runner Mode entry: {err}")

            if self.in_runner_mode:
                lock_pct = 0.90 if is_reversing else getattr(self, 'profit_lock_pct', 0.80)
                # Unbreakable net-positive floor: strictly >= friction_floor + $1.00 to guarantee ZERO loss
                unbreakable_net_floor = max(friction_floor + 1.00, effective_target_profit * 0.50)
                trailing_peak_floor = self.max_floating_pnl * lock_pct
                runner_floor = max(unbreakable_net_floor, trailing_peak_floor)
                if float_pnl <= runner_floor and float_pnl >= friction_floor + 1.00:
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

                if float_pnl >= effective_target_profit and float_pnl >= friction_floor + 1.00 and is_price_in_profit_direction and min_dist_met:
                    target_hit = True

            # 2. MULTI-STAGE RATCHETED BREAKEVEN PROTECTION
            if self.use_breakeven:
                # Stage 1: 50% Target Profit hit -> Lock floor at friction_floor to guarantee net positive profit after fees
                if float_pnl >= self.target_profit * getattr(self, "breakeven_trigger", 0.5):
                    self.breakeven_activated = True
                    stage1_target = max(friction_floor, min(float_pnl - 1.00, self.target_profit * 0.40))
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage1_target)
                
                # Stage 2: 75% Target Profit hit -> Ratchet floor up to 50% TP
                if float_pnl >= self.target_profit * 0.75:
                    stage2_target = max(friction_floor + 2.00, min(float_pnl - 1.00, self.target_profit * 0.55))
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage2_target)

                # Stage 3: 90% Target Profit hit -> Ratchet floor up to 75% TP
                if float_pnl >= self.target_profit * 0.90:
                    stage3_target = max(friction_floor + 4.00, min(float_pnl - 1.00, self.target_profit * 0.75))
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage3_target)

            if self.use_breakeven and self.breakeven_activated and not self.in_runner_mode:
                active_ratchet = getattr(self, "ratchet_floor", 0.0)
                if active_ratchet > 0 and float_pnl <= active_ratchet:
                    breakeven_hit = True

            # 3. TRAILING STOP (when not in runner mode)
            if self.use_trailing_stop and not self.in_runner_mode:
                if self.max_floating_pnl >= self.trailing_stop_distance:
                    trail_dist = self.trailing_stop_distance * (1.5 if avg_delta > 0 else 1.0)
                    trailing_level = self.max_floating_pnl - trail_dist
                    if trailing_level > 0 and float_pnl <= trailing_level and float_pnl >= friction_floor:
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

            # 5. HEDGE-LOCK UN-LOCK CHECK (When positions exist in BOTH directions)
            hedge_lock_hit = False
            buy_positions = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
            sell_positions = [p for p in self.broker.open_positions.values() if p.type == "SELL"]
            if buy_positions and sell_positions:
                if float_pnl >= volume_friction_target:
                    hedge_lock_hit = True

            # 5b. DYNAMIC COUNTER-HEDGE REVERSAL LOCK (Converts single-side trend drawdown into market-neutral dual basket)
            # If a single-side basket enters floating drawdown >= 35% of effective_stop_loss during a strong move,
            # automatically deploy a counter-hedge order to lock floating drawdown and allow market-neutral recovery!
            if len(self.broker.open_positions) >= 2 and not hedge_lock_hit:
                buy_pos_count = len(buy_positions)
                sell_pos_count = len(sell_positions)
                
                # Single-side basket experiencing trend drawdown
                if (buy_pos_count > 0 and sell_pos_count == 0) or (sell_pos_count > 0 and buy_pos_count == 0):
                    hedge_threshold = effective_stop_loss * 0.35
                    if float_pnl <= -hedge_threshold and len(self.broker.pending_orders) < 2:
                        hedge_side = "SELL_STOP" if buy_pos_count > 0 else "BUY_STOP"
                        hedge_dist_pct = getattr(self, "trap_offset", 0.07) * 0.50
                        hedge_px = round(current_price * (1.0 - hedge_dist_pct / 100.0) if hedge_side == "SELL_STOP" else current_price * (1.0 + hedge_dist_pct / 100.0), 2)
                        hedge_size = max(0.01, round(total_basket_lots * 0.75, 4))
                        try:
                            self.broker.place_order(hedge_side, hedge_px, hedge_size, timestamp)
                        except Exception:
                            pass

            # 6. MICRO-VELOCITY MOMENTUM SCALP EXIT (True Trend Reversal Guard)
            momentum_scalp_hit = False
            if len(self.broker.open_positions) > 0 and float_pnl >= volume_friction_target:
                if len(self.price_history_ticks) >= 5 and is_reversing and float_pnl < getattr(self, "max_floating_pnl", float_pnl) * 0.85:
                    momentum_scalp_hit = True

            # 7. VOLUME WEIGHTED AVERAGE COST RECOVERY EXIT (WVAP Exit on 2+ Fills)
            wvap_exit_hit = False
            if len(self.broker.open_positions) >= 2 and not self.in_runner_mode:
                wvap_target = max(volume_friction_target, friction_floor + 1.00)
                if float_pnl >= wvap_target:
                    wvap_exit_hit = True

            # 8. SINGLE-FILL QUICK PERCENT SCALP EXIT (Equalized for Crypto & Gold)
            single_fill_scalp_hit = False
            if len(self.broker.open_positions) == 1 and not self.in_runner_mode:
                open_pos = list(self.broker.open_positions.values())[0]
                entry_px = getattr(open_pos, 'open_price', getattr(open_pos, 'price', getattr(open_pos, 'entry_price', current_price)))
                if open_pos.type == "BUY":
                    move_pct = (current_price - entry_px) / entry_px * 100.0
                else:
                    move_pct = (entry_px - current_price) / entry_px * 100.0
                
                target_move_threshold = max(0.08, getattr(self, "trap_offset", 0.08) * 0.90)
                if move_pct >= target_move_threshold and float_pnl >= volume_friction_target and not is_positive_trend:
                    single_fill_scalp_hit = True

        if target_hit or runner_hit or trailing_stop_hit or stop_loss_hit or timeout_hit or breakeven_hit or early_range_hit or prop_guard_hit or hedge_lock_hit or velocity_shield_hit or momentum_scalp_hit or wvap_exit_hit or single_fill_scalp_hit:
            if single_fill_scalp_hit: reason = "SINGLE_FILL_QUICK_SCALP"
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
            
            # Reset breakeven & runner state for next cycle
            self.breakeven_activated = False
            self.ratchet_floor = 0.0
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

            trades_count = len(closed_trades)
            cycle_pnl = sum(t["pnl"] for t in closed_trades)
            if not closed_trades:
                # Fallback: positions may have been closed externally by MT5 or the user
                cycle_pnl = self.broker.realized_pnl - _pnl_before

            cycle_summary = {
                "cycle_id": self.current_cycle_id,
                "deploy_price": self.deploy_price,
                "exit_price": current_price,
                "pnl": cycle_pnl,
                "trades_count": trades_count,
                "start_time": self.cycle_start_time,
                "exit_time": timestamp,
                "exit_reason": reason
            }
            self.cycle_history.append(cycle_summary)

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

            # FIX 4: Clear runner mode BEFORE calling deploy_traps so the runner guard
            # inside deploy_traps doesn't block the fresh grid after a cycle exit.
            self.in_runner_mode = False

            if self.auto_restart:
                # Instantly deploy new traps at the new current price
                self.deploy_traps(current_price, timestamp)
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
