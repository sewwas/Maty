import uuid
import time
from typing import Dict, List, Optional

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

class SimulatedBroker:
    def __init__(self, initial_balance: float = 10000.0, commission_pct: float = 0.0, slippage_pct: float = 0.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        
        self.pending_orders: Dict[str, Order] = {}
        self.open_positions: Dict[str, Position] = {}
        self.closed_trades: List[dict] = []
        self.realized_pnl = 0.0

    def reset(self):
        self.balance = self.initial_balance
        self.pending_orders.clear()
        self.open_positions.clear()
        self.closed_trades.clear()
        self.realized_pnl = 0.0

    def place_order(self, type: str, trigger_price: float, size: float, timestamp: float) -> Order:
        order = Order(type, trigger_price, size, timestamp)
        self.pending_orders[order.order_id] = order
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        return self.pending_orders.pop(order_id, None)

    def cancel_all_orders(self):
        self.pending_orders.clear()

    def get_floating_pnl(self, current_price: float) -> float:
        return sum(pos.get_pnl(current_price) for pos in self.open_positions.values())

    def sync(self):
        pass

    def get_all_account_positions(self) -> list:
        return []

    def get_equity(self, current_price: float) -> float:
        return self.balance + self.get_floating_pnl(current_price)

    def close_position(self, position_id: str, exit_price: float, timestamp: float) -> Optional[dict]:
        pos = self.open_positions.pop(position_id, None)
        if not pos:
            return None

        # Apply slippage (against the trade exit)
        if pos.type == "BUY":
            fill_exit_price = exit_price * (1 - self.slippage_pct)
        else:
            fill_exit_price = exit_price * (1 + self.slippage_pct)

        # Calculate trade PnL
        pnl = (fill_exit_price - pos.entry_price) * pos.size if pos.type == "BUY" else (pos.entry_price - fill_exit_price) * pos.size
        
        # Calculate exit commission
        trade_value = pos.size * fill_exit_price
        exit_commission = trade_value * self.commission_pct

        # Update balance and statistics
        self.balance += pnl - exit_commission
        self.realized_pnl += pnl - exit_commission

        trade_record = {
            "position_id": pos.position_id,
            "type": pos.type,
            "entry_price": pos.entry_price,
            "exit_price": fill_exit_price,
            "size": pos.size,
            "pnl": pnl - exit_commission,
            "entry_time": pos.entry_time,
            "exit_time": timestamp,
            "commission": exit_commission
        }
        self.closed_trades.append(trade_record)
        return trade_record

    def close_all_positions(self, exit_price: float, timestamp: float) -> List[dict]:
        closed_records = []
        # Copy keys to avoid modification during iteration
        for pos_id in list(self.open_positions.keys()):
            record = self.close_position(pos_id, exit_price, timestamp)
            if record:
                closed_records.append(record)
        return closed_records

    def process_tick(self, previous_price: float, current_price: float, timestamp: float) -> List[Position]:
        """
        Check if any pending orders are triggered.
        Handles tick movements.
        """
        triggered_positions = []
        orders_to_trigger = []

        # Find orders that were triggered in this price movement
        for order in list(self.pending_orders.values()):
            triggered = False
            if order.type == "BUY_STOP":
                # Triggered if price crosses upwards past the trigger price
                if previous_price <= order.trigger_price <= current_price or current_price >= order.trigger_price:
                    triggered = True
            elif order.type == "SELL_STOP":
                # Triggered if price crosses downwards past the trigger price
                if previous_price >= order.trigger_price >= current_price or current_price <= order.trigger_price:
                    triggered = True

            if triggered:
                orders_to_trigger.append(order)

        # Sort triggered orders so that they trigger in the order of distance to prevent wrong sequence (simulated)
        # e.g., if price jumps, the closest order triggers first
        orders_to_trigger.sort(key=lambda o: abs(o.trigger_price - previous_price))

        for order in orders_to_trigger:
            if order.order_id not in self.pending_orders:
                continue

            # Remove from pending
            self.pending_orders.pop(order.order_id)

            # Apply slippage (against the entry)
            if order.type == "BUY_STOP":
                fill_price = order.trigger_price * (1 + self.slippage_pct)
                pos_type = "BUY"
            else:
                fill_price = order.trigger_price * (1 - self.slippage_pct)
                pos_type = "SELL"

            # Commission
            trade_value = order.size * fill_price
            entry_commission = trade_value * self.commission_pct
            self.balance -= entry_commission

            # Open position
            pos = Position(pos_type, fill_price, order.size, timestamp)
            self.open_positions[pos.position_id] = pos
            triggered_positions.append(pos)

        return triggered_positions

class BreakoutGridBot:
    def __init__(
        self,
        broker: SimulatedBroker,
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
        bb_squeeze_threshold: float = 0.02
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

        self.deployed = False
        self.deploy_price = 0.0
        self.current_cycle_id = 1
        
        # History of cycles: {cycle_id, start_price, exit_price, pnl, trades_count, start_time, exit_time}
        self.cycle_history = []
        self.cycle_start_time = None

    def deploy_traps(self, current_price: float, timestamp: float, bb_width: float = None):
        """
        Cancel existing traps and place a new grid of traps centered around current_price.
        If use_bb_filter is True, deployment will be skipped if bb_width is missing or > threshold.
        """
        if self.use_bb_filter:
            if bb_width is None or bb_width > self.bb_squeeze_threshold:
                return

        self.broker.cancel_all_orders()
        self.deploy_price = current_price
        self.cycle_start_time = timestamp
        self.max_floating_pnl = -float("inf")

        # Calculate absolute gap and offset
        if self.is_percent:
            offset_val = current_price * (self.trap_offset / 100.0)
            gap_val = current_price * (self.grid_gap / 100.0)
        else:
            offset_val = self.trap_offset
            gap_val = self.grid_gap

        try:
            # Place Buy Stop orders above the current price
            for i in range(self.grid_levels):
                trigger_price = current_price + offset_val + (i * gap_val)
                level_size = self.order_size * (self.order_size_multiplier ** i)
                self.broker.place_order("BUY_STOP", trigger_price, level_size, timestamp)

            # Place Sell Stop orders below the current price
            for i in range(self.grid_levels):
                trigger_price = current_price - offset_val - (i * gap_val)
                level_size = self.order_size * (self.order_size_multiplier ** i)
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

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, bb_width: float = None) -> Optional[dict]:
        """
        Processes a single price tick.
        Evaluates profit targets, stop losses, and cycle timeouts.
        Returns a dictionary summarizing the cycle if an exit condition is met, otherwise None.
        """
        if not self.deployed and self.auto_restart:
            self.deploy_traps(current_price, timestamp, bb_width)

        if not self.deployed:
            return None

        # Let broker process the price tick to trigger any pending orders
        triggered_positions = self.broker.process_tick(previous_price, current_price, timestamp)

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

        # Check exit conditions
        target_hit = False
        trailing_stop_hit = False
        stop_loss_hit = False
        timeout_hit = (timestamp - self.cycle_start_time) >= self.max_cycle_duration

        if len(self.broker.open_positions) > 0:
            # Update max PnL
            if float_pnl > getattr(self, 'max_floating_pnl', -float("inf")):
                self.max_floating_pnl = float_pnl

            if self.use_trailing_stop:
                if self.max_floating_pnl > 0:
                    if float_pnl <= (self.max_floating_pnl - self.trailing_stop_distance):
                        trailing_stop_hit = True
            else:
                if float_pnl >= self.target_profit:
                    target_hit = True
                    
            if float_pnl <= -self.stop_loss:
                stop_loss_hit = True

        if target_hit or trailing_stop_hit or stop_loss_hit or timeout_hit:
            # Determine reason
            if trailing_stop_hit: reason = "TRAILING_STOP"
            elif target_hit: reason = "TARGET_PROFIT"
            elif stop_loss_hit: reason = "STOP_LOSS"
            else: reason = "TIMEOUT"
            
            # Close cycle
            closed_trades = self.broker.close_all_positions(current_price, timestamp)
            self.broker.cancel_all_orders()

            trades_count = len(closed_trades)
            cycle_pnl = sum(t["pnl"] for t in closed_trades)

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
