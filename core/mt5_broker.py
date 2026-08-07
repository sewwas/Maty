import time
import os
import sys
from typing import Dict, List, Optional, Any
from core.engine import Order, Position

try:
    import MetaTrader5 as mt5
    if not hasattr(mt5, 'initialize'):
        raise ImportError("MetaTrader5 _core DLL is blocked or failed to initialize.")
    MT5_AVAILABLE = True
except (ImportError, Exception):
    mt5 = None
    MT5_AVAILABLE = False


SYMBOL_MAGIC_NUMBERS = {
    "BTCUSDT": 998871,
    "ETHUSDT": 998872,
    "SOLUSDT": 998873,
    "BNBUSDT": 998874,
    "DOGEUSDT": 998875,
    "PAXGUSDT": 998876
}

class TradeDisabledError(RuntimeError):
    pass


def get_symbol_magic_number(symbol: str) -> int:
    if not symbol:
        return 998877
    sym_upper = symbol.upper()
    if sym_upper in SYMBOL_MAGIC_NUMBERS:
        return SYMBOL_MAGIC_NUMBERS[sym_upper]
    clean_sym = sym_upper.replace("USDT", "").replace("USD", "")
    if clean_sym in ("PAXG", "XAU", "GOLD"):
        return 998876
    char_code_sum = sum(ord(c) * (i + 1) for i, c in enumerate(sym_upper))
    return 998870 + (char_code_sum % 1000)


class MT5Broker:
    """
    Clean, simplified MT5 Broker interface for Exness MetaTrader 5 trading.
    Handles order placement, cancellation, position tracking, and floating PnL.
    """
    def __init__(self, login: int = 279696908, password: str = "", server: str = "Exness-MT5Trial8", symbol: str = "BTCUSDT", symbol_suffix: str = "", magic_number: Optional[int] = None):
        if not MT5_AVAILABLE:
            raise ImportError("MetaTrader5 library is not available.")

        self.login = int(login)
        self.password = str(password)
        self.server = str(server)
        self.symbol = str(symbol)
        self.symbol_suffix = str(symbol_suffix)
        self.magic_number = magic_number if (magic_number is not None and magic_number != 998877) else get_symbol_magic_number(symbol)

        self.pending_orders: Dict[str, Order] = {}
        self.open_positions: Dict[str, Position] = {}
        self.closed_trades: List[dict] = []
        self.realized_pnl = 0.0

        self.ticket_to_order_id: Dict[int, str] = {}
        self.ticket_to_position_id: Dict[int, str] = {}

        try:
            if not mt5.initialize():
                print(f"Notice: MT5 initialize status: {mt5.last_error()}")

            # If terminal is already connected to target account, skip password login call to prevent timeouts
            acc = mt5.account_info()
            if not acc or (self.login > 0 and acc.login != self.login):
                if self.password:
                    mt5.login(login=self.login, password=self.password, server=self.server)
        except Exception as init_err:
            print(f"Notice: MT5 init check: {init_err}")

    def get_exness_symbol(self, ui_symbol: str) -> str:
        if not hasattr(self, "_exness_symbol_cache"):
            self._exness_symbol_cache = {}
        if ui_symbol in self._exness_symbol_cache:
            return self._exness_symbol_cache[ui_symbol]

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

        res = candidate
        if MT5_AVAILABLE:
            mt5.symbol_select(candidate, True)
            if mt5.symbol_info(candidate) is not None:
                res = candidate
            else:
                for suff in ["m", "c", "_i", ".a", ""]:
                    alt = f"{base_sym}{suff}"
                    mt5.symbol_select(alt, True)
                    if mt5.symbol_info(alt) is not None:
                        res = alt
                        break
        self._exness_symbol_cache[ui_symbol] = res
        return res

    def ensure_connected(self) -> bool:
        if not MT5_AVAILABLE:
            return False
        now = time.time()
        if hasattr(self, "_last_conn_ok") and (now - self._last_conn_ok < 3.0):
            return True
        try:
            if mt5.terminal_info() is None:
                mt5.initialize()
            if mt5.account_info() is None:
                if self.password:
                    mt5.login(login=self.login, password=self.password, server=self.server)
            res = mt5.account_info() is not None
            if res:
                self._last_conn_ok = now
            return res
        except Exception:
            return False

    @property
    def is_cent_account(self) -> bool:
        exness_sym = self.get_exness_symbol(self.symbol)
        if exness_sym.endswith("c"):
            return True
        if self.ensure_connected():
            acc = mt5.account_info()
            if acc and hasattr(acc, "currency") and ("USC" in str(acc.currency).upper() or "EUOC" in str(acc.currency).upper()):
                return True
        return False

    @property
    def balance_usd(self) -> float:
        bal = self.balance
        if self.is_cent_account:
            return bal / 100.0
        return bal

    @property
    def balance(self) -> float:
        if self.ensure_connected():
            acc = mt5.account_info()
            if acc:
                return float(acc.equity)
        return 1000.0

    @property
    def _balance(self) -> float:
        return self.balance

    @_balance.setter
    def _balance(self, val: float):
        pass

    def get_equity(self, current_price: float = 0.0) -> float:
        return self.balance

    def get_current_spread(self) -> float:
        exness_symbol = self.get_exness_symbol(self.symbol)
        info = mt5.symbol_info(exness_symbol) if exness_symbol else None
        if info and info.ask and info.bid:
            return abs(info.ask - info.bid)
        return 0.0

    def get_min_stop_distance(self) -> float:
        exness_symbol = self.get_exness_symbol(self.symbol)
        info = mt5.symbol_info(exness_symbol) if exness_symbol else None
        if info:
            point = info.point if hasattr(info, "point") and info.point else 0.0001
            stops_level = getattr(info, "trade_stops_level", 0) or 0
            return max(stops_level * point, point * 50.0)
        return 0.005

    def place_order(self, order_type: str, price: float, size: float, timestamp: float) -> Order:
        if not self.ensure_connected():
            raise RuntimeError("MT5 connection offline.")

        exness_symbol = self.get_exness_symbol(self.symbol)
        symbol_info = mt5.symbol_info(exness_symbol)
        if symbol_info is None:
            raise RuntimeError(f"Symbol {exness_symbol} info not found.")

        # Minimum stop distance calculation
        point = symbol_info.point
        stops_level = getattr(symbol_info, "trade_stops_level", 0) or 0
        min_stop_dist = max(stops_level * point, point * 50.0)

        tick = mt5.symbol_info_tick(exness_symbol)
        ask = tick.ask if tick else price
        bid = tick.bid if tick else price

        if order_type == "BUY_STOP":
            mt5_type = mt5.ORDER_TYPE_BUY_STOP
            min_allowed_price = ask + min_stop_dist
            trigger_price = max(price, min_allowed_price)
        else:
            mt5_type = mt5.ORDER_TYPE_SELL_STOP
            max_allowed_price = bid - min_stop_dist
            trigger_price = min(price, max_allowed_price)

        digits = symbol_info.digits
        trigger_price = round(trigger_price, digits)

        # Volume calculation & alignment with Exness symbol volume limits & steps
        vol_min = symbol_info.volume_min if hasattr(symbol_info, "volume_min") and symbol_info.volume_min else 0.01
        vol_max = symbol_info.volume_max if hasattr(symbol_info, "volume_max") and symbol_info.volume_max else 100.0
        vol_step = symbol_info.volume_step if hasattr(symbol_info, "volume_step") and symbol_info.volume_step else 0.01

        if vol_step > 0:
            steps = max(1, round(size / vol_step))
            order_size = round(steps * vol_step, 4)
        else:
            order_size = round(size, 4)

        order_size = max(vol_min, min(vol_max, order_size))

        # Detect filling mode supported by broker for pending orders (RETURN prevents 9s IOC auto-cancellation by Exness)
        filling_mode = getattr(symbol_info, "filling_mode", 0) or 0
        if (filling_mode & mt5.ORDER_FILLING_RETURN) != 0:
            mt5_filling = mt5.ORDER_FILLING_RETURN
        elif (filling_mode & mt5.ORDER_FILLING_FOK) != 0:
            mt5_filling = mt5.ORDER_FILLING_FOK
        else:
            mt5_filling = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": exness_symbol,
            "volume": order_size,
            "type": mt5_type,
            "price": trigger_price,
            "sl": 0.0,
            "tp": 0.0,
            "magic": self.magic_number,
            "comment": "Maty Bot Trap",
            "type_filling": mt5_filling,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode not in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
            comment = getattr(result, 'comment', 'Placement failed')
            retcode = getattr(result, 'retcode', 'N/A')
            raise RuntimeError(f"MT5 order placement failed ({exness_symbol}): {comment} (Retcode: {retcode})")

        ticket = result.order
        order_id = f"ord_{int(time.time() * 1000)}"
        order = Order(order_type, trigger_price, order_size, timestamp)
        order.order_id = order_id
        order.mt5_ticket = ticket

        self.pending_orders[order_id] = order
        self.ticket_to_order_id[ticket] = order_id
        return order

    def purge_duplicate_mt5_orders(self) -> int:
        """
        Direct MT5 Terminal Duplicate Purge:
        Queries live pending orders directly from MT5 terminal for this bot's magic number or symbol,
        groups orders by price level, and immediately sends TRADE_ACTION_REMOVE to cancel any
        overlapping duplicate tickets at the exact same or close price on MT5 server.
        """
        if not self.ensure_connected():
            return 0

        exness_symbol = self.get_exness_symbol(self.symbol)
        orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else None
        if not orders:
            return 0

        symbol_info = mt5.symbol_info(exness_symbol)
        point = symbol_info.point if symbol_info else 0.0001
        # Exact price match tolerance (3 pips / 3 cents max) to prevent purging valid grid levels
        tolerance = max(point * 3.0, 0.03)

        buy_orders = []
        sell_orders = []
        for o in orders:
            # Purge duplicate tickets on symbol regardless of magic number
            if o.type in [mt5.ORDER_TYPE_BUY_STOP, 4]:
                buy_orders.append(o)
            elif o.type in [mt5.ORDER_TYPE_SELL_STOP, 5]:
                sell_orders.append(o)

        purged_count = 0
        for group in [buy_orders, sell_orders]:
            seen_prices = []
            for o in sorted(group, key=lambda x: x.price_open):
                p = float(o.price_open)
                if any(abs(p - sp) < tolerance for sp in seen_prices):
                    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
                    mt5.order_send(req)
                    purged_count += 1
                    if o.ticket in self.ticket_to_order_id:
                        oid = self.ticket_to_order_id.pop(o.ticket, None)
                        if oid:
                            self.pending_orders.pop(oid, None)
                else:
                    seen_prices.append(p)

        return purged_count

    def cancel_order(self, order_id: str) -> Optional[Order]:
        if not self.ensure_connected():
            return None

        order = self.pending_orders.get(order_id)
        if not order:
            return None

        ticket = getattr(order, 'mt5_ticket', None)
        if not ticket:
            for t, oid in list(self.ticket_to_order_id.items()):
                if oid == order_id:
                    ticket = t
                    break

        if ticket:
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
            mt5.order_send(req)

        self.pending_orders.pop(order_id, None)
        if ticket:
            self.ticket_to_order_id.pop(ticket, None)
        return order

    def cancel_all_orders(self, symbol: Optional[str] = None):
        if not self.ensure_connected():
            return

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)
        orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else None
        if orders:
            for o in orders:
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
                mt5.order_send(req)

        # Synchronous verification: wait up to 250ms for MT5 server to confirm order removals
        for _ in range(5):
            rem = mt5.orders_get(symbol=exness_symbol) if exness_symbol else None
            if not rem:
                break
            time.sleep(0.05)

        self.pending_orders.clear()
        self.ticket_to_order_id.clear()

    def close_position(self, position_id: str, exit_price: float, timestamp: float) -> Optional[dict]:
        if not self.ensure_connected():
            return None

        ticket = None
        for t, pid in list(self.ticket_to_position_id.items()):
            if pid == position_id:
                ticket = t
                break

        if not ticket and position_id.startswith("live_"):
            try:
                ticket = int(position_id.replace("live_", ""))
            except Exception:
                pass

        if not ticket:
            return None

        pos_list = mt5.positions_get(ticket=ticket)
        if not pos_list:
            return None

        pos = pos_list[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        price = (tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask) if tick else exit_price

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "magic": self.magic_number,
            "comment": "Maty Bot Exit",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        res = mt5.order_send(req)
        if res and res.retcode in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
            pnl = getattr(res, 'profit', 0.0) or pos.profit
            record = {
                "position_id": position_id,
                "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
                "entry_price": pos.price_open,
                "exit_price": res.price if res.price > 0 else price,
                "size": pos.volume,
                "pnl": pnl,
                "entry_time": pos.time,
                "exit_time": timestamp,
                "commission": 0.0
            }
            self.closed_trades.append(record)
            self.realized_pnl += pnl
            self.open_positions.pop(position_id, None)
            self.ticket_to_position_id.pop(ticket, None)
            return record
        return None

    def close_all_positions(self, exit_price: float, timestamp: float, symbol: Optional[str] = None) -> List[dict]:
        if not self.ensure_connected():
            return []

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)
        positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else None
        closed = []
        if positions:
            for pos in positions:
                if pos.magic == self.magic_number:
                    pid = self.ticket_to_position_id.get(pos.ticket, f"live_{pos.ticket}")
                    rec = self.close_position(pid, exit_price, timestamp)
                    if rec:
                        closed.append(rec)
        return closed

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: Optional[str] = None) -> List[Position]:
        if not self.ensure_connected():
            return []

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)

        # 1. Active pending orders from MT5
        self.purge_duplicate_mt5_orders()
        mt5_orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else None
        active_order_tickets = set()
        if mt5_orders:
            for o in mt5_orders:
                if o.magic == self.magic_number:
                    active_order_tickets.add(o.ticket)
                    if o.ticket not in self.ticket_to_order_id:
                        order_type = "BUY_STOP" if o.type in [mt5.ORDER_TYPE_BUY_STOP, 4] else "SELL_STOP"
                        loc_ord = Order(order_type, o.price_open, o.volume_initial, o.time_setup)
                        loc_ord.order_id = f"mt5_{o.ticket}"
                        loc_ord.mt5_ticket = o.ticket
                        self.ticket_to_order_id[o.ticket] = loc_ord.order_id
                        self.pending_orders[loc_ord.order_id] = loc_ord

        # Purge local orders ONLY if MT5 query succeeded
        if mt5_orders is not None:
            for ticket, oid in list(self.ticket_to_order_id.items()):
                if ticket not in active_order_tickets:
                    self.pending_orders.pop(oid, None)
                    self.ticket_to_order_id.pop(ticket, None)

        # 2. Active positions from MT5
        mt5_positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else None
        active_pos_tickets = set()
        triggered_positions = []

        if mt5_positions:
            for p in mt5_positions:
                if p.magic == self.magic_number:
                    active_pos_tickets.add(p.ticket)
                    if p.ticket not in self.ticket_to_position_id:
                        pos_type = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                        new_pos = Position(pos_type, p.price_open, p.volume, p.time)
                        new_pos.position_id = f"live_{p.ticket}"
                        self.ticket_to_position_id[p.ticket] = new_pos.position_id
                        self.open_positions[new_pos.position_id] = new_pos
                        triggered_positions.append(new_pos)

        # Purge local positions ONLY if MT5 query succeeded
        if mt5_positions is not None:
            for ticket, pid in list(self.ticket_to_position_id.items()):
                if ticket not in active_pos_tickets:
                    self.open_positions.pop(pid, None)
                    self.ticket_to_position_id.pop(ticket, None)

        return triggered_positions

    def get_floating_pnl(self, current_price: float) -> float:
        if not self.ensure_connected():
            return 0.0
        exness_symbol = self.get_exness_symbol(self.symbol)
        positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else None
        total_pnl = 0.0
        if positions:
            for p in positions:
                if p.magic == self.magic_number:
                    total_pnl += p.profit
        return total_pnl

    def sync_history_from_mt5(self, days: int = 30, force: bool = False):
        """
        Fetches closed deal history directly from MT5 terminal for this bot's magic number,
        synchronizing closed_trades and realized_pnl. Throttled to max once per 30s to prevent VPS lag.
        """
        if not self.ensure_connected():
            return

        now = time.time()
        if not force and hasattr(self, "_last_history_sync_time") and (now - self._last_history_sync_time < 30.0):
            return
        self._last_history_sync_time = now

        try:
            import datetime
            from_date = datetime.datetime.now() - datetime.timedelta(days=days)
            to_date = datetime.datetime.now() + datetime.timedelta(days=1)
            exness_symbol = self.get_exness_symbol(self.symbol)
            deals = mt5.history_deals_get(from_date, to_date, group=f"*{exness_symbol}*") if exness_symbol else mt5.history_deals_get(from_date, to_date)
            if deals:
                synced_trades = []
                synced_pnl = 0.0
                for d in deals:
                    if getattr(d, "magic", 0) == self.magic_number and getattr(d, "entry", 0) in (1, mt5.DEAL_ENTRY_OUT if hasattr(mt5, "DEAL_ENTRY_OUT") else 1):
                        pnl = float(getattr(d, "profit", 0.0)) + float(getattr(d, "swap", 0.0)) + float(getattr(d, "commission", 0.0))
                        t_record = {
                            "position_id": f"deal_{d.ticket}",
                            "type": "BUY" if getattr(d, "type", 0) == 1 else "SELL",
                            "entry_price": float(d.price),
                            "exit_price": float(d.price),
                            "size": float(d.volume),
                            "pnl": pnl,
                            "entry_time": float(d.time),
                            "exit_time": float(d.time),
                            "commission": float(getattr(d, "commission", 0.0))
                        }
                        synced_trades.append(t_record)
                        synced_pnl += pnl
                if synced_trades:
                    self.closed_trades = synced_trades
                    self.realized_pnl = synced_pnl
        except Exception as err:
            print(f"Notice: MT5 deal history sync: {err}")

    def sync(self):
        if not self.ensure_connected():
            return
        self.process_tick(0.0, 0.0, time.time())
        self.sync_history_from_mt5()


class SimulatedBroker:
    """
    Lightweight simulated paper-trading broker for demo mode.
    """
    def __init__(self, initial_balance: float = 1000.0, symbol: str = "BTCUSDT", magic_number: int = 998877):
        self.balance = float(initial_balance)
        self.symbol = symbol
        self.magic_number = magic_number
        self.pending_orders: Dict[str, Order] = {}
        self.open_positions: Dict[str, Position] = {}
        self.closed_trades: List[dict] = []
        self.realized_pnl = 0.0

    def ensure_connected(self) -> bool:
        return True

    @property
    def _balance(self) -> float:
        return self.balance

    @_balance.setter
    def _balance(self, val: float):
        self.balance = float(val)

    def get_equity(self, current_price: float = 0.0) -> float:
        return self.balance + self.get_floating_pnl(current_price)

    def get_exness_symbol(self, ui_symbol: str) -> str:
        return ui_symbol

    def get_current_spread(self) -> float:
        return 0.0

    def place_order(self, order_type: str, price: float, size: float, timestamp: float) -> Order:
        order_id = f"sim_{int(time.time() * 1000)}_{len(self.pending_orders)+1}"
        order = Order(order_type, price, size, timestamp)
        order.order_id = order_id
        self.pending_orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        return self.pending_orders.pop(order_id, None)

    def cancel_all_orders(self, symbol: Optional[str] = None):
        self.pending_orders.clear()

    def close_position(self, position_id: str, exit_price: float, timestamp: float) -> Optional[dict]:
        pos = self.open_positions.pop(position_id, None)
        if not pos:
            return None
        pnl = (exit_price - pos.entry_price) * pos.size if pos.type == "BUY" else (pos.entry_price - exit_price) * pos.size
        record = {
            "position_id": position_id,
            "type": pos.type,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "size": pos.size,
            "pnl": pnl,
            "entry_time": pos.timestamp,
            "exit_time": timestamp,
            "commission": 0.0
        }
        self.closed_trades.append(record)
        self.realized_pnl += pnl
        return record

    def close_all_positions(self, exit_price: float, timestamp: float, symbol: Optional[str] = None) -> List[dict]:
        closed = []
        for pid in list(self.open_positions.keys()):
            rec = self.close_position(pid, exit_price, timestamp)
            if rec:
                closed.append(rec)
        return closed

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: Optional[str] = None) -> List[Position]:
        triggered = []
        for order_id, order in list(self.pending_orders.items()):
            is_trig = False
            if order.type == "BUY_STOP" and current_price >= order.trigger_price:
                is_trig = True
                pos_type = "BUY"
            elif order.type == "SELL_STOP" and current_price <= order.trigger_price:
                is_trig = True
                pos_type = "SELL"

            if is_trig:
                self.pending_orders.pop(order_id, None)
                pos = Position(pos_type, order.trigger_price, order.size, timestamp)
                self.open_positions[pos.position_id] = pos
                triggered.append(pos)
        return triggered

    def get_floating_pnl(self, current_price: float) -> float:
        total = 0.0
        for pos in self.open_positions.values():
            pnl = (current_price - pos.entry_price) * pos.size if pos.type == "BUY" else (pos.entry_price - current_price) * pos.size
            total += pnl
        return total

    def sync(self):
        pass
