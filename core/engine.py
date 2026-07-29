import uuid
import time
from typing import Dict, List, Optional, Any, TYPE_CHECKING

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


class BreakoutGridBot:
    def __init__(
        self,
        broker: 'MT5Broker',
        grid_levels: int = 5,
        grid_gap: float = 10.0,
        trap_offset: float = 5.0,
        order_size: float = 0.1,
        order_size_multiplier: float = 1.0,
        target_profit: float = 10.0,
        auto_restart: bool = True,
        is_percent: bool = False,
        stop_loss: float = 20.0,
        max_cycle_duration: float = 3600.0,
        cancel_opposite_on_trigger: bool = False,
        use_trailing_stop: bool = False,
        trailing_stop_distance: float = 15.0,
        use_bb_filter: bool = False,
        bb_squeeze_threshold: float = 0.02,
        use_breakeven: bool = False,
        breakeven_trigger: float = 0.5,
        use_smart_trailing: bool = True,
        profit_lock_pct: float = 0.80,
        use_adaptive_gap: bool = False,
        base_bb_width: float = 0.005,
        adaptive_gap_min_mult: float = 0.5,
        adaptive_gap_max_mult: float = 2.5
    ):
        self.broker = broker
        self.grid_levels = grid_levels
        self.grid_gap = grid_gap
        self.trap_offset = trap_offset
        self.order_size = order_size
        self.order_size_multiplier = order_size_multiplier
        self.target_profit = target_profit
        self.auto_restart = auto_restart
        self.is_percent = is_percent
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

            # Clamp to safe max order size cap if set (default 50.0 lots)
            max_cap = getattr(self, "max_order_size", 50.0)
            if max_cap > 0 and size > max_cap:
                size = max_cap
        else:
            # Anti-Martingale (mult < 1.0): Ensure size doesn't drop below 0.001
            if size < 0.001:
                size = 0.001

        return round(size, 8)

    def deploy_traps(self, current_price: float, timestamp: float, bb_width: Optional[float] = None):
        """
        Cancel existing traps and place a new grid of traps centered around current_price.
        If use_bb_filter is True, deployment will be skipped if bb_width is missing or > threshold.
        """
        if self.use_bb_filter:
            if bb_width is None or bb_width > self.bb_squeeze_threshold:
                return

        effective_gap = self.get_effective_gap(current_price, bb_width)

        self.broker.cancel_all_orders()
        self.deploy_price = current_price
        self.deploy_order_size = self.order_size
        self.deploy_order_size_multiplier = self.order_size_multiplier
        self.deploy_grid_gap = effective_gap
        self.deploy_trap_offset = self.trap_offset
        self.cycle_start_time = timestamp
        self.max_floating_pnl = -float("inf")
        self.in_runner_mode = False
        self.price_history_ticks.clear()
        self._last_trigger_time = timestamp

        # Calculate absolute gap and offset
        if self.is_percent:
            offset_val = current_price * (self.trap_offset / 100.0)
            gap_val = current_price * (effective_gap / 100.0)
        else:
            offset_val = self.trap_offset
            gap_val = effective_gap

        try:
            # Place Buy Stop orders above the current price with strict Martingale scaling
            for i in range(self.grid_levels):
                trigger_price = current_price + offset_val + (i * gap_val)
                level_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                self.broker.place_order("BUY_STOP", trigger_price, level_size, timestamp)

            # Place Sell Stop orders below the current price with strict Martingale scaling
            for i in range(self.grid_levels):
                trigger_price = current_price - offset_val - (i * gap_val)
                level_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                self.broker.place_order("SELL_STOP", trigger_price, level_size, timestamp)

            self.deployed = True
        except Exception as e:
            # Rollback: Clean up any pending orders placed during this failed deployment to avoid orphans
            print(f"Failed to deploy grid traps. Rolling back: {e}")
            try:
                self.broker.cancel_all_orders()
            except Exception as rollback_err:
                print(f"Deployment rollback cleanup failed: {rollback_err}")
            self.deployed = False
            raise e

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

        center_price = self.deploy_price if self.deploy_price > 0 else current_price
        base_size = getattr(self, "deploy_order_size", self.order_size)
        mult = getattr(self, "deploy_order_size_multiplier", self.order_size_multiplier)
        gap_config = getattr(self, "deploy_grid_gap", self.grid_gap)
        offset_config = getattr(self, "deploy_trap_offset", self.trap_offset)

        if self.is_percent:
            offset_val = center_price * (offset_config / 100.0)
            gap_val = center_price * (gap_config / 100.0)
        else:
            offset_val = offset_config
            gap_val = gap_config

        # Collect existing pending trigger prices AND open position entry prices to prevent duplication
        buy_pending = [o for o in self.broker.pending_orders.values() if o.type == "BUY_STOP"]
        buy_open = [p for p in self.broker.open_positions.values() if p.type == "BUY"]
        sell_pending = [o for o in self.broker.pending_orders.values() if o.type == "SELL_STOP"]
        sell_open = [p for p in self.broker.open_positions.values() if p.type == "SELL"]

        existing_buy_levels = [o.trigger_price for o in buy_pending] + [p.entry_price for p in buy_open]
        existing_sell_levels = [o.trigger_price for o in sell_pending] + [p.entry_price for p in sell_open]

        placed_count = 0
        try:
            buy_placed = 0
            sell_placed = 0
            # Check and place missing BUY_STOP levels ONLY if total BUY levels < self.grid_levels
            if len(buy_pending) + len(buy_open) < self.grid_levels:
                for i in range(self.grid_levels):
                    if len(buy_pending) + len(buy_open) + buy_placed >= self.grid_levels:
                        break
                    target_price = center_price + offset_val + (i * gap_val)
                    # Only place if target price is above current_price and level doesn't exist in pending OR open positions
                    if target_price > current_price and not any(abs(target_price - ex) < (gap_val * 0.4) for ex in existing_buy_levels):
                        level_size = self.calculate_level_size(base_size, mult, i)
                        self.broker.place_order("BUY_STOP", target_price, level_size, timestamp)
                        buy_placed += 1

            # Check and place missing SELL_STOP levels ONLY if total SELL levels < self.grid_levels
            if len(sell_pending) + len(sell_open) < self.grid_levels:
                for i in range(self.grid_levels):
                    if len(sell_pending) + len(sell_open) + sell_placed >= self.grid_levels:
                        break
                    target_price = center_price - offset_val - (i * gap_val)
                    # Only place if target price is below current_price and level doesn't exist in pending OR open positions
                    if target_price < current_price and not any(abs(target_price - ex) < (gap_val * 0.4) for ex in existing_sell_levels):
                        level_size = self.calculate_level_size(base_size, mult, i)
                        self.broker.place_order("SELL_STOP", target_price, level_size, timestamp)
                        sell_placed += 1

            placed_count = buy_placed + sell_placed
            self.deployed = True
        except Exception as e:
            print(f"Notice: Grid repair encountered non-critical order placement error: {e}")

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

        if self.is_percent:
            offset_val = center_price * (self.trap_offset / 100.0)
            gap_val = center_price * (self.grid_gap / 100.0)
        else:
            offset_val = self.trap_offset
            gap_val = self.grid_gap

        tolerance = gap_val * 0.5

        # Build the set of valid grid prices (expected levels)
        valid_buy_levels = [center_price + offset_val + (i * gap_val) for i in range(self.grid_levels)]
        valid_sell_levels = [center_price - offset_val - (i * gap_val) for i in range(self.grid_levels)]

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
        if not self.deployed and self.auto_restart:
            self.deploy_traps(current_price, timestamp, bb_width)

        if not self.deployed:
            return None

        # ── RUNNER EXIT COOLDOWN ─────────────────────────────────────────────────
        # After Runner Mode exits, wait briefly before processing new triggers
        # to avoid the first grid trap filling instantly on a still-trending price.
        if timestamp < getattr(self, '_runner_exit_cooldown_until', 0.0):
            return None
        # ─────────────────────────────────────────────────────────────────────────

        # Let broker process the price tick to trigger any pending orders
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

        # Automatic Grid Repair check: if positions are open and not in Runner Mode, maintain grid trap density
        if len(self.broker.open_positions) > 0 and not getattr(self, "in_runner_mode", False):
            if len(self.broker.pending_orders) < (self.grid_levels * 2):
                try:
                    self.repair_grid(current_price, timestamp)
                except Exception as repair_err:
                    print(f"Auto-repair notice: {repair_err}")

        # Track tick price history and velocity (Delta P / Delta t)
        self.price_history_ticks.append(current_price)
        if len(self.price_history_ticks) > 10:
            self.price_history_ticks.pop(0)

        avg_delta = 0.0
        is_reversing = False
        if len(self.price_history_ticks) >= 3:
            recent_deltas = [self.price_history_ticks[i] - self.price_history_ticks[i-1] for i in range(1, len(self.price_history_ticks))]
            avg_delta = sum(recent_deltas) / len(recent_deltas)
            is_reversing = (recent_deltas[-1] < 0 and recent_deltas[-2] < 0)

        # Dynamic friction floor based on open position count to cover spread & fees
        num_pos = len(self.broker.open_positions)
        friction_floor = max(3.00, 3.00 + (num_pos * 0.75))

        # ── STAGNANT GRID AUTO-REDEPLOY ─────────────────────────────────────────
        # If the grid has had zero fills for a long time AND no positions are open,
        # the market has moved far from the deploy price. Snap the grid to current price.
        _stagnant_redeploy_interval = self.max_cycle_duration * 0.5  # Half of max duration
        _no_positions = len(self.broker.open_positions) == 0
        _last_trig = getattr(self, '_last_trigger_time', self.cycle_start_time)
        _stagnant = (timestamp - _last_trig) >= _stagnant_redeploy_interval
        _past_cooldown = timestamp >= getattr(self, '_runner_exit_cooldown_until', 0.0)
        if _no_positions and _stagnant and self.deployed and self.auto_restart and _past_cooldown:
            # Price has drifted — silently redeploy at current price with no cycle record
            self.deploy_traps(current_price, timestamp, bb_width)
            return None  # No cycle exit, just a silent recenter
        # ─────────────────────────────────────────────────────────────────────────

        # Check exit conditions
        target_hit = False
        runner_hit = False
        trailing_stop_hit = False
        stop_loss_hit = False
        breakeven_hit = False

        # SMART TIMEOUT: Only exits if PnL is at or above breakeven (friction_floor).
        # If the cycle is in the red when time expires, do NOT force-exit — let Stop Loss
        # handle it. A forced exit at a loss is always mathematically worse than waiting.
        elapsed = timestamp - self.cycle_start_time
        _timed_out = elapsed >= self.max_cycle_duration and len(self.broker.open_positions) > 0
        timeout_hit = _timed_out and (float_pnl >= friction_floor)

        if len(self.broker.open_positions) > 0:
            # Update max PnL
            if float_pnl > getattr(self, 'max_floating_pnl', -float("inf")):
                self.max_floating_pnl = float_pnl

            # 1. SMART PROFIT EXPANSION (RUNNER MODE)
            if self.use_smart_trailing and float_pnl >= self.target_profit:
                if not self.in_runner_mode:
                    self.in_runner_mode = True
                    # Immediately cancel all pending traps to prevent opposite triggers during pullback!
                    try:
                        self.broker.cancel_all_orders()
                    except Exception as err:
                        print(f"Failed to cancel pending orders on Runner Mode entry: {err}")

            if self.in_runner_mode:
                lock_pct = 0.90 if is_reversing else getattr(self, 'profit_lock_pct', 0.80)
                hard_min_floor = max(self.target_profit * 0.50, friction_floor + 2.00)
                # Cushion peak floor so 1-tick spread noise ($2.50) right after target hit doesn't trigger exit immediately
                cushioned_peak_floor = max(hard_min_floor, self.max_floating_pnl - max(2.50, self.max_floating_pnl * (1.0 - lock_pct)))
                runner_floor = min(cushioned_peak_floor, self.max_floating_pnl * lock_pct)
                if float_pnl <= runner_floor:
                    runner_hit = True
            else:
                # Standard Target Profit (if Smart Runner Mode is disabled)
                if float_pnl >= self.target_profit:
                    target_hit = True

            # 2. MULTI-STAGE RATCHETED BREAKEVEN PROTECTION
            if self.use_breakeven:
                # Stage 1: 50% Target Profit hit -> Lock floor below current PnL (capped by friction_floor)
                if float_pnl >= self.target_profit * getattr(self, "breakeven_trigger", 0.5):
                    self.breakeven_activated = True
                    stage1_target = min(float_pnl - 1.00, friction_floor)
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), max(1.00, stage1_target))
                
                # Stage 2: 75% Target Profit hit -> Ratchet floor up to 50% TP (never exceeding float_pnl - 1.00)
                if float_pnl >= self.target_profit * 0.75:
                    stage2_target = min(float_pnl - 1.00, max(friction_floor + 2.00, self.target_profit * 0.50))
                    self.ratchet_floor = max(getattr(self, "ratchet_floor", 0.0), stage2_target)

                # Stage 3: 90% Target Profit hit -> Ratchet floor up to 70% TP (never exceeding float_pnl - 1.00)
                if float_pnl >= self.target_profit * 0.90:
                    stage3_target = min(float_pnl - 1.00, max(friction_floor + 4.00, self.target_profit * 0.70))
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
                    
            # 4. SMART EARLY RANGE EXIT (On 3+ Level Fills during Range Chop)
            # When 3 or more grid levels fill and price recovers back to 50% Target Profit (+$5.00+),
            # exit with solid positive profit instead of wasting the trade cycle!
            early_range_hit = False
            if len(self.broker.open_positions) >= 3 and not self.in_runner_mode:
                target_floor = max(self.target_profit * 0.50, friction_floor + 2.00)
                if float_pnl >= target_floor:
                    early_range_hit = True

        if target_hit or runner_hit or trailing_stop_hit or stop_loss_hit or timeout_hit or breakeven_hit or early_range_hit:
            if runner_hit:          reason = "RUNNER_EXPANSION"
            elif target_hit:        reason = "TARGET_PROFIT"
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

            self.current_cycle_id += 1

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
