import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception as e:
        import logging; logging.warning(f"Exception: {e}")

import uuid
import time
import datetime
import numpy as np
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING


class Order:
    def __init__(self, type: str, trigger_price: float, size: float, timestamp: float):
        self.order_id = str(uuid.uuid4())[:8]
        self.type = type
        self.trigger_price = trigger_price
        self.size = size
        self.timestamp = timestamp
        self.tp = 0.0   # Take Profit price (0 = not set)
        self.sl = 0.0   # Stop Loss price (0 = not set)

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "type": self.type,
            "trigger_price": self.trigger_price,
            "size": self.size,
            "timestamp": self.timestamp
        }

class Position:
    def __init__(self, type: str, entry_price: float, size: float, entry_time: float, pos_id: Optional[str] = None):
        self.position_id = str(pos_id) if pos_id else str(uuid.uuid4())[:8]
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


from core.auto_reading import (
    AutoReadingEngine,
    PAIR_PRIORITY_REGISTRY,
    _ORDERS_PER_SLOT,
    select_active_pairs,
    get_pair_gold_params,
    PAIR_SAFETY_BOUNDS,
    clamp_symbol_lot_size
)
from core.grid_risk import (
    get_pip_size,
    sanitize_order_size,
    calculate_ratchet_breakeven
)


class BreakoutGridBot:
    def __init__(
        self,
        broker: 'MT5Broker',
        symbol: str = "PAXGUSDT",
        grid_levels: int = 5,
        grid_gap: float = 10.0,
        trap_offset: float = 5.0,
        order_size: float = 0.01,
        order_size_multiplier: float = 1.0,
        target_profit: float = 0.50,
        auto_restart: bool = True,
        is_percent: bool = False,
        spacing_mode: Optional[str] = None,
        stop_loss: float = 0.0,
        max_cycle_duration: float = float("inf"),
        cancel_opposite_on_trigger: bool = True,
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
        pending_order_side_mode: str = "AUTO_ADAPTIVE",
        symbol_code: Optional[str] = None,
        **kwargs
    ):
        self.symbol_code = symbol_code or symbol
        self.symbol = self.symbol_code
        self.broker = broker
        self.grid_levels = min(5, max(1, int(grid_levels)))
        self.grid_gap = grid_gap
        self.trap_offset = trap_offset
        self.order_size = order_size
        self.order_size_multiplier = min(1.30, max(1.0, float(order_size_multiplier)))
        self.max_basket_drawdown_pct = 0.05
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
        self.breakeven_trigger = breakeven_trigger
        self.use_smart_trailing = use_smart_trailing
        self.profit_lock_pct = profit_lock_pct
        self.use_adaptive_gap = use_adaptive_gap
        self.use_auto_reading = bool(use_auto_reading)
        if self.use_auto_reading:
            self.auto_reading_engine = AutoReadingEngine()


        sym_str = getattr(self.broker, "symbol", getattr(self, "symbol", ""))
        self._order_size = sanitize_order_size(sym_str, order_size)

        self.max_daily_drawdown: float = 0.0
        self.daily_circuit_breaker_tripped: bool = False
        self.use_news_shield: bool = True

        self.prop_firm_guard_enabled: bool = False
        self.prop_firm_max_daily_drawdown_pct: float = 4.5
        self.prop_firm_target_pct: float = 8.0

        sym_str_upper = sym_str.upper()
        is_crypto_247 = False
        self.use_weekend_shutdown: bool = not is_crypto_247
        self.weekend_shutdown_utc_hour: int = 20
        self.weekend_shutdown_utc_minute: int = 30
        self.weekend_reopen_utc_hour: int = 22
        self.weekend_reopen_utc_minute: int = 30
        self.weekend_shutdown_triggered: bool = False

        self.use_grid_repair: bool = False
        self.use_auto_cleanup: bool = False

        self.use_self_learning: bool = True
        self.trade_history: List[dict] = []
        self.learned_win_rate: float = 75.0
        self.learned_profit_factor: float = 2.0
        self.learned_tuning_mult: float = 1.00
        self.learned_runner_lock_boost: float = 0.00

        self.deployed = False
        self.deploy_price = 0.0
        self.current_cycle_id = 1
        
        self.cycle_history = []
        self.cycle_start_time = 0.0
        self.max_floating_pnl = -float("inf")
        self.breakeven_activated = False
        self.in_runner_mode = False
        self.price_history_ticks: List[float] = []
        self._last_trigger_time: float = 0.0
        self._runner_exit_cooldown_until: float = 0.0

        self._fakeout_guard_enabled: bool = False
        self._fakeout_guard_ticks: int = 8
        self._fakeout_recent_fills: dict = {}
        self._tick_counter: int = 0

        self.use_smc_elliott: bool = True
        self._last_smc_eval: dict = {}

    def is_weekend_market_paused(self, now_utc: datetime.datetime) -> bool:
        if not getattr(self, "use_weekend_shutdown", True):
            return False
        
        weekday = now_utc.weekday()
        sd_h = getattr(self, "weekend_shutdown_utc_hour", 20)
        sd_m = getattr(self, "weekend_shutdown_utc_minute", 30)
        ro_h = getattr(self, "weekend_reopen_utc_hour", 22)
        ro_m = getattr(self, "weekend_reopen_utc_minute", 30)

        if weekday == 4:
            return (now_utc.hour > sd_h) or (now_utc.hour == sd_h and now_utc.minute >= sd_m)
        if weekday == 5:
            return True
        if weekday == 6:
            return (now_utc.hour < ro_h) or (now_utc.hour == ro_h and now_utc.minute < ro_m)
        
        return False

    def is_high_impact_news_blackout(self, timestamp: float) -> bool:
        if not getattr(self, "use_news_shield", True):
            return False
        try:
            from core.data import get_economic_calendar
            events = get_economic_calendar()
            if not events:
                return False
            
            curr_sec = (timestamp / 1000.0) if timestamp > 1e11 else timestamp
            for ev in events:
                if ev.get("impact") == "HIGH":
                    ev_ts = ev.get("timestamp", 0.0)
                    if ev_ts > 0:
                        if abs(curr_sec - ev_ts) <= 900.0:
                            return True
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")
        return False

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
        sym = str(getattr(self, "symbol", getattr(getattr(self, "broker", None), "symbol", "")) or "").upper()
        # Gold / PAXG: Strict capital protection — ALWAYS flat lot sizing (no Martingale escalation!)
        if any(x in sym for x in ["XAU", "GOLD", "PAXG"]):
            return round(base_size, 2)

        if mult == 1.0 or level_idx == 0:
            return round(base_size, 8)

        raw_size = base_size * (mult ** level_idx)
        size = round(raw_size, 8)

        if mult > 1.0:
            prev_raw = base_size * (mult ** (level_idx - 1))
            prev_size = round(prev_raw, 8)
            
            if size <= prev_size:
                size = prev_size + 0.01

            size = min(size, 0.10)
        else:
            if size < 0.01:
                size = 0.01

        return round(min(size, 0.10), 2)

    def ensure_attributes_initialized(self):
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
            self.use_news_shield = True
        if not hasattr(self, "prop_firm_guard_enabled"):
            self.prop_firm_guard_enabled = True
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
        # ── Industry-grade 3-stage TP state flags ──────────────────────────
        if not hasattr(self, "_tp1_buy_taken"):
            self._tp1_buy_taken = False
        if not hasattr(self, "_tp1_sell_taken"):
            self._tp1_sell_taken = False
        if not hasattr(self, "_tp2_buy_taken"):
            self._tp2_buy_taken = False
        if not hasattr(self, "_tp2_sell_taken"):
            self._tp2_sell_taken = False
        if not hasattr(self, "_chandelier_buy_high"):
            self._chandelier_buy_high = 0.0
        if not hasattr(self, "_chandelier_sell_low"):
            self._chandelier_sell_low = 0.0
        if not hasattr(self, "_last_partial_tp_time"):
            self._last_partial_tp_time = 0.0
        # ── Profit Lock state flags ────────────────────────────────────────
        if not hasattr(self, "_last_profit_lock_time"):
            self._last_profit_lock_time = 0.0
        if not hasattr(self, "_early_profit_ticks"):
            self._early_profit_ticks = 0
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
            self.grid_levels = 5
        if not hasattr(self, "grid_gap"):
            self.grid_gap = 0.30
        if not hasattr(self, "trap_offset"):
            self.trap_offset = 0.15
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
        if not hasattr(self, "use_auto_reading"):
            self.use_auto_reading = False
        if not hasattr(self, "auto_profile"):
            self.auto_profile = "BALANCED"
        if not hasattr(self, "pending_order_side_mode"):
            self.pending_order_side_mode = "AUTO_ADAPTIVE"
        if getattr(self, "use_auto_reading", False) and not hasattr(self, "auto_reading_engine"):
            self.auto_reading_engine = AutoReadingEngine()
        if not hasattr(self, "_fakeout_guard_enabled"):
            self._fakeout_guard_enabled = False
        if not hasattr(self, "_fakeout_guard_ticks"):
            self._fakeout_guard_ticks = 8
        if not hasattr(self, "_fakeout_recent_fills"):
            self._fakeout_recent_fills = {}
        if not hasattr(self, "_tick_counter"):
            self._tick_counter = 0
        if not hasattr(self, "use_smc_elliott"):
            self.use_smc_elliott = True
        if not hasattr(self, "_last_smc_eval"):
            self._last_smc_eval = {}

    def deploy_traps(self, current_price: float, timestamp: float, *args, force: bool = False, bb_width: Optional[float] = None, **kwargs):
        import core.grid_risk as gr
        return gr.deploy_traps(self, current_price, timestamp, *args, force=force, bb_width=bb_width, **kwargs)

    def repair_grid(self, current_price: float, timestamp: float) -> int:
        import core.grid_risk as gr
        return gr.repair_grid(self, current_price, timestamp)

    def cleanup_stale_grid_orders(self, current_price: float) -> int:
        import core.grid_risk as gr
        return gr.cleanup_stale_grid_orders(self, current_price)

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, bb_width: Optional[float] = None) -> Optional[dict]:
        from core.grid_risk import process_engine_tick
        return process_engine_tick(self, previous_price, current_price, timestamp, bb_width)

    def process_live_tick(self, current_price: Optional[float] = None, timestamp: Optional[float] = None) -> Optional[dict]:
        from core.data import get_live_price
        ts = timestamp if timestamp else time.time()
        if current_price is None or current_price <= 0:
            current_price = get_live_price(self.symbol)
        
        if not current_price or current_price <= 0:
            return None
        
        prev_price = getattr(self, "_last_seen_price", current_price) or current_price
        self._last_seen_price = current_price
        
        return self.process_tick(prev_price, current_price, ts)

    def record_trade_outcome(self, pnl: float, exit_reason: str, duration: float, exit_price: float = 0.0):
        import core.grid_risk as gr
        return gr.record_trade_outcome(self, pnl, exit_reason, duration, exit_price)

    def get_self_learning_metrics(self) -> dict:
        import core.grid_risk as gr
        return gr.get_self_learning_metrics(self)

    def check_target_profit(self, current_price: float, timestamp: float) -> Optional[dict]:
        from core.grid_risk import check_target_profit
        return check_target_profit(self, current_price, timestamp)

    def sync_cycle_history_from_trades(self):
        import core.grid_risk as gr
        return gr.sync_cycle_history_from_trades(self)


