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

    def ensure_connected(self) -> bool:
        """
        Checks connection to MT5 terminal and tries to reconnect/login if disconnected.
        """
        if not MT5_AVAILABLE:
            return False
            
        try:
            # Check terminal info
            info = mt5.terminal_info()
            if info is not None:
                # Check if logged in and connected
                acc = mt5.account_info()
                if acc is not None:
                    return True
        except Exception:
            pass

        # Try to initialize and login
        if not mt5.initialize():
            return False
            
        authorized = mt5.login(login=self.login, password=self.password, server=self.server)
        return authorized

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
        self.ensure_connected()
        account_info = mt5.account_info()
        return account_info.balance if account_info else 0.0

    def get_equity(self, current_price: float = None) -> float:
        self.ensure_connected()
        account_info = mt5.account_info()
        return account_info.equity if account_info else 0.0

    def get_floating_pnl(self, current_price: float = None) -> float:
        if not self.ensure_connected():
            return 0.0
            
        exness_symbol = self.get_exness_symbol(self.symbol) if self.symbol else None
        positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else mt5.positions_get()
        
        pnl = 0.0
        if positions:
            for pos in positions:
                if pos.magic == self.magic_number:
                    pnl += pos.profit
        return pnl

    def place_order(self, type: str, trigger_price: float, size: float, timestamp: float, symbol: str = None) -> Order:
        """
        Places a pending Buy Stop or Sell Stop order on the MT5 terminal.
        """
        if not self.ensure_connected():
            raise RuntimeError("MT5 connection is offline. Cannot place order.")

        if symbol is None:
            symbol = self.symbol
        exness_symbol = self.get_exness_symbol(symbol)
        
        # Select symbol in Market Watch if not already active
        mt5.symbol_select(exness_symbol, True)
        
        # Map bot order type to MT5 order types
        mt5_order_type = mt5.ORDER_TYPE_BUY_STOP if type == "BUY_STOP" else mt5.ORDER_TYPE_SELL_STOP

        # Round trigger price and order volume/size to match the broker's symbol constraints
        info = mt5.symbol_info(exness_symbol)
        if info is not None:
            # Enforce MT5 Stop Level constraints to prevent Invalid Price rejections
            tick = mt5.symbol_info_tick(exness_symbol)
            if tick is not None:
                bid = tick.bid
                ask = tick.ask
                point = info.point
                # Minimum allowed distance in price points (trade_stops_level)
                # Exness uses dynamic stop levels that are often reported as 0, so we enforce
                # a minimum distance of at least 2.5 times the current spread in points, plus 2 points margin.
                spread_pts = (ask - bid) / point if point > 0 else 0
                stop_level_pts = int(max(info.trade_stops_level, spread_pts * 2.5)) + 2
                stop_level_dist = stop_level_pts * point
                
                if type == "BUY_STOP":
                    min_allowed_price = ask + stop_level_dist
                    if trigger_price < min_allowed_price:
                        trigger_price = min_allowed_price
                        print(f"Adjusted BUY_STOP trigger price to {trigger_price} to satisfy dynamic Stop Level ({stop_level_pts} pts).")
                elif type == "SELL_STOP":
                    max_allowed_price = bid - stop_level_dist
                    if trigger_price > max_allowed_price:
                        trigger_price = max_allowed_price
                        print(f"Adjusted SELL_STOP trigger price to {trigger_price} to satisfy dynamic Stop Level ({stop_level_pts} pts).")

            # 1. Round price to the nearest tick size (e.g. 0.01 or 0.1)
            tick_size = info.trade_tick_size
            if tick_size > 0:
                price_steps = round(trigger_price / tick_size)
                trigger_price = round(price_steps * tick_size, 8)
                
            # 2. Round size/volume to the nearest volume step and clamp within min/max volume limits
            vol_min = info.volume_min
            vol_max = info.volume_max
            vol_step = info.volume_step
            if vol_step > 0:
                size_steps = round(size / vol_step)
                size = round(size_steps * vol_step, 8)
            if size < vol_min:
                size = vol_min
            elif size > vol_max:
                size = vol_max

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
        success_codes = [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]
        
        if result is None or result.retcode not in success_codes:
            err = mt5.last_error() if result is None else result.comment
            print(f"MT5 Order placement failed: {err} (Retcode: {getattr(result, 'retcode', 'N/A')})")
            # Fallback to try ORDER_FILLING_IOC if broker restricts filling mode
            if result and result.retcode in [mt5.TRADE_RETCODE_INVALID_FILL, 10014]:
                request["type_filling"] = mt5.ORDER_FILLING_IOC
                result = mt5.order_send(request)
                
            if result is None or result.retcode not in success_codes:
                raise RuntimeError(f"Failed to place {type} on MT5. Error: {getattr(result, 'comment', err)}")

        # Create local Order representation
        order = Order(type, trigger_price, size, timestamp)
        # Store ticket mapping
        self.ticket_to_order_id[result.order] = order.order_id
        self.pending_orders[order.order_id] = order
        
        # Add a tiny delay to throttle order placement and prevent rate-limiting/anti-spam limits on the broker
        time.sleep(0.05)
        
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """
        Deletes a pending order from MT5.
        """
        if not self.ensure_connected():
            print("MT5 connection is offline. Cannot cancel order.")
            return None

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
        if not self.ensure_connected():
            print("MT5 connection is offline. Cannot cancel all orders.")
            self.pending_orders.clear()
            self.ticket_to_order_id.clear()
            return

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
                    
        # Wait up to 1.5 seconds for the broker to complete order cancellation to avoid duplicates on quick redeploy
        import time
        for _ in range(15):
            orders_still_active = False
            active_orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else mt5.orders_get()
            if active_orders:
                for o in active_orders:
                    if o.magic == self.magic_number:
                        orders_still_active = True
                        break
            if not orders_still_active:
                break
            time.sleep(0.1)

        self.pending_orders.clear()
        self.ticket_to_order_id.clear()

    def close_position(self, position_id: str, exit_price: float, timestamp: float) -> Optional[dict]:
        """
        Closes a specific MT5 position.
        """
        if not self.ensure_connected():
            print("MT5 connection is offline. Cannot close position.")
            return None

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
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None when closing position {ticket}. Last error: {mt5.last_error()}")
            
        success_codes = [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]
        if result.retcode in success_codes:
            # Remove from local track
            self.ticket_to_position_id.pop(ticket, None)
            local_pos = self.open_positions.pop(position_id, None)
            
            pnl = result.profit if result.profit is not None else 0.0
            record = {
                "position_id": position_id,
                "type": local_pos.type if local_pos else ("BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"),
                "entry_price": pos.price_open,
                "exit_price": result.price if result.price > 0 else price,
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
        if not self.ensure_connected():
            raise RuntimeError("MT5 connection is offline. Cannot close open positions.")

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
                    else:
                        raise RuntimeError(f"Failed to close active position {pos.ticket} on Exness MT5!")
                        
        return closed_records

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: str = None) -> List[Position]:
        """
        Synchronizes with the live MT5 account state.
        Detects if any pending orders were filled by the broker.
        """
        if not self.ensure_connected():
            return []

        if symbol is None:
            symbol = self.symbol
        exness_symbol = self.get_exness_symbol(symbol) if symbol else None
        
        # 1. Fetch current pending orders from MT5
        mt5_orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else mt5.orders_get()
        if mt5_orders is None:
            print(f"Failed to fetch pending orders from MT5 (Connection error): {mt5.last_error()}")
            return []
            
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
        if mt5_positions is None:
            print(f"Failed to fetch active positions from MT5 (Connection error): {mt5.last_error()}")
            return []
            
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

        # 5. Clean up any open positions that were closed directly in MT5 by the user or broker
        for ticket, pos_id in list(self.ticket_to_position_id.items()):
            if ticket not in mt5_positions_dict:
                # Position was closed outside the bot
                local_pos = self.open_positions.pop(pos_id, None)
                self.ticket_to_position_id.pop(ticket, None)
                
                # Retrieve actual details from MT5 trade history
                entry_price = local_pos.entry_price if local_pos else 0.0
                exit_price = current_price
                pnl = 0.0
                size = local_pos.size if local_pos else 0.0
                pos_type = local_pos.type if local_pos else "BUY"
                
                history_success = False
                try:
                    # Request deals matching this position ticket
                    deals = mt5.history_deals_get(position=ticket)
                    if deals:
                        deals = sorted(list(deals), key=lambda d: d.time)
                        # First deal is entry, last is exit
                        entry_deal = deals[0]
                        exit_deal = deals[-1]
                        entry_price = entry_deal.price
                        exit_price = exit_deal.price
                        pnl = sum(d.profit + d.commission + d.swap for d in deals) # net profit
                        size = exit_deal.volume
                        pos_type = "BUY" if entry_deal.type == mt5.DEAL_TYPE_BUY else "SELL"
                        history_success = True
                except Exception as e:
                    print(f"Failed to fetch MT5 history deals for closed position {ticket}: {e}")
                
                if not history_success and local_pos:
                    # Fallback approximation
                    pnl = local_pos.get_pnl(current_price)
                
                record = {
                    "position_id": pos_id,
                    "type": pos_type,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "size": size,
                    "pnl": pnl,
                    "entry_time": local_pos.entry_time if local_pos else timestamp - 60,
                    "exit_time": timestamp,
                    "commission": 0.0
                }
                self.closed_trades.append(record)
                self.realized_pnl += pnl
                print(f"Position {ticket} was closed outside the bot. PnL: ${pnl:+.2f}")

        return triggered_positions

    def sync(self):
        """
        Synchronizes local pending_orders and open_positions dictionaries with the MT5 terminal.
        Does not perform trigger evaluations. Useful for refreshing UI tables when bot is paused.
        """
        if not self.ensure_connected():
            return
            
        exness_symbol = self.get_exness_symbol(self.symbol) if self.symbol else None
        
        # 1. Sync pending orders
        mt5_orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else mt5.orders_get()
        if mt5_orders is not None:
            self.pending_orders.clear()
            self.ticket_to_order_id.clear()
            for o in mt5_orders:
                if o.magic == self.magic_number:
                    # Create Order object
                    order_type = "BUY_STOP" if o.type == mt5.ORDER_TYPE_BUY_STOP else "SELL_STOP"
                    local_order = Order(order_type, o.price_open, o.volume_initial, o.time_setup)
                    local_order.order_id = str(o.ticket)
                    self.pending_orders[local_order.order_id] = local_order
                    self.ticket_to_order_id[o.ticket] = local_order.order_id

        # 2. Sync active positions
        mt5_positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else mt5.positions_get()
        if mt5_positions is not None:
            self.open_positions.clear()
            self.ticket_to_position_id.clear()
            for p in mt5_positions:
                if p.magic == self.magic_number:
                    pos_type = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                    local_pos = Position(pos_type, p.price_open, p.volume, p.time)
                    local_pos.position_id = str(p.ticket)
                    self.open_positions[local_pos.position_id] = local_pos
                    self.ticket_to_position_id[p.ticket] = local_pos.position_id

        # 3. Sync recent deals history
        try:
            self.sync_history_from_mt5()
        except Exception as e:
            print(f"Failed to sync history from MT5: {e}")

    def get_all_account_positions(self) -> list:
        """
        Retrieves all active positions on the MT5 account (including manual and external trades)
        for UI display purposes.
        """
        if not self.ensure_connected():
            return []
            
        exness_symbol = self.get_exness_symbol(self.symbol) if self.symbol else None
        positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else mt5.positions_get()
        
        pos_list = []
        if positions:
            for p in positions:
                # Include positions that do NOT belong to this bot (manual/external trades)
                if p.magic != self.magic_number:
                    pos_type = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                    pos_list.append({
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": pos_type,
                        "price": p.price_open,
                        "volume": p.volume,
                        "profit": p.profit,
                        "magic": p.magic
                    })
        return pos_list

    def sync_history_from_mt5(self):
        """
        Queries MT5 historical deals for our magic number and populates
        the closed_trades list and realized_pnl.
        """
        if not self.ensure_connected():
            return

        import MetaTrader5 as mt5_ref
        import time

        # Query deals for the last 7 days to cover recent cycles
        now = time.time()
        from_date = now - 7 * 24 * 3600
        deals = mt5_ref.history_deals_get(from_date, now + 3600)
        
        if not deals:
            return

        # Group deals by position ID
        position_deals = {}
        for d in deals:
            if d.magic == self.magic_number:
                pid = d.position_id
                if pid not in position_deals:
                    position_deals[pid] = []
                position_deals[pid].append(d)

        # Clear and rebuild closed trades
        self.closed_trades.clear()
        self.realized_pnl = 0.0

        for pid, d_list in position_deals.items():
            d_list = sorted(d_list, key=lambda x: x.time)
            
            # Reconstruct closed trades where there are at least two deals (entry & exit)
            if len(d_list) >= 2:
                entry_deal = d_list[0]
                exit_deal = d_list[-1]
                
                # Check exit type indicator to make sure it is closed
                if exit_deal.entry in [mt5_ref.DEAL_ENTRY_OUT, mt5_ref.DEAL_ENTRY_OUT_BY, 1, 3]:
                    pnl = sum(d.profit + d.commission + d.swap for d in d_list)
                    pos_type = "BUY" if entry_deal.type == mt5_ref.DEAL_TYPE_BUY else "SELL"
                    
                    record = {
                        "position_id": f"live_{pid}",
                        "type": pos_type,
                        "entry_price": entry_deal.price,
                        "exit_price": exit_deal.price,
                        "size": exit_deal.volume,
                        "pnl": pnl,
                        "entry_time": entry_deal.time,
                        "exit_time": exit_deal.time,
                        "commission": 0.0
                    }
                    self.closed_trades.append(record)
                    self.realized_pnl += pnl

        # Sort closed trades by exit time descending so newest shows first in UI
        self.closed_trades = sorted(self.closed_trades, key=lambda x: x["exit_time"], reverse=True)
