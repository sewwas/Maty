import time
import os
from typing import Dict, List, Optional
from core.engine import Order, Position

# Try to import MetaTrader 5, default to None if not installed (e.g., in clean development environments)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

class MT5Broker:
    def __init__(self, login: int, password: str, server: str, symbol: str, symbol_suffix: str = "", magic_number: int = 998877):
        """
        Interfaces with MetaTrader 5 for real money trading on Exness.
        """
        if not MT5_AVAILABLE:
            raise ImportError("The 'MetaTrader5' library is not installed. Please run 'pip install MetaTrader5' in your terminal.")

        self.login = int(login)
        self.password = password
        self.server = server
        self.symbol = symbol
        self.symbol_suffix = symbol_suffix
        self.magic_number = magic_number

        self.pending_orders: Dict[str, Order] = {}
        self.open_positions: Dict[str, Position] = {}
        self.closed_trades: List[dict] = []
        self.realized_pnl = 0.0

        # Map to keep track of MT5 tickets vs bot custom IDs
        # mt5_ticket_id (int) -> bot_order_id (str)
        self.ticket_to_order_id = {}
        self.ticket_to_position_id = {}

        # Connect to the MetaTrader 5 terminal
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
            
        # Log into account
        authorized = mt5.login(login=self.login, password=self.password, server=self.server)
        if not authorized:
            raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    def get_exness_symbol(self, ui_symbol: str) -> str:
        """
        Maps UI symbol (e.g., BTCUSDT) to Exness MT5 symbol (e.g., BTCUSDm)
        """
        symbol_map = {
            "BTCUSDT": "BTCUSD",
            "ETHUSDT": "ETHUSD",
            "SOLUSDT": "SOLUSD",
            "BNBUSDT": "BNBUSD",
            "DOGEUSDT": "DOGEUSD",
            "PAXGUSDT": "XAUUSD"
        }
        base_sym = symbol_map.get(ui_symbol, ui_symbol)
        candidate = f"{base_sym}{self.symbol_suffix}"
        
        # If the broker does not support XAUUSD, check if they use "GOLD" instead (e.g. some Exness/other broker setups)
        if ui_symbol == "PAXGUSDT" and MT5_AVAILABLE:
            # Check symbol validity in MT5 terminal
            info = mt5.symbol_info(candidate)
            if info is None:
                fallback_candidate = f"GOLD{self.symbol_suffix}"
                fallback_info = mt5.symbol_info(fallback_candidate)
                if fallback_info is not None:
                    return fallback_candidate
                    
        return candidate

    def reset(self):
        """
        Resets local state but does NOT clear live account balance/equity
        """
        self.pending_orders.clear()
        self.open_positions.clear()
        self.closed_trades.clear()
        self.realized_pnl = 0.0
        self.ticket_to_order_id.clear()
        self.ticket_to_position_id.clear()

    @property
    def balance(self) -> float:
        account_info = mt5.account_info()
        return account_info.balance if account_info else 0.0

    def get_equity(self, current_price: float = None) -> float:
        account_info = mt5.account_info()
        return account_info.equity if account_info else 0.0

    def get_floating_pnl(self, current_price: float = None) -> float:
        account_info = mt5.account_info()
        return account_info.profit if account_info else 0.0

    def place_order(self, type: str, trigger_price: float, size: float, timestamp: float, symbol: str = None) -> Order:
        """
        Places a pending Buy Stop or Sell Stop order on the MT5 terminal.
        """
        if symbol is None:
            symbol = self.symbol
        exness_symbol = self.get_exness_symbol(symbol)
        
        # Select symbol in Market Watch if not already active
        mt5.symbol_select(exness_symbol, True)
        
        # Map bot order type to MT5 order types
        mt5_order_type = mt5.ORDER_TYPE_BUY_STOP if type == "BUY_STOP" else mt5.ORDER_TYPE_SELL_STOP

        # Standard Exness standard accounts usually require ORDER_FILLING_IOC or ORDER_FILLING_RETURN.
        # We try ORDER_FILLING_RETURN (which acts as standard GTC/pending filling on Exness)
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": exness_symbol,
            "volume": float(size),
            "type": mt5_order_type,
            "price": float(trigger_price),
            "deviation": 20,
            "magic": self.magic_number,
            "comment": "Maty Breakout Grid",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error() if result is None else result.comment
            print(f"MT5 Order placement failed: {err} (Retcode: {getattr(result, 'retcode', 'N/A')})")
            # Fallback to try ORDER_FILLING_IOC if broker restricts filling mode
            if result and result.retcode in [mt5.TRADE_RETCODE_INVALID_FILL, 10014]:
                request["type_filling"] = mt5.ORDER_FILLING_IOC
                result = mt5.order_send(request)
                
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"Failed to place {type} on MT5. Error: {getattr(result, 'comment', err)}")

        # Create local Order representation
        order = Order(type, trigger_price, size, timestamp)
        # Store ticket mapping
        self.ticket_to_order_id[result.order] = order.order_id
        self.pending_orders[order.order_id] = order
        
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """
        Deletes a pending order from MT5.
        """
        order = self.pending_orders.get(order_id)
        if not order:
            return None

        # Find the MT5 ticket ID
        ticket = None
        for t, oid in list(self.ticket_to_order_id.items()):
            if oid == order_id:
                ticket = t
                break

        if ticket is not None:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.ticket_to_order_id.pop(ticket, None)
                return self.pending_orders.pop(order_id, None)
            else:
                print(f"Failed to cancel MT5 order {ticket}: {result.comment}")
        return None

    def cancel_all_orders(self, symbol: str = None):
        """
        Cancels all pending orders placed by this bot magic number.
        """
        if symbol is None:
            symbol = self.symbol
        # Get active orders
        exness_symbol = self.get_exness_symbol(symbol) if symbol else None
        orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else mt5.orders_get()
        
        if orders:
            for mt5_order in orders:
                if mt5_order.magic == self.magic_number:
                    request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": mt5_order.ticket
                    }
                    mt5.order_send(request)
                    
        self.pending_orders.clear()
        self.ticket_to_order_id.clear()

    def close_position(self, position_id: str, exit_price: float, timestamp: float) -> Optional[dict]:
        """
        Closes a specific MT5 position.
        """
        # Find the position ticket ID
        ticket = None
        for t, pid in list(self.ticket_to_position_id.items()):
            if pid == position_id:
                ticket = t
                break

        if ticket is None:
            return None

        # Retrieve MT5 position info
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None
        pos = positions[0]

        # Opposite type to close it
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        
        # Get current tick to use correct market price
        tick = mt5.symbol_info_tick(pos.symbol)
        price = tick.ask if close_type == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": pos.ticket,
            "price": price,
            "deviation": 20,
            "magic": self.magic_number,
            "comment": "Maty Close Position",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            # Remove from local track
            self.ticket_to_position_id.pop(ticket, None)
            local_pos = self.open_positions.pop(position_id, None)
            
            pnl = result.profit
            record = {
                "position_id": position_id,
                "type": local_pos.type if local_pos else ("BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"),
                "entry_price": pos.price_open,
                "exit_price": result.price,
                "size": pos.volume,
                "pnl": pnl,
                "entry_time": pos.time,
                "exit_time": timestamp,
                "commission": 0.0
            }
            self.closed_trades.append(record)
            self.realized_pnl += pnl
            return record
        else:
            print(f"Failed to close position {ticket}: {result.comment}")
        return None

    def close_all_positions(self, exit_price: float, timestamp: float, symbol: str = None) -> List[dict]:
        """
        Closes all open positions matching this bot's magic number.
        """
        if symbol is None:
            symbol = self.symbol
        exness_symbol = self.get_exness_symbol(symbol) if symbol else None
        positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else mt5.positions_get()
        closed_records = []

        if positions:
            for pos in positions:
                if pos.magic == self.magic_number:
                    # Find matching local position ID
                    local_pid = self.ticket_to_position_id.get(pos.ticket)
                    if not local_pid:
                        # Auto generate if not tracked locally
                        local_pid = f"live_{pos.ticket}"
                        self.ticket_to_position_id[pos.ticket] = local_pid

                    record = self.close_position(local_pid, exit_price, timestamp)
                    if record:
                        closed_records.append(record)

        self.open_positions.clear()
        self.ticket_to_position_id.clear()
        return closed_records

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: str = None) -> List[Position]:
        """
        Synchronizes with the live MT5 account state.
        Detects if any pending orders were filled by the broker.
        """
        if not MT5_AVAILABLE:
            return []

        if symbol is None:
            symbol = self.symbol
        exness_symbol = self.get_exness_symbol(symbol) if symbol else None
        
        # 1. Fetch current pending orders from MT5
        mt5_orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else mt5.orders_get()
        mt5_order_tickets = set()
        if mt5_orders:
            for o in mt5_orders:
                if o.magic == self.magic_number:
                    mt5_order_tickets.add(o.ticket)

        # 2. Find local pending orders that are NO LONGER present on MT5 (i.e., triggered or deleted)
        removed_orders = []
        for ticket, order_id in list(self.ticket_to_order_id.items()):
            if ticket not in mt5_order_tickets:
                removed_orders.append((ticket, order_id))

        # 3. Fetch active positions from MT5
        mt5_positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else mt5.positions_get()
        mt5_positions_dict = {}
        if mt5_positions:
            for p in mt5_positions:
                if p.magic == self.magic_number:
                    mt5_positions_dict[p.ticket] = p

        # 4. Process the removed pending orders
        triggered_positions = []
        for ticket, order_id in removed_orders:
            local_order = self.pending_orders.pop(order_id, None)
            self.ticket_to_order_id.pop(ticket, None)

            if local_order:
                # If it's now in the active positions, it was triggered/filled
                if ticket in mt5_positions_dict:
                    mt5_pos = mt5_positions_dict[ticket]
                    pos_type = "BUY" if mt5_pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                    
                    # Create Position object
                    new_pos = Position(pos_type, mt5_pos.price_open, mt5_pos.volume, mt5_pos.time)
                    
                    # Store mapping
                    self.ticket_to_position_id[ticket] = new_pos.position_id
                    self.open_positions[new_pos.position_id] = new_pos
                    triggered_positions.append(new_pos)
                else:
                    # The order was cancelled manually or timed out
                    print(f"Pending order {ticket} was cancelled or expired on MT5.")

        # 5. Clean up any open positions that were closed directly in MT5 by the user
        for ticket, pos_id in list(self.ticket_to_position_id.items()):
            if ticket not in mt5_positions_dict:
                # Position was closed outside the bot
                self.open_positions.pop(pos_id, None)
                self.ticket_to_position_id.pop(ticket, None)
                print(f"Position {ticket} was closed directly in MT5.")

        return triggered_positions
