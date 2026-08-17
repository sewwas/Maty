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
    def __init__(self, login: Optional[int] = None, password: str = "", server: str = "", symbol: str = "BTCUSDT", symbol_suffix: str = "", magic_number: Optional[int] = None):
        if not MT5_AVAILABLE:
            raise ImportError("MetaTrader5 library is not available.")

        self.login = int(login) if login is not None else 0
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

            # Dynamic real MT5 account binding directly from live logged-in terminal
            acc = mt5.account_info()
            if acc:
                self.login = int(acc.login)
                self.server = str(acc.server)
            elif self.login > 0 and self.password:
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
            "XRPUSDT": "XRPUSD",
            "ADAUSDT": "ADAUSD",
            "DOTUSDT": "DOTUSD",
            "LTCUSDT": "LTCUSD",
            "LINKUSDT": "LINKUSD",
            "PAXGUSDT": "XAUUSD"
        }
        base_sym = symbol_map.get(ui_symbol, ui_symbol)

        res = ui_symbol
        if MT5_AVAILABLE:
            # Probe common Exness symbol variations (e.g. SOLUSDm for Exness Standard, SOLUSD, SOLUSDc)
            probes = []
            if self.symbol_suffix:
                probes.append(f"{base_sym}{self.symbol_suffix}")
            probes.extend([f"{base_sym}m", base_sym, f"{base_sym}c", f"{base_sym}.a", f"{base_sym}_i"])

            for candidate in probes:
                if mt5.symbol_select(candidate, True):
                    info = mt5.symbol_info(candidate)
                    if info is not None:
                        res = candidate
                        break

            if res == ui_symbol:
                # Group search fallback across full broker catalog
                group_symbols = mt5.symbols_get(group=f"*{base_sym}*")
                if group_symbols:
                    matching = [s.name for s in group_symbols if s.name.upper().startswith(base_sym.upper())]
                    if matching:
                        matching.sort(key=lambda name: (len(name), name))
                        selected = matching[0]
                        if mt5.symbol_select(selected, True):
                            res = selected

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
            acc = mt5.account_info()
            if acc is None:
                if self.password:
                    mt5.login(login=self.login, password=self.password, server=self.server)
                acc = mt5.account_info()
            if acc:
                self.login = int(acc.login)
                self.server = str(acc.server)
            res = acc is not None
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
        now = time.time()
        if hasattr(self, "_acc_info_cache"):
            acc, ts = self._acc_info_cache
            if now - ts < 1.0 and acc:
                return float(acc.equity)
        if self.ensure_connected():
            acc = mt5.account_info()
            self._acc_info_cache = (acc, now)
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

    def get_cached_symbol_info(self, exness_symbol: str):
        now = time.time()
        if not hasattr(self, "_symbol_info_cache"):
            self._symbol_info_cache = {}
        if exness_symbol in self._symbol_info_cache:
            info, ts = self._symbol_info_cache[exness_symbol]
            if now - ts < 2.0 and info is not None:
                return info
        if MT5_AVAILABLE and exness_symbol:
            mt5.symbol_select(exness_symbol, True)
            info = mt5.symbol_info(exness_symbol)
        else:
            info = None
        if info:
            self._symbol_info_cache[exness_symbol] = (info, now)
        return info

    def get_current_spread(self) -> float:
        exness_symbol = self.get_exness_symbol(self.symbol)
        info = self.get_cached_symbol_info(exness_symbol) if exness_symbol else None
        if info and info.ask and info.bid:
            return abs(info.ask - info.bid)
        return 0.0

    def get_total_account_orders_count(self) -> int:
        """Returns total active pending orders + open positions across ALL symbols on MT5 account."""
        if not self.ensure_connected():
            return len(self.pending_orders) + len(self.open_positions)
        try:
            orders = mt5.orders_get()
            positions = mt5.positions_get()
            n_orders = len(orders) if orders else 0
            n_positions = len(positions) if positions else 0
            return n_orders + n_positions
        except Exception:
            return len(self.pending_orders) + len(self.open_positions)

    def get_min_stop_distance(self) -> float:
        exness_symbol = self.get_exness_symbol(self.symbol)
        info = self.get_cached_symbol_info(exness_symbol) if exness_symbol else None
        if info:
            point = info.point if hasattr(info, "point") and info.point else 0.0001
            stops_level = getattr(info, "trade_stops_level", 0) or 0
            min_dist = max(stops_level * point, point * 50.0)
            if "XAU" in exness_symbol.upper() or "GOLD" in exness_symbol.upper():
                return max(2.50, min_dist)
            return min_dist
        return 2.50 if "XAU" in self.symbol.upper() or "GOLD" in self.symbol.upper() else 0.005

    def place_order(self, order_type: str, price: float, size: float, timestamp: float, tp: float = 0.0, sl: float = 0.0) -> Order:
        if not self.ensure_connected():
            raise RuntimeError("MT5 connection offline.")

        exness_symbol = self.get_exness_symbol(self.symbol)
        symbol_info = self.get_cached_symbol_info(exness_symbol)
        if symbol_info is None:
            raise RuntimeError(f"Symbol {exness_symbol} info not found.")

        if getattr(symbol_info, "trade_mode", 4) == 0:
            raise TradeDisabledError(f"Exness server has disabled trading for {exness_symbol} on this account.")

        # Minimum stop distance calculation
        point = symbol_info.point
        stops_level = getattr(symbol_info, "trade_stops_level", 0) or 0
        min_stop_dist = max(stops_level * point, point * 50.0)

        tick = mt5.symbol_info_tick(exness_symbol)
        ask = tick.ask if tick else price
        bid = tick.bid if tick else price

        if order_type == "BUY_STOP":
            mt5_type = mt5.ORDER_TYPE_BUY_STOP
            trigger_price = max(price, ask + min_stop_dist)
        elif order_type == "SELL_STOP":
            mt5_type = mt5.ORDER_TYPE_SELL_STOP
            trigger_price = min(price, bid - min_stop_dist)
        elif order_type == "BUY_LIMIT":
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT
            trigger_price = min(price, ask - min_stop_dist)
        elif order_type == "SELL_LIMIT":
            mt5_type = mt5.ORDER_TYPE_SELL_LIMIT
            trigger_price = max(price, bid + min_stop_dist)
        else:
            mt5_type = mt5.ORDER_TYPE_BUY_STOP
            trigger_price = max(price, ask + min_stop_dist)

        digits = symbol_info.digits
        trigger_price = round(trigger_price, digits)

        # Layer 1 Unbreakable Pre-Placement Duplicate Shield (Strict Level Cap Enforcement)
        for p_ord in list(self.pending_orders.values()):
            ord_t = getattr(p_ord, "timestamp", getattr(p_ord, "time", 0.0))
            if getattr(p_ord, "type", "") == order_type and (timestamp - ord_t) < 15.0:
                return p_ord

        round_dp = 2 if any(x in str(exness_symbol).upper() for x in ["BTC", "XAU", "GOLD", "PAXG", "ETH"]) else 4
        existing_orders = mt5.orders_get(symbol=exness_symbol) if MT5_AVAILABLE else ()
        if existing_orders:
            # Prevent placing duplicate orders at the EXACT SAME price level while allowing multi-level grids
            for ext_o in existing_orders:
                if ext_o.type == mt5_type and round(ext_o.price_open, round_dp) == round(trigger_price, round_dp):
                    loc_ord = Order(order_type, ext_o.price_open, getattr(ext_o, "volume_initial", size), getattr(ext_o, "time_setup", timestamp))
                    loc_ord.order_id = f"mt5_{ext_o.ticket}"
                    loc_ord.mt5_ticket = ext_o.ticket
                    self.ticket_to_order_id[ext_o.ticket] = loc_ord.order_id
                    self.pending_orders[loc_ord.order_id] = loc_ord
                    return loc_ord

        # Volume alignment
        vol_min = getattr(symbol_info, "volume_min", 0.01) or 0.01
        vol_max = getattr(symbol_info, "volume_max", 100.0) or 100.0
        vol_step = getattr(symbol_info, "volume_step", 0.01) or 0.01
        order_size = max(vol_min, min(vol_max, round(round(size / vol_step) * vol_step, 4) if vol_step > 0 else round(size, 4)))

        # Hardware TP & SL Clamping & Default Generation (Guarantees visible TP/SL on MT5 terminal with realistic noise buffer)
        sym_name = str(exness_symbol).upper()
        if "BTC" in sym_name:
            min_sl_dist = 650.0   # Wide Noise-Immune SL Buffer for BTC
            min_tp_dist = 950.0
        elif any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]):
            min_sl_dist = 20.0    # Wide Noise-Immune SL Buffer for Gold
            min_tp_dist = 35.0
        elif "ETH" in sym_name:
            min_sl_dist = 45.0    # Wide Noise-Immune SL Buffer for ETH
            min_tp_dist = 75.0
        elif any(x in sym_name for x in ["EUR", "GBP"]):
            min_sl_dist = 0.0120  # Wide Noise-Immune Buffer for Forex
            min_tp_dist = 0.0200
        else:
            min_sl_dist = max(min_stop_dist * 5.0, point * 500.0)
            min_tp_dist = max(min_stop_dist * 5.0, point * 500.0)

        if "BUY" in order_type:
            tp_val = round(max(tp, trigger_price + min_tp_dist), digits) if tp > 0 else round(trigger_price + min_tp_dist, digits)
            sl_val = round(min(sl, trigger_price - min_sl_dist), digits) if sl > 0 else round(trigger_price - min_sl_dist, digits)
        else:
            tp_val = round(min(tp, trigger_price - min_tp_dist), digits) if tp > 0 else round(trigger_price - min_tp_dist, digits)
            sl_val = round(max(sl, trigger_price + min_sl_dist), digits) if sl > 0 else round(trigger_price + min_sl_dist, digits)

        # Dynamic Exness filling mode detection
        filling_flags = getattr(symbol_info, "filling_mode", 0) or 0
        if filling_flags & 4:
            best_filling = mt5.ORDER_FILLING_RETURN
        elif filling_flags & 1:
            best_filling = mt5.ORDER_FILLING_FOK
        elif filling_flags & 2:
            best_filling = mt5.ORDER_FILLING_IOC
        else:
            best_filling = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": exness_symbol,
            "volume": order_size,
            "type": mt5_type,
            "price": trigger_price,
            "sl": sl_val,
            "tp": tp_val,
            "magic": self.magic_number,
            "comment": "Maty Bot Trap",
            "type_filling": best_filling,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        result = mt5.order_send(request)

        # Fallback Tier 1: Try alternative filling modes (FOK / IOC / RETURN) if rejected
        if result is None or getattr(result, "retcode", 0) not in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
            for alt_fill in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                if alt_fill != best_filling:
                    request["type_filling"] = alt_fill
                    result = mt5.order_send(request)
                    if result is not None and getattr(result, "retcode", 0) in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
                        break

        # Fallback Tier 2: If Limit order failed on Exness account, convert to Stop breakout trap with valid TP/SL
        if result is None or getattr(result, "retcode", 0) not in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
            if "BUY" in order_type:
                request["type"] = mt5.ORDER_TYPE_BUY_STOP
                request["price"] = max(price, ask + min_stop_dist)
                request["tp"] = round(request["price"] + min_tp_dist, digits) if tp > 0 else 0.0
                request["sl"] = round(request["price"] - min_sl_dist, digits) if sl > 0 else 0.0
            else:
                request["type"] = mt5.ORDER_TYPE_SELL_STOP
                request["price"] = min(price, bid - min_stop_dist)
                request["tp"] = round(request["price"] - min_tp_dist, digits) if tp > 0 else 0.0
                request["sl"] = round(request["price"] + min_sl_dist, digits) if sl > 0 else 0.0
            result = mt5.order_send(request)

        # Fallback Tier 3: Try alternative filling modes (FOK / IOC)
        if result is None or getattr(result, "retcode", 0) not in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
            for fill_mode in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]:
                request["type_filling"] = fill_mode
                result = mt5.order_send(request)
                if result is not None and getattr(result, "retcode", 0) in [mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED]:
                    break

        is_placed = result is not None and (getattr(result, "retcode", -1) in (0, 10009, 10008, 10004) or getattr(result, "comment", "") == "ok")
        if not is_placed:
            comment = getattr(result, 'comment', 'Placement failed')
            retcode = getattr(result, 'retcode', 'N/A')
            raise RuntimeError(f"MT5 order placement failed ({exness_symbol}): {comment} (Retcode: {retcode})")

        ticket = result.order
        order_id = f"ord_{int(time.time() * 1000)}"
        order = Order(order_type, trigger_price, order_size, timestamp)
        order.order_id = str(ticket) if ticket else order_id
        order.broker_ticket = ticket
        self.pending_orders[order.order_id] = order
        return order

        self.pending_orders[order_id] = order
        self.ticket_to_order_id[ticket] = order_id
        return order

    def purge_duplicate_mt5_orders(self) -> int:
        """
        Scans MT5 server for pending orders across all symbol aliases.
        Strictly enforces max 1 BUY order and 1 SELL order (max 2 total pending orders per symbol).
        Cancels all extra/duplicate pending orders on MT5 immediately.
        """
        if not self.ensure_connected():
            return 0
        exness_symbol = self.get_exness_symbol(self.symbol)

        orders = []
        for s_alias in set([exness_symbol, self.symbol, f"{exness_symbol}m", f"{exness_symbol}c", "XAUUSD", "XAUUSDm"]):
            if s_alias and MT5_AVAILABLE:
                ords = mt5.orders_get(symbol=s_alias)
                if ords:
                    orders.extend(list(ords))

        if not orders and MT5_AVAILABLE:
            all_o = mt5.orders_get()
            if all_o:
                clean_target = "XAU" if any(x in self.symbol.upper() for x in ["XAU", "GOLD", "PAXG"]) else self.symbol.replace("USDT", "").replace("USD", "")
                orders = [o for o in all_o if clean_target in str(o.symbol).upper()]

        if not orders:
            return 0

        unique_orders_dict = {o.ticket: o for o in orders}
        unique_orders = list(unique_orders_dict.values())

        by_side = {"BUY": [], "SELL": []}
        for o in unique_orders:
            if hasattr(self, "magic_number") and self.magic_number and getattr(o, "magic", 0) != self.magic_number:
                continue
            is_buy = o.type in [mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_LIMIT, 2, 4]
            side_key = "BUY" if is_buy else "SELL"
            by_side[side_key].append(o)

        purged = 0
        for side_key, side_orders in by_side.items():
            if len(side_orders) > 1:
                side_orders.sort(key=lambda x: getattr(x, "time_setup", 0), reverse=True)
                for extra_o in side_orders[1:]:
                    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(extra_o.ticket)}
                    res = mt5.order_send(req)
                    if res and res.retcode in (0, 10009, 10008, 10004):
                        purged += 1
                        self.pending_orders.pop(f"mt5_{extra_o.ticket}", None)
                        self.ticket_to_order_id.pop(extra_o.ticket, None)
        return purged

    def purge_duplicate_mt5_positions(self) -> int:
        """
        Permanently disabled to prevent unauthorized position closing.
        """
        return 0

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
        if hasattr(self, "_in_flight_orders") and isinstance(self._in_flight_orders, set):
            self._in_flight_orders.clear()
            
        if not self.ensure_connected():
            return

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)
        orders_sym = mt5.orders_get(symbol=exness_symbol) if exness_symbol else ()

        all_tks = set()
        if orders_sym:
            for o in orders_sym:
                if hasattr(self, "magic_number") and self.magic_number:
                    if getattr(o, "magic", 0) == self.magic_number:
                        all_tks.add(o.ticket)
                else:
                    all_tks.add(o.ticket)

        for t in all_tks:
            req = {"action": mt5.TRADE_ACTION_REMOVE, "order": t, "symbol": exness_symbol}
            mt5.order_send(req)

        # Synchronous verification: wait up to 250ms for MT5 server to confirm order removals
        for _ in range(5):
            rem = mt5.orders_get(symbol=exness_symbol) if exness_symbol else None
            if rem and hasattr(self, "magic_number") and self.magic_number:
                rem = [o for o in rem if getattr(o, "magic", 0) == self.magic_number]
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
            if str(pid) == str(position_id):
                ticket = t
                break

        if not ticket:
            clean_pid = str(position_id).replace("live_", "").replace("pos_", "").replace("ord_", "")
            if clean_pid.isdigit():
                try:
                    ticket = int(clean_pid)
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

        symbol_info = self.get_cached_symbol_info(pos.symbol)
        filling_mode = getattr(symbol_info, "filling_mode", 0) or 0
        mt5_filling = mt5.ORDER_FILLING_IOC
        if (filling_mode & mt5.ORDER_FILLING_FOK) != 0:
            mt5_filling = mt5.ORDER_FILLING_FOK
        elif (filling_mode & mt5.ORDER_FILLING_RETURN) != 0:
            mt5_filling = mt5.ORDER_FILLING_RETURN

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "magic": getattr(pos, "magic", self.magic_number),
            "comment": "Maty Bot Exit",
            "type_filling": mt5_filling,
        }

        res = mt5.order_send(req)
        is_ok = res is not None and (res.retcode in (0, 10009, 10008, 10004) or getattr(res, "deal", 0) > 0 or getattr(res, "comment", "") == "ok")
        if not is_ok:
            # Fallback retry with RETURN filling mode for zero-latency execution
            req["type_filling"] = mt5.ORDER_FILLING_RETURN
            res = mt5.order_send(req)
            is_ok = res is not None and (res.retcode in (0, 10009, 10008, 10004) or getattr(res, "deal", 0) > 0 or getattr(res, "comment", "") == "ok")

        if is_ok:
            act_exit = getattr(res, "price", 0.0) or price
            pnl = float(getattr(pos, 'profit', 0.0))

            st_sec = float(pos.time / 1000.0) if pos.time > 1e11 else float(pos.time)
            ex_sec = float(timestamp / 1000.0) if timestamp > 1e11 else float(timestamp)
            record = {
                "position_id": position_id,
                "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
                "entry_price": pos.price_open,
                "exit_price": act_exit,
                "size": pos.volume,
                "pnl": pnl,
                "entry_time": st_sec,
                "exit_time": ex_sec,
                "commission": 0.0
            }
            try:
                self.closed_trades.append(record)
                if len(self.closed_trades) > 500:
                    self.closed_trades = self.closed_trades[-500:]
                self.realized_pnl += pnl
                self.open_positions.pop(position_id, None)
                self.ticket_to_position_id.pop(ticket, None)
            except Exception:
                pass
            return record
        return None

    def modify_position_sl_tp(self, position_id: str, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
        """
        Sends TRADE_ACTION_SLTP or TRADE_ACTION_MODIFY request to MT5 server to update hardware 
        Stop Loss (SL) and Take Profit (TP) directly on live MT5 positions or pending orders.
        Guarantees that existing non-zero SL and TP levels are preserved when updating single targets.
        """
        if not self.ensure_connected():
            return False

        clean_pid = str(position_id).replace("live_", "").replace("pos_", "").replace("ord_", "").replace("mt5_", "")
        ticket = None
        for t, pid in list(self.ticket_to_position_id.items()):
            if pid == position_id or str(t) == clean_pid:
                ticket = int(t)
                break

        if not ticket and clean_pid.isdigit():
            ticket = int(clean_pid)

        # 1. Try to find open position
        pos = None
        if ticket:
            pos_list = mt5.positions_get(ticket=ticket)
            if pos_list:
                pos = pos_list[0]

        if not pos:
            pos_list = mt5.positions_get() if MT5_AVAILABLE else ()
            if pos_list:
                for p in pos_list:
                    if getattr(p, "ticket", None) == ticket or str(getattr(p, "ticket", "")) == clean_pid:
                        pos = p
                        ticket = int(p.ticket)
                        break

        # 2. Handle Open Position SL/TP Modification (TRADE_ACTION_SLTP)
        if pos and ticket:
            symbol_info = self.get_cached_symbol_info(pos.symbol)
            digits = symbol_info.digits if symbol_info else 4
            point = symbol_info.point if symbol_info else 0.0001
            stops_lvl = getattr(symbol_info, "trade_stops_level", 0) or 0
            min_stop_dist = max(stops_lvl * point, point * 50.0, 0.10 if any(x in str(pos.symbol).upper() for x in ["XAU", "GOLD"]) else 0.0001)

            tick_info = mt5.symbol_info_tick(pos.symbol)
            bid_px = getattr(tick_info, "bid", 0.0) or getattr(pos, "price_current", 0.0)
            ask_px = getattr(tick_info, "ask", 0.0) or getattr(pos, "price_current", 0.0)

            cur_p_sl = float(getattr(pos, "sl", 0.0) or 0.0)
            cur_p_tp = float(getattr(pos, "tp", 0.0) or 0.0)

            # Preserve existing SL level if sl is not provided or <= 0
            if sl is None:
                final_sl = cur_p_sl
            elif sl > 0:
                final_sl = round(sl, digits)
            else:
                final_sl = cur_p_sl if cur_p_sl > 0 else 0.0

            # Preserve existing TP level if tp is not provided or <= 0, or compute default TP if missing
            if tp is None:
                final_tp = cur_p_tp
            elif tp > 0:
                final_tp = round(tp, digits)
            else:
                if cur_p_tp > 0:
                    final_tp = cur_p_tp
                else:
                    lot_v = float(getattr(pos, "volume", 0.01) or 0.01)
                    c_mult = 100.0 if any(x in str(pos.symbol).upper() for x in ["XAU", "GOLD"]) else 1.0
                    tp_dist = max(min_stop_dist * 2.0, 2.0 / max(0.001, lot_v * c_mult))
                    if pos.type == mt5.POSITION_TYPE_BUY:
                        final_tp = round(pos.price_open + tp_dist, digits)
                    else:
                        final_tp = round(pos.price_open - tp_dist, digits)

            # Exness Stops Level Clamping: ensure SL & TP satisfy broker minimum distance from live price
            if pos.type == mt5.POSITION_TYPE_BUY:
                if final_tp > 0 and ask_px > 0:
                    final_tp = max(final_tp, round(ask_px + min_stop_dist, digits))
                if final_sl > 0 and bid_px > 0:
                    final_sl = min(final_sl, round(bid_px - min_stop_dist, digits))
            else:
                if final_tp > 0 and bid_px > 0:
                    final_tp = min(final_tp, round(bid_px - min_stop_dist, digits))
                if final_sl > 0 and ask_px > 0:
                    final_sl = max(final_sl, round(ask_px + min_stop_dist, digits))

            req = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": int(ticket),
                "sl": float(final_sl),
                "tp": float(final_tp),
            }

            res = mt5.order_send(req)
            is_ok = res is not None and (getattr(res, "retcode", -1) in (0, 10009, 10008, 10004) or getattr(res, "comment", "") == "ok")
            if not is_ok:
                req["magic"] = int(getattr(pos, "magic", self.magic_number) or self.magic_number)
                res = mt5.order_send(req)
                is_ok = res is not None and (getattr(res, "retcode", -1) in (0, 10009, 10008, 10004) or getattr(res, "comment", "") == "ok")

            if is_ok:
                # Update local position tracking
                pid_key = self.ticket_to_position_id.get(ticket, f"live_{ticket}")
                pos_obj = self.open_positions.get(pid_key)
                if pos_obj:
                    pos_obj.sl = final_sl
                    pos_obj.tp = final_tp
            return is_ok

        # 3. Fallback: Pending Order Modification (TRADE_ACTION_MODIFY)
        if ticket:
            ord_list = mt5.orders_get(ticket=ticket) if MT5_AVAILABLE else ()
            if ord_list:
                ord_item = ord_list[0]
                symbol_info = self.get_cached_symbol_info(ord_item.symbol)
                digits = symbol_info.digits if symbol_info else 4
                cur_ord_sl = float(getattr(ord_item, "sl", 0.0) or 0.0)
                cur_ord_tp = float(getattr(ord_item, "tp", 0.0) or 0.0)

                final_sl = round(sl, digits) if (sl is not None and sl > 0) else cur_ord_sl
                final_tp = round(tp, digits) if (tp is not None and tp > 0) else cur_ord_tp

                req = {
                    "action": mt5.TRADE_ACTION_MODIFY,
                    "order": int(ticket),
                    "price": float(ord_item.price_open),
                    "sl": float(final_sl),
                    "tp": float(final_tp),
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                res = mt5.order_send(req)
                return res is not None and (getattr(res, "retcode", -1) in (0, 10009, 10008, 10004) or getattr(res, "comment", "") == "ok")

        return False

    def modify_order(self, order_id: str, price: Optional[float] = None, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
        """Alias method for modify_position_sl_tp to ensure 100% API compatibility."""
        return self.modify_position_sl_tp(order_id, sl=sl, tp=tp)

    def close_all_positions(self, exit_price: float = 0.0, timestamp: float = 0.0, symbol: Optional[str] = None, side: Optional[str] = None) -> List[dict]:
        """
        Closes positions on MT5 server with 3-tier filling mode fallbacks.
        side: None (closes ALL), 'BUY' (closes BUY positions only), 'SELL' (closes SELL positions only).
        """
        if not self.ensure_connected():
            return []

        if symbol:
            exness_symbol = self.get_exness_symbol(symbol)
            positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else None
        else:
            positions = mt5.positions_get() if MT5_AVAILABLE else None

        closed = []
        if positions:
            for pos in list(positions):
                try:
                    pos_side = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                    if side and str(side).upper() != pos_side:
                        continue

                    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    tick = mt5.symbol_info_tick(pos.symbol)
                    price = (tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask) if tick else getattr(pos, "price_current", exit_price)
                    
                    symbol_info = self.get_cached_symbol_info(pos.symbol)
                    filling_mode = getattr(symbol_info, "filling_mode", 0) or 0
                    
                    best_filling = mt5.ORDER_FILLING_IOC
                    if (filling_mode & mt5.ORDER_FILLING_FOK) != 0:
                        best_filling = mt5.ORDER_FILLING_FOK
                    elif (filling_mode & mt5.ORDER_FILLING_RETURN) != 0:
                        best_filling = mt5.ORDER_FILLING_RETURN

                    req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": pos.symbol,
                        "volume": pos.volume,
                        "type": close_type,
                        "position": int(pos.ticket),
                        "price": price,
                        "magic": getattr(pos, "magic", self.magic_number),
                        "comment": f"Maty Close {pos_side}",
                        "type_filling": best_filling,
                    }

                    res = mt5.order_send(req)
                    if res is None or getattr(res, "retcode", -1) not in (0, 10009, 10008, 10004):
                        for alt_fill in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                            req["type_filling"] = alt_fill
                            res = mt5.order_send(req)
                            if res is not None and getattr(res, "retcode", -1) in (0, 10009, 10008, 10004):
                                break

                    is_ok = res is not None and (getattr(res, "retcode", -1) in (0, 10009, 10008, 10004) or getattr(res, "deal", 0) > 0 or getattr(res, "comment", "") == "ok")
                    if is_ok:
                        closed.append({"position_id": f"live_{pos.ticket}", "pnl": float(getattr(pos, "profit", 0.0)), "side": pos_side})
                        self.open_positions.pop(f"live_{pos.ticket}", None)
                        self.open_positions.pop(str(pos.ticket), None)
                        self.ticket_to_position_id.pop(pos.ticket, None)
                except Exception:
                    pass
        return closed

    def close_buy_positions(self, symbol: Optional[str] = None) -> List[dict]:
        """Closes ONLY BUY positions on MT5 server."""
        return self.close_all_positions(symbol=symbol, side="BUY")

    def close_sell_positions(self, symbol: Optional[str] = None) -> List[dict]:
        """Closes ONLY SELL positions on MT5 server."""
        return self.close_all_positions(symbol=symbol, side="SELL")

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: Optional[str] = None) -> List[Position]:
        if not self.ensure_connected():
            return []

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)

        # 1. Active pending orders & duplicate open position purge from MT5
        self.purge_duplicate_mt5_orders()
        self.purge_duplicate_mt5_positions()
        mt5_orders = mt5.orders_get(symbol=exness_symbol) if exness_symbol else None
        active_order_tickets = set()
        if mt5_orders:
            for o in mt5_orders:
                if o.magic == self.magic_number or getattr(self, "magic_number", None) is None:
                    active_order_tickets.add(o.ticket)
                    # Auto-attach hardware SL/TP to existing live MT5 pending orders if missing (sl == 0.0 or tp == 0.0)
                    cur_o_sl = float(getattr(o, "sl", 0.0) or 0.0)
                    cur_o_tp = float(getattr(o, "tp", 0.0) or 0.0)
                    if cur_o_sl == 0.0 or cur_o_tp == 0.0:
                        symbol_info = self.get_cached_symbol_info(o.symbol)
                        digits = symbol_info.digits if symbol_info else 2
                        point = symbol_info.point if symbol_info else 0.01
                        stops_lvl = getattr(symbol_info, "trade_stops_level", 0) or 0
                        sym_u = str(o.symbol).upper()
                        if "BTC" in sym_u:
                            sl_dist = 250.0
                            tp_dist = 450.0
                        elif "ETH" in sym_u:
                            sl_dist = 20.0
                            tp_dist = 40.0
                        elif any(x in sym_u for x in ["XAU", "GOLD"]):
                            sl_dist = 6.0
                            tp_dist = 12.0
                        elif any(x in sym_u for x in ["EUR", "GBP"]):
                            sl_dist = 0.0035
                            tp_dist = 0.0070
                        else:
                            sl_dist = max(stops_lvl * point, point * 500.0, 1.0)
                            tp_dist = max(stops_lvl * point, point * 500.0, 1.0)

                        is_buy = o.type in [mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_LIMIT, 2, 4]
                        px = float(o.price_open)
                        calc_tp = round(px + tp_dist if is_buy else px - tp_dist, digits)
                        calc_sl = round(px - sl_dist if is_buy else px + sl_dist, digits)
                        t_tp = cur_o_tp if cur_o_tp > 0 else calc_tp
                        t_sl = cur_o_sl if cur_o_sl > 0 else calc_sl
                        try:
                            self.modify_position_sl_tp(str(o.ticket), t_sl, t_tp)
                        except Exception:
                            pass

                    if o.ticket not in self.ticket_to_order_id:
                        order_type = "BUY_STOP" if o.type in [mt5.ORDER_TYPE_BUY_STOP, 4] else ("BUY_LIMIT" if o.type in [mt5.ORDER_TYPE_BUY_LIMIT, 2] else ("SELL_LIMIT" if o.type in [mt5.ORDER_TYPE_SELL_LIMIT, 3] else "SELL_STOP"))
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

        # 2. Active positions from MT5 across ALL symbols
        mt5_positions = mt5.positions_get() if MT5_AVAILABLE else None
        active_pos_tickets = set()
        triggered_positions = []

        if mt5_positions:
            for p in mt5_positions:
                sym_upper = str(p.symbol).upper()
                active_pos_tickets.add(p.ticket)
                pid = self.ticket_to_position_id.get(p.ticket)

                symbol_info = self.get_cached_symbol_info(p.symbol)
                digits = symbol_info.digits if symbol_info else (4 if any(x in sym_upper for x in ["DOGE", "GBP", "EUR"]) else 2)
                point = symbol_info.point if symbol_info else (0.01 if "BTC" in sym_upper else 0.0001)
                stops_lvl = getattr(symbol_info, "trade_stops_level", 0) or 0
                if "BTC" in sym_upper:
                    sl_dist_floor = 250.0
                    tp_dist_floor = 450.0
                elif any(x in sym_upper for x in ["XAU", "GOLD"]):
                    sl_dist_floor = 6.0
                    tp_dist_floor = 12.0
                elif "ETH" in sym_upper:
                    sl_dist_floor = 20.0
                    tp_dist_floor = 40.0
                elif any(x in sym_upper for x in ["EUR", "GBP"]):
                    sl_dist_floor = 0.0035
                    tp_dist_floor = 0.0070
                else:
                    sl_dist_floor = max(stops_lvl * point, point * 500.0, 1.0)
                    tp_dist_floor = max(stops_lvl * point, point * 500.0, 1.0)

                # Auto-attach SL/TP to live MT5 position if missing (sl == 0.0 or tp == 0.0)
                cur_p_sl = float(getattr(p, "sl", 0.0) or 0.0)
                cur_p_tp = float(getattr(p, "tp", 0.0) or 0.0)

                if cur_p_sl == 0.0 or cur_p_tp == 0.0:
                    is_buy = (p.type == mt5.POSITION_TYPE_BUY)
                    p_open = float(p.price_open)
                    calc_tp = round(p_open + tp_dist_floor if is_buy else p_open - tp_dist_floor, digits)
                    calc_sl = round(p_open - sl_dist_floor if is_buy else p_open + sl_dist_floor, digits)
                    target_tp = cur_p_tp if cur_p_tp > 0 else calc_tp
                    target_sl = cur_p_sl if cur_p_sl > 0 else calc_sl
                    try:
                        self.modify_position_sl_tp(str(p.ticket), target_sl, target_tp)
                        cur_p_sl = target_sl
                        cur_p_tp = target_tp
                    except Exception:
                        pass

                if not pid:
                    pos_type = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
                    new_pos = Position(pos_type, p.price_open, p.volume, p.time)
                    new_pos.position_id = f"live_{p.ticket}"
                    new_pos.sl = cur_p_sl
                    new_pos.tp = cur_p_tp
                    self.ticket_to_position_id[p.ticket] = new_pos.position_id
                    self.open_positions[new_pos.position_id] = new_pos
                    triggered_positions.append(new_pos)
                else:
                    pos_obj = self.open_positions.get(pid)
                    if pos_obj:
                        pos_obj.sl = cur_p_sl
                        pos_obj.tp = cur_p_tp

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
        positions = mt5.positions_get() if MT5_AVAILABLE else None
        total_pnl = 0.0
        if positions:
            for p in positions:
                total_pnl += float(getattr(p, "profit", 0.0) or 0.0)
        return total_pnl

    def sync_history_from_mt5(self, days: int = 180, force: bool = False):
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
            deals = mt5.history_deals_get(from_date, to_date)
            if deals:
                pos_entry_times = {d.position_id: float(d.time) for d in deals if getattr(d, "entry", 0) == 0}
                synced_trades = []
                synced_pnl = 0.0
                target_syms = {self.symbol.upper(), (exness_symbol or "").upper()}
                for d in deals:
                    d_sym = str(getattr(d, "symbol", "")).upper()
                    if d_sym and (d_sym in target_syms or any(ts in d_sym or d_sym in ts for ts in target_syms if ts)):
                        pnl = float(getattr(d, "profit", 0.0)) + float(getattr(d, "swap", 0.0)) + float(getattr(d, "commission", 0.0))
                        if getattr(d, "entry", 0) in (1, 2) or abs(pnl) > 0.0001:
                            ex_sec = float(d.time / 1000.0) if d.time > 1e11 else float(d.time)
                            raw_e = pos_entry_times.get(d.position_id, None)
                            if raw_e is not None:
                                raw_sec = float(raw_e / 1000.0) if raw_e > 1e11 else float(raw_e)
                                e_sec = min(raw_sec, ex_sec - 1.0)
                            else:
                                e_sec = ex_sec - 15.0
                            t_record = {
                                "position_id": f"deal_{d.ticket}",
                                "type": "BUY" if getattr(d, "type", 0) == 1 else "SELL",
                                "entry_price": float(d.price),
                                "exit_price": float(d.price),
                                "size": float(d.volume),
                                "pnl": pnl,
                                "entry_time": e_sec,
                                "exit_time": ex_sec,
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

    def place_order(self, order_type: str, price: float, size: float, timestamp: float, tp: float = 0.0, sl: float = 0.0) -> Order:
        order_id = f"sim_{int(time.time() * 1000)}_{len(self.pending_orders)+1}"
        order = Order(order_type, price, size, timestamp)
        order.order_id = order_id
        order.tp = tp
        order.sl = sl
        self.pending_orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        return self.pending_orders.pop(order_id, None)

    def cancel_all_orders(self, symbol: Optional[str] = None):
        if symbol:
            to_remove = [oid for oid, ord_obj in list(self.pending_orders.items()) if getattr(ord_obj, "symbol", symbol) == symbol]
            for oid in to_remove:
                self.pending_orders.pop(oid, None)
        else:
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
            "entry_time": getattr(pos, "timestamp", getattr(pos, "entry_time", timestamp)),
            "exit_time": timestamp,
            "commission": 0.0
        }
        self.closed_trades.append(record)
        self.realized_pnl += pnl
        return record

    def close_all_positions(self, exit_price: float = 0.0, timestamp: float = 0.0, symbol: Optional[str] = None, side: Optional[str] = None) -> List[dict]:
        closed = []
        for pid, pos in list(self.open_positions.items()):
            if symbol and getattr(pos, "symbol", symbol) != symbol:
                continue
            if side and str(side).upper() != pos.type:
                continue
            rec = self.close_position(pid, exit_price or getattr(pos, 'entry_price', 0.0), timestamp or time.time())
            if rec:
                closed.append(rec)
        return closed

    def close_buy_positions(self, symbol: Optional[str] = None) -> List[dict]:
        return self.close_all_positions(symbol=symbol, side="BUY")

    def close_sell_positions(self, symbol: Optional[str] = None) -> List[dict]:
        return self.close_all_positions(symbol=symbol, side="SELL")

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
        sym_u = str(getattr(self, "symbol", "")).upper()
        contract_mult = 100.0 if ("XAU" in sym_u or "PAXG" in sym_u or "GOLD" in sym_u) else 1.0
        for pos in self.open_positions.values():
            pnl = ((current_price - pos.entry_price) * pos.size * contract_mult) if pos.type == "BUY" else ((pos.entry_price - current_price) * pos.size * contract_mult)
            pos.profit = pnl
            total += pnl
        return total


    def sync(self):
        pass
