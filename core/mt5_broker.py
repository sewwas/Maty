import time
import os
import sys
from typing import Dict, List, Optional, Any

try:
    import MetaTrader5 as mt5
    if not hasattr(mt5, 'initialize'):
        raise ImportError("MetaTrader5 _core DLL is blocked or failed to initialize.")
    MT5_AVAILABLE = True
except (ImportError, Exception):
    mt5 = None
    MT5_AVAILABLE = False

if not MT5_AVAILABLE:
    try:
        import requests
        bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
        r_bridge = requests.get(f"http://127.0.0.1:{bridge_port}/account", timeout=0.5)
        if r_bridge.status_code == 200 and r_bridge.json().get("connected"):
            MT5_AVAILABLE = True
    except Exception:
        pass

SYMBOL_MAGIC_NUMBERS = {
    "XAUUSD": 998876,
    "GOLD": 998876,
    "PAXGUSDT": 998876
}

class TradeDisabledError(RuntimeError):
    pass


def is_manual_magic(magic: Optional[Any]) -> bool:
    """Returns True if the magic number belongs to a manual bot (>= 1,000,000)."""
    if magic is None:
        return False
    try:
        m = int(magic)
        return m >= 1000000 or str(m).startswith("100")
    except Exception:
        return False


def get_symbol_magic_number(symbol: str, is_manual: bool = False) -> int:
    if not symbol:
        base = 998877
    else:
        sym_upper = symbol.upper()
        if sym_upper in SYMBOL_MAGIC_NUMBERS:
            base = SYMBOL_MAGIC_NUMBERS[sym_upper]
        else:
            clean_sym = sym_upper.replace("USDT", "").replace("USDC", "").replace("USD", "")
            if clean_sym in ("PAXG", "XAU", "GOLD"):
                base = 998876
            else:
                char_code_sum = sum(ord(c) * (i + 1) for i, c in enumerate(sym_upper))
                base = 998870 + (char_code_sum % 1000)
    
    return base + 10000 if is_manual else base


class MT5Broker:
    """
    Clean, simplified MT5 Broker interface for Exness MetaTrader 5 trading.
    Handles order placement, cancellation, position tracking, and floating PnL.
    """
    def __init__(self, symbol: str = "PAXGUSDT", login: Optional[int] = None, password: str = "", server: str = "", symbol_suffix: str = "", magic_number: Optional[int] = None):
        from core.engine import Order, Position
        self.OrderClass = Order
        self.PositionClass = Position

        if not MT5_AVAILABLE:
            self.is_simulated = True
        else:
            self.is_simulated = False
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                r_bridge = requests.get(f"http://127.0.0.1:{bridge_port}/account", timeout=0.5)
                if r_bridge.status_code == 200:
                    d_b = r_bridge.json()
                    if d_b.get("connected"):
                        self.login = int(d_b.get("login", self.login if self.login else 257515247))
                        self.server = str(d_b.get("server", self.server if self.server else "Exness-MT5Real36"))
            except Exception:
                pass

        if isinstance(symbol, int) and isinstance(login, str):
            symbol, login = login, symbol

        self.symbol = str(symbol)
        self.login = int(login) if (login is not None and str(login).isdigit()) else 0
        self.password = str(password)
        self.server = str(server)
        self.symbol_suffix = str(symbol_suffix)
        self.magic_number = magic_number if (magic_number is not None and magic_number != 998877) else get_symbol_magic_number(self.symbol)

        self.pending_orders: Dict[str, Any] = {}
        self.open_positions: Dict[str, Any] = {}
        self.closed_trades: List[dict] = []
        self.realized_pnl = 0.0

        self.ticket_to_order_id: Dict[int, str] = {}
        self.ticket_to_position_id: Dict[int, str] = {}
        self.runner_ids = set()

        try:
            if mt5 is not None:
                if not mt5.initialize():
                    print(f"Notice: MT5 initialize status: {mt5.last_error()}")

                acc = (mt5.account_info if mt5 is not None else (lambda *a, **k: None))()
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

        u_sym = (ui_symbol or "").upper().strip()
        symbol_map = {
            "PAXGUSDT": "XAUUSD",
            "PAXGUSD": "XAUUSD",
            "PAXGUSDC": "XAUUSD",
            "GOLD": "XAUUSD"
        }
        base_sym = symbol_map.get(u_sym, u_sym)

        clean_base = base_sym
        for q in ["USDT", "USDC", "USD"]:
            if clean_base.endswith(q):
                clean_base = clean_base[:-len(q)]
                break

        probes = []
        if self.symbol_suffix:
            probes.append(f"{base_sym}{self.symbol_suffix}")

        if clean_base and clean_base != base_sym:
            probes.extend([
                f"{clean_base}USD", f"{clean_base}USDm", f"{clean_base}USDc", f"{clean_base}USD.a",
                f"{clean_base}USDT", f"{clean_base}USDTm", f"{clean_base}USDTc",
                f"{clean_base}USDC", f"{clean_base}USDCm",
                clean_base, f"{clean_base}m", f"{clean_base}c"
            ])
        probes.extend([f"{base_sym}m", base_sym, f"{base_sym}c", f"{base_sym}.a", f"{base_sym}_i"])

        seen_p = set()
        dedup_probes = []
        for p in probes:
            if p and p not in seen_p:
                seen_p.add(p)
                dedup_probes.append(p)

        res = ui_symbol
        if MT5_AVAILABLE and mt5 is not None:
            for candidate in dedup_probes:
                if (mt5.symbol_select if mt5 is not None else (lambda *a, **k: False))(candidate, True):
                    info = (mt5.symbol_info if mt5 is not None else (lambda *a, **k: None))(candidate)
                    if info is not None:
                        res = candidate
                        break

            if res == ui_symbol:
                group_symbols = (mt5.symbols_get if mt5 is not None else (lambda *a, **k: ()))(group=f"*{clean_base}*")
                if group_symbols:
                    matching = [s.name for s in group_symbols if s.name.upper().startswith(clean_base.upper())]
                    if matching:
                        matching.sort(key=lambda name: (len(name), name))
                        res = matching[0]
        else:
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                r_sym = requests.get(f"http://127.0.0.1:{bridge_port}/symbol_info?symbol={base_sym}", timeout=0.8)
                if r_sym.status_code == 200:
                    d_sym = r_sym.json()
                    if d_sym.get("symbol") and not d_sym.get("error"):
                        res = str(d_sym.get("symbol"))
            except Exception:
                res = base_sym

        self._exness_symbol_cache[ui_symbol] = res
        return res

    def get_account_info(self):
        if mt5 is not None:
            try:
                acc_native = (mt5.account_info if mt5 is not None else (lambda *a, **k: None))()
                if acc_native:
                    return acc_native
            except Exception:
                pass
        try:
            import requests
            bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
            r = requests.get(f"http://127.0.0.1:{bridge_port}/account", timeout=1.0)
            if r.status_code == 200:
                d = r.json()
                if d.get("connected"):
                    class BridgeAcc:
                        pass
                    b = BridgeAcc()
                    b.login = int(d.get("login", 257515247))
                    b.server = str(d.get("server", "Exness-MT5Real36"))
                    b.balance = float(d.get("balance", 1000.0))
                    b.equity = float(d.get("equity", 1000.0))
                    b.leverage = int(d.get("leverage", 2000))
                    b.currency = str(d.get("currency", "USD"))
                    return b
        except Exception:
            pass
        return None

    def ensure_connected(self) -> bool:
        acc = self.get_account_info()
        if acc:
            return True
        if not MT5_AVAILABLE or mt5 is None:
            return False

        now = time.time()
        if hasattr(self, "_last_conn_ok") and (now - self._last_conn_ok < 3.0):
            return True
        try:
            if mt5.terminal_info() is None:
                mt5.initialize()
            acc = (mt5.account_info if mt5 is not None else (lambda *a, **k: None))()
            if acc is None:
                if self.password:
                    mt5.login(login=self.login, password=self.password, server=self.server)
                acc = (mt5.account_info if mt5 is not None else (lambda *a, **k: None))()
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
        return False

    @property
    def balance_usd(self) -> float:
        return self.balance

    @property
    def balance(self) -> float:
        """Returns account cash balance (realized funds only, excludes floating PnL)."""
        now = time.time()
        if hasattr(self, "_acc_info_cache"):
            acc, ts = self._acc_info_cache
            if now - ts < 1.0 and acc:
                return float(acc.balance)
        acc = self.get_account_info()
        self._acc_info_cache = (acc, now)
        if acc:
            return float(acc.balance)
        return 1000.0

    @property
    def _balance(self) -> float:
        return self.balance

    @_balance.setter
    def _balance(self, val: float):
        pass

    def get_equity(self, current_price: float = 0.0) -> float:
        """Returns account equity (balance + floating PnL)."""
        now = time.time()
        if hasattr(self, "_acc_info_cache"):
            acc, ts = self._acc_info_cache
            if now - ts < 1.0 and acc:
                return float(acc.equity)
        acc = self.get_account_info()
        self._acc_info_cache = (acc, now)
        if acc:
            return float(acc.equity)
        return self.balance

    def get_cached_symbol_info(self, exness_symbol: str):
        now = time.time()
        if not hasattr(self, "_symbol_info_cache"):
            self._symbol_info_cache = {}
        if exness_symbol in self._symbol_info_cache:
            info, ts = self._symbol_info_cache[exness_symbol]
            if now - ts < 2.0 and info is not None:
                return info

        info = None
        if MT5_AVAILABLE and mt5 is not None and exness_symbol:
            mt5.symbol_select(exness_symbol, True)
            info = mt5.symbol_info(exness_symbol)
        elif MT5_AVAILABLE and exness_symbol:
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                r = requests.get(f"http://127.0.0.1:{bridge_port}/symbol_info?symbol={exness_symbol}", timeout=1.0)
                if r.status_code == 200:
                    d = r.json()
                    if not d.get("error"):
                        class MockSymbolInfo:
                            def __init__(self, data):
                                self.name = data.get("symbol", exness_symbol)
                                self.point = float(data.get("point", 0.001 if "XAU" in str(exness_symbol).upper() else 0.0001))
                                self.digits = int(data.get("digits", 3 if "XAU" in str(exness_symbol).upper() else 5))
                                self.trade_mode = int(data.get("trade_mode", 4))
                                self.trade_stops_level = int(data.get("trade_stops_level", 0))
                                self.volume_min = float(data.get("volume_min", 0.01))
                                self.volume_max = float(data.get("volume_max", 100.0))
                                self.volume_step = float(data.get("volume_step", 0.01))
                                self.filling_mode = int(data.get("filling_mode", 4))
                                self.contract_size = float(data.get("contract_size", 100.0 if "XAU" in str(exness_symbol).upper() else 1.0))
                                self.currency_profit = str(data.get("currency_profit", "USD"))
                                self.currency_margin = str(data.get("currency_margin", "USD"))
                                self.ask = float(data.get("ask", 0.0))
                                self.bid = float(data.get("bid", 0.0))
                        info = MockSymbolInfo(d)
            except Exception:
                info = None

        if not info:
            class DefaultMockInfo:
                def __init__(self, sym):
                    self.name = sym
                    self.point = 0.001 if "XAU" in str(sym).upper() else 0.0001
                    self.digits = 3 if "XAU" in str(sym).upper() else 5
                    self.trade_mode = 4
                    self.trade_stops_level = 0
                    self.volume_min = 0.01
                    self.volume_max = 100.0
                    self.volume_step = 0.01
                    self.filling_mode = 4
                    self.ask = 0.0
                    self.bid = 0.0
            info = DefaultMockInfo(exness_symbol)

        if info:
            self._symbol_info_cache[exness_symbol] = (info, now)
        return info

    def get_current_spread(self) -> float:
        exness_symbol = self.get_exness_symbol(self.symbol)
        info = self.get_cached_symbol_info(exness_symbol) if exness_symbol else None
        if info and info.ask and info.bid:
            return abs(info.ask - info.bid)
        return 0.0

    def _fetch_live_orders(self, symbol: Optional[str] = None):
        if MT5_AVAILABLE and mt5 is not None:
            return mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
        try:
            import requests
            bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
            sym_param = f"?symbol={symbol}" if symbol else ""
            r = requests.get(f"http://127.0.0.1:{bridge_port}/orders{sym_param}", timeout=1.0)
            if r.status_code == 200:
                data = r.json()
                res = []
                for d in data.get("orders", []):
                    class BridgeOrder:
                        pass
                    o = BridgeOrder()
                    o.ticket = int(d.get("ticket", 0))
                    o.symbol = str(d.get("symbol", ""))
                    o.type = int(d.get("type", 0))
                    o.price_open = float(d.get("price_open", 0.0))
                    o.volume_initial = float(d.get("volume_initial", 0.01))
                    o.sl = float(d.get("sl", 0.0))
                    o.tp = float(d.get("tp", 0.0))
                    o.magic = int(d.get("magic", 0))
                    o.time_setup = int(d.get("time_setup", time.time()))
                    res.append(o)
                return res
        except Exception:
            pass
        return []

    def _fetch_live_positions(self, symbol: Optional[str] = None, ticket: Optional[int] = None):
        if MT5_AVAILABLE and mt5 is not None:
            if ticket:
                return mt5.positions_get(ticket=ticket)
            return mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        try:
            import requests
            bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
            sym_param = f"?symbol={symbol}" if symbol else ""
            r = requests.get(f"http://127.0.0.1:{bridge_port}/positions{sym_param}", timeout=1.0)
            if r.status_code == 200:
                data = r.json()
                res = []
                for d in data.get("positions", []):
                    if ticket and int(d.get("ticket", 0)) != int(ticket):
                        continue
                    class BridgePos:
                        pass
                    p = BridgePos()
                    p.ticket = int(d.get("ticket", 0))
                    p.symbol = str(d.get("symbol", ""))
                    p.type = int(d.get("type", 0))
                    p.price_open = float(d.get("price_open", 0.0))
                    p.price_current = float(d.get("price_current", 0.0))
                    p.volume = float(d.get("volume", 0.01))
                    p.sl = float(d.get("sl", 0.0))
                    p.tp = float(d.get("tp", 0.0))
                    p.profit = float(d.get("profit", 0.0))
                    p.magic = int(d.get("magic", 0))
                    p.time = int(d.get("time", time.time()))
                    res.append(p)
                return res
        except Exception:
            pass
        return []

    def get_total_account_orders_count(self) -> int:
        """Returns order+position count for THIS symbol and magic number only."""
        if not self.ensure_connected():
            return len(self.pending_orders) + len(self.open_positions)
        try:
            exness_symbol = self.get_exness_symbol(self.symbol)
            orders = self._fetch_live_orders(exness_symbol) or []
            positions = self._fetch_live_positions(exness_symbol) or []
            n_orders = sum(1 for o in orders if getattr(o, "magic", 0) == self.magic_number)
            n_positions = sum(1 for p in positions if getattr(p, "magic", 0) == self.magic_number)
            return n_orders + n_positions
        except Exception:
            return len(self.pending_orders) + len(self.open_positions)

    def get_min_stop_distance(self) -> float:
        exness_symbol = self.get_exness_symbol(self.symbol)
        info = self.get_cached_symbol_info(exness_symbol) if exness_symbol else None
        if info:
            point = info.point if hasattr(info, "point") and info.point else 0.0001
            stops_level = getattr(info, "trade_stops_level", 0) or 0
            return max(stops_level * point, point * 10.0)
        return 0.50 if "XAU" in self.symbol.upper() or "GOLD" in self.symbol.upper() else 0.005

    def place_order(self, order_type: str, price: float, size: float, timestamp: float, tp: float = 0.0, sl: float = 0.0) -> Any:
        from core.engine import Order
        
        if not self.ensure_connected():
            if mt5 is not None:
                raise RuntimeError("MT5 connection offline.")

        exness_symbol = self.get_exness_symbol(self.symbol)
        symbol_info = self.get_cached_symbol_info(exness_symbol)
        if symbol_info is None:
            if mt5 is not None:
                raise RuntimeError(f"Symbol {exness_symbol} info not found.")
            else:
                class DummySym:
                    point = 0.001
                    digits = 3
                    trade_stops_level = 0
                symbol_info = DummySym()

        if getattr(symbol_info, "trade_mode", 4) == 0:
            if mt5 is not None:
                raise TradeDisabledError(f"Exness server has disabled trading for {exness_symbol} on this account.")

        point = symbol_info.point
        stops_level = getattr(symbol_info, "trade_stops_level", 0) or 0
        min_stop_dist = max(stops_level * point, point * 50.0)

        if mt5 is not None:
            tick = mt5.symbol_info_tick(exness_symbol)
            ask = tick.ask if tick else price
            bid = tick.bid if tick else price
        else:
            ask = price
            bid = price

        if order_type == "BUY_LIMIT":
            mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if mt5 is not None else 2
            trigger_price = price if price < (ask - min_stop_dist) else (ask - min_stop_dist)
        elif order_type == "BUY_STOP":
            mt5_type = mt5.ORDER_TYPE_BUY_STOP if mt5 is not None else 4
            trigger_price = price if price > (ask + min_stop_dist) else (ask + min_stop_dist)
        elif order_type == "SELL_LIMIT":
            mt5_type = mt5.ORDER_TYPE_SELL_LIMIT if mt5 is not None else 3
            trigger_price = price if price > (bid + min_stop_dist) else (bid + min_stop_dist)
        elif order_type == "SELL_STOP":
            mt5_type = mt5.ORDER_TYPE_SELL_STOP if mt5 is not None else 5
            trigger_price = price if price < (bid - min_stop_dist) else (bid - min_stop_dist)
        else:
            mt5_type = mt5.ORDER_TYPE_BUY_STOP if mt5 is not None else 4
            trigger_price = price if price > (ask + min_stop_dist) else (ask + min_stop_dist)
            order_type = "BUY_STOP"

        digits = symbol_info.digits
        trigger_price = round(trigger_price, digits)

        vol_min = getattr(symbol_info, "volume_min", 0.01) or 0.01
        vol_max = getattr(symbol_info, "volume_max", 100.0) or 100.0
        vol_step = getattr(symbol_info, "volume_step", 0.01) or 0.01
        order_size = max(vol_min, min(vol_max, round(round(size / vol_step) * vol_step, 4) if vol_step > 0 else round(size, 4)))

        existing_positions = self._fetch_live_positions(exness_symbol)
        if existing_positions:
            # Filter to THIS broker's magic number only
            my_magic = getattr(self, "magic_number", None)
            if my_magic is not None:
                existing_positions = [p for p in existing_positions if getattr(p, "magic", 0) == my_magic]
            # Manual bot (magic >= 1,000,000) allows up to 50 positions; auto bot capped at 2
            is_manual_broker = is_manual_magic(my_magic)
            pos_cap = 50 if is_manual_broker else 2
            vol_cap = 100.0 if is_manual_broker else 0.05
            total_open_vol = sum(float(getattr(p, "volume", 0.0) or 0.0) for p in existing_positions)
            if len(existing_positions) >= pos_cap or (not is_manual_broker and total_open_vol + order_size > vol_cap):
                return None   # Position cap hit

        sym_u_name = str(exness_symbol).upper()
        px_tolerance = 0.01 if any(x in sym_u_name for x in ["XAU", "GOLD", "PAXG"]) else 0.00005

        p_ord_copy = list(self.pending_orders.items())
        for oid, p_ord in p_ord_copy:
            ord_px = getattr(p_ord, "trigger_price", getattr(p_ord, "price_open", 0.0))
            if getattr(p_ord, "type", "") == order_type and abs(trigger_price - ord_px) <= px_tolerance:
                tk = int(getattr(p_ord, "broker_ticket", getattr(p_ord, "mt5_ticket", 0)) or 0)
                live_o = (mt5.orders_get if mt5 is not None else (lambda *a, **k: ()))(ticket=tk) if (MT5_AVAILABLE and tk > 0) else None
                if live_o:
                    return p_ord
                else:
                    self.pending_orders.pop(oid, None)
        existing_orders = []
        if MT5_AVAILABLE:
            for s_alias in set([exness_symbol, self.symbol, f"{exness_symbol}m", f"{exness_symbol}c", "XAUUSD", "XAUUSDm"]):
                if s_alias:
                    ords = (mt5.orders_get if mt5 is not None else (lambda *a, **k: ()))(symbol=s_alias)
                    if ords:
                        existing_orders.extend(list(ords))
            if not existing_orders:
                all_o = (mt5.orders_get if mt5 is not None else (lambda *a, **k: ()))()
                if all_o:
                    clean_target = "XAU" if any(x in self.symbol.upper() for x in ["XAU", "GOLD"]) else ("PAXG" if "PAXG" in self.symbol.upper() else self.symbol.replace("USDT", "").replace("USDC", "").replace("USD", "").upper())
                    existing_orders = [o for o in all_o if clean_target in str(o.symbol).upper()]

        if existing_orders:
            for ext_o in existing_orders:
                is_ext_buy = ext_o.type in [mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_LIMIT, 2, 4]
                is_new_buy = mt5_type in [mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_BUY_LIMIT, 2, 4]
                if is_ext_buy == is_new_buy:
                    if abs(float(ext_o.price_open) - trigger_price) <= px_tolerance:
                        loc_ord = Order(order_type, ext_o.price_open, getattr(ext_o, "volume_initial", size), getattr(ext_o, "time_setup", timestamp))
                        loc_ord.order_id = f"mt5_{ext_o.ticket}"
                        loc_ord.mt5_ticket = ext_o.ticket
                        self.ticket_to_order_id[ext_o.ticket] = loc_ord.order_id
                        self.pending_orders[loc_ord.order_id] = loc_ord
                        return loc_ord

        vol_min = getattr(symbol_info, "volume_min", 0.01) or 0.01
        vol_max = getattr(symbol_info, "volume_max", 100.0) or 100.0
        vol_step = getattr(symbol_info, "volume_step", 0.01) or 0.01
        order_size = max(vol_min, min(vol_max, round(round(size / vol_step) * vol_step, 4) if vol_step > 0 else round(size, 4)))

        sym_name = str(exness_symbol).upper()
        if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]):
            min_sl_dist = 35.0
            min_tp_dist = 0.50
        else:
            min_sl_dist = max(min_stop_dist * 2.0, point * 50.0)
            min_tp_dist = max(min_stop_dist * 2.0, point * 10.0)

        if "BUY" in order_type:
            # tp=0.0  → no TP on MT5 (basket-managed)
            # tp>0    → caller-specified TP price
            tp_val = round(tp, digits) if tp > 0 else 0.0
            sl_val = round(sl, digits) if sl > 0 else 0.0
        else:
            tp_val = round(tp, digits) if tp > 0 else 0.0
            sl_val = round(sl, digits) if sl > 0 else 0.0

        if mt5 is None:
            try:
                import requests
                import os
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                url = f"http://127.0.0.1:{bridge_port}/order_send?symbol={exness_symbol}&type={order_type}&price={trigger_price}&volume={order_size}&sl={sl_val}&tp={tp_val}&magic={self.magic_number}"
                r_resp = requests.get(url, timeout=3.0)
                if r_resp.status_code == 200:
                    data = r_resp.json()
                    if data.get("success"):
                        ticket = data.get("ticket", int(time.time()))
                        loc_ord = Order(order_type, trigger_price, order_size, timestamp)
                        loc_ord.order_id = f"mt5_{ticket}"
                        loc_ord.broker_ticket = ticket
                        self.pending_orders[loc_ord.order_id] = loc_ord
                        self.ticket_to_order_id[ticket] = loc_ord.order_id
                        return loc_ord
                    else:
                        print(f"[{exness_symbol}] REST Bridge order_send returned: {data}")
            except Exception as e:
                print(f"[{self.symbol}] REST Bridge order_send exception: {e}")
            return None

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

        # Consider 0, 10004, 10008, 10009 as successful placement
        success_codes = [0, mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED, 10004]

        if result is None or getattr(result, "retcode", -1) not in success_codes:
            for alt_fill in [mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]:
                if alt_fill != best_filling:
                    request["type_filling"] = alt_fill
                    result = mt5.order_send(request)
                    if result is not None and getattr(result, "retcode", -1) in success_codes:
                        break

        if result is None or getattr(result, "retcode", -1) not in success_codes:
            retcode  = getattr(result, "retcode", "N/A")
            comment  = getattr(result, "comment", "no result")
            sym_log  = exness_symbol or self.symbol
            # Only print if it's an actual rejection, not a success code
            if retcode not in success_codes and comment != "ok":
                print(f"[{sym_log}] MT5 order rejected (retcode={retcode}): {comment} | type={order_type} price={trigger_price}")
            
            # Retry with adjusted price — keep the same order type (do NOT convert LIMIT to STOP)
            if order_type == "BUY_LIMIT":
                request["price"] = round(min(trigger_price, ask - min_stop_dist * 2), digits)
                request["tp"]    = round(tp, digits) if tp > 0 else 0.0
                request["sl"]    = round(sl, digits) if sl > 0 else 0.0
            elif order_type == "SELL_LIMIT":
                request["price"] = round(max(trigger_price, bid + min_stop_dist * 2), digits)
                request["tp"]    = round(tp, digits) if tp > 0 else 0.0
                request["sl"]    = round(sl, digits) if sl > 0 else 0.0
            elif "BUY" in order_type:
                request["type"]  = mt5.ORDER_TYPE_BUY_STOP
                request["price"] = max(price, ask + min_stop_dist)
                request["tp"]    = round(tp, digits) if tp > 0 else 0.0
                request["sl"]    = round(sl, digits) if sl > 0 else 0.0
            else:
                request["type"]  = mt5.ORDER_TYPE_SELL_STOP
                request["price"] = min(price, bid - min_stop_dist)
                request["tp"]    = round(tp, digits) if tp > 0 else 0.0
                request["sl"]    = round(sl, digits) if sl > 0 else 0.0
            result = mt5.order_send(request)

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

    def purge_duplicate_mt5_orders(self) -> int:
        if not self.ensure_connected():
            return 0
        exness_symbol = self.get_exness_symbol(self.symbol)
        orders = self._fetch_live_orders(exness_symbol)
        if not orders:
            return 0

        unique_orders_dict = {o.ticket: o for o in orders}
        unique_orders = list(unique_orders_dict.values())

        sym_info = self.get_cached_symbol_info(exness_symbol)
        digits = sym_info.digits if sym_info and hasattr(sym_info, "digits") else 2

        purged = 0
        by_price = {}
        for o in unique_orders:
            if hasattr(self, "magic_number") and self.magic_number and getattr(o, "magic", 0) != self.magic_number:
                continue
            o_type = getattr(o, "type", 0)

            px_key = (o_type, round(float(getattr(o, "price_open", 0.0)), digits))
            if px_key not in by_price:
                by_price[px_key] = []
            by_price[px_key].append(o)
        for px_key, same_price_orders in by_price.items():
            if len(same_price_orders) > 1:
                same_price_orders.sort(key=lambda x: getattr(x, "time_setup", 0), reverse=True)
                for extra_o in same_price_orders[1:]:
                    extra_ticket = int(extra_o.ticket)
                    if mt5 is not None:
                        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": extra_ticket}
                        res = mt5.order_send(req)
                        if res and res.retcode in (0, 10009, 10008, 10004):
                            purged += 1
                    else:
                        try:
                            import requests
                            bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                            r_c = requests.get(f"http://127.0.0.1:{bridge_port}/order_cancel?ticket={extra_ticket}", timeout=1.5)
                            if r_c.status_code == 200 and r_c.json().get("success"):
                                purged += 1
                        except Exception:
                            pass
                    self.pending_orders.pop(f"live_ord_{extra_ticket}", None)
                    self.pending_orders.pop(f"mt5_{extra_ticket}", None)
                    self.ticket_to_order_id.pop(extra_ticket, None)

        return purged

    def purge_duplicate_mt5_positions(self) -> int:
        if not self.ensure_connected():
            return 0
        exness_symbol = self.get_exness_symbol(self.symbol)
        poss = (mt5.positions_get if mt5 is not None else (lambda *a, **k: ()))(symbol=exness_symbol) if (MT5_AVAILABLE and exness_symbol) else None
        if not poss and MT5_AVAILABLE:
            all_poss = (mt5.positions_get if mt5 is not None else (lambda *a, **k: ()))()
            if all_poss:
                clean_target = "XAU" if any(x in self.symbol.upper() for x in ["XAU", "GOLD"]) else ("PAXG" if "PAXG" in self.symbol.upper() else self.symbol.replace("USDT", "").replace("USDC", "").replace("USD", "").upper())
                poss = [p for p in all_poss if clean_target in str(p.symbol).upper()]

        if not poss:
            return 0
            
        my_poss = [p for p in poss if getattr(p, "magic", 0) == getattr(self, "magic_number", 0)]
        
        # Manual bots allow up to 50 active positions. Auto bots are capped at 2.
        is_manual = is_manual_magic(getattr(self, "magic_number", 0))
        max_allowed = 50 if is_manual else 2

        if len(my_poss) <= max_allowed:
            return 0

        my_poss.sort(key=lambda x: getattr(x, "time", 0), reverse=True)
        excess = my_poss[max_allowed:]
        closed_count = 0
        for p in excess:
            close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(p.symbol)
            if not tick:
                continue
            price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": close_type,
                "position": p.ticket,
                "price": price,
                "deviation": 20,
                "magic": getattr(p, "magic", 0),
                "comment": "Max 2 Position Ceiling Purge",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            res = mt5.order_send(req)
            if res and res.retcode in (0, 10009, 10008, 10004):
                closed_count += 1
                pid = self.ticket_to_position_id.pop(p.ticket, None)
                if pid:
                    self.open_positions.pop(pid, None)
        return closed_count

    def cancel_order(self, order_id: str) -> Any:
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

        cancel_ok = False
        if ticket:
            if mt5 is not None:
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
                res = mt5.order_send(req)
                cancel_ok = res is not None and getattr(res, "retcode", -1) in (0, 10009, 10008, 10004)
            else:
                try:
                    import requests
                    bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                    r_c = requests.get(f"http://127.0.0.1:{bridge_port}/order_cancel?ticket={ticket}", timeout=1.5)
                    cancel_ok = r_c.status_code == 200 and r_c.json().get("success")
                except Exception:
                    cancel_ok = False

            if not cancel_ok:
                # Fix #5: Do NOT call process_tick(0,0,...) here.
                # process_tick with (0, 0) triggers purge_duplicate_mt5_positions which can
                # close real live positions as a side effect of the cancel error path.
                # State will resync naturally on the next regular tick from the engine.
                pass

        if cancel_ok or (ticket is None):
            self.pending_orders.pop(order_id, None)
            if ticket:
                self.ticket_to_order_id.pop(ticket, None)
        return order

    def cancel_all_orders(self, symbol: Optional[str] = None):
        if hasattr(self, "_in_flight_orders") and isinstance(self._in_flight_orders, set):
            self._in_flight_orders.clear()
            
        if not self.ensure_connected():
            self.pending_orders.clear()
            self.ticket_to_order_id.clear()
            return

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)

        orders_list = []
        if mt5 is not None:
            for s_alias in set([exness_symbol, sym, f"{exness_symbol}m", f"{exness_symbol}c", "XAUUSD", "XAUUSDm"]):
                if s_alias and MT5_AVAILABLE:
                    ords = mt5.orders_get(symbol=s_alias)
                    if ords:
                        orders_list.extend(list(ords))

            if not orders_list and MT5_AVAILABLE:
                all_o = mt5.orders_get()
                if all_o:
                    clean_target = "XAU" if any(x in str(sym).upper() for x in ["XAU", "GOLD"]) else ("PAXG" if "PAXG" in str(sym).upper() else str(sym).replace("USDT", "").replace("USDC", "").replace("USD", "").upper())
                    orders_list = [o for o in all_o if clean_target in str(o.symbol).upper()]

            all_tks = set()
            if orders_list:
                for o in orders_list:
                    if getattr(o, "magic", self.magic_number) == self.magic_number:
                        all_tks.add((o.ticket, o.symbol))

            has_error = False
            for t, sym_name_tk in all_tks:
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": t, "symbol": sym_name_tk}
                res = mt5.order_send(req)
                if res and res.retcode not in (0, 10009, 10008, 10004) and res.retcode != 10013:
                    print(f"[MT5Broker] MT5 cancel failed for {t} retcode {res.retcode}")
                    has_error = True
                elif res is None:
                    print(f"[MT5Broker] MT5 cancel failed for {t} (No response)")
                    has_error = True
                else:
                    # Success or already removed (10013)
                    oid = self.ticket_to_order_id.get(t)
                    if oid: self.pending_orders.pop(oid, None)
                    self.pending_orders.pop(f"mt5_{t}", None)
                    self.pending_orders.pop(f"live_ord_{t}", None)
                    self.ticket_to_order_id.pop(t, None)
                    
            if has_error:
                raise Exception("Failed to cancel one or more MT5 orders")
                
        else:
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                params = []
                if exness_symbol:
                    params.append(f"symbol={exness_symbol}")
                if getattr(self, "magic_number", None) is not None:
                    params.append(f"magic={self.magic_number}")
                query_str = ("?" + "&".join(params)) if params else ""
                r = requests.get(f"http://127.0.0.1:{bridge_port}/cancel_all{query_str}", timeout=15.0)
                if r.status_code != 200:
                    raise Exception(f"REST Bridge cancel_all returned status {r.status_code}")
            except Exception as e:
                print(f"[MT5Broker] REST Bridge cancel_all exception: {e}")
                raise e

        self.pending_orders.clear()
        self.ticket_to_order_id.clear()
        time.sleep(0.2)

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
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")

        if not ticket:
            pos_obj = self.open_positions.pop(position_id, None)
            return {"exit_price": exit_price, "profit": float(getattr(pos_obj, "profit", 0.0) or 0.0)} if pos_obj else None

        if mt5 is None:
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                r_cl = requests.get(f"http://127.0.0.1:{bridge_port}/position_close?ticket={ticket}", timeout=2.0)
                if r_cl.status_code == 200 and r_cl.json().get("success"):
                    pos_obj = self.open_positions.pop(position_id, None)
                    pnl = float(getattr(pos_obj, "profit", 0.0) or 0.0)
                    return {"exit_price": exit_price, "profit": pnl}
            except Exception:
                pass
            return None

        pos_list = mt5.positions_get(ticket=ticket)
        if not pos_list:
            pos_obj = self.open_positions.pop(position_id, None)
            return {"exit_price": exit_price, "profit": float(getattr(pos_obj, "profit", 0.0) or 0.0)} if pos_obj else None

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
            req["type_filling"] = mt5.ORDER_FILLING_RETURN
            res = mt5.order_send(req)
            is_ok = res is not None and (res.retcode in (0, 10009, 10008, 10004) or getattr(res, "deal", 0) > 0 or getattr(res, "comment", "") == "ok")

        if is_ok:
            act_exit = getattr(res, "price", 0.0) or price
            pnl = float(getattr(pos, 'profit', 0.0))

            st_sec = float(pos.time / 1000.0) if pos.time > 1e11 else float(pos.time)
            ex_sec = float(timestamp / 1000.0) if timestamp > 1e11 else float(timestamp)
            if ex_sec <= st_sec:   # Guard against negative duration from timestamp unit mismatch
                ex_sec = st_sec + 1.0
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
            except Exception as e:
                import logging; logging.warning(f"Exception: {e}")
            return record
        return None

    def modify_position_sl_tp(self, position_id: str, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
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

        pos = None
        if ticket:
            pos_list = self._fetch_live_positions(ticket=ticket)
            if pos_list:
                pos = pos_list[0]

        if not pos:
            pos_list = self._fetch_live_positions()
            if pos_list:
                for p in pos_list:
                    if getattr(p, "ticket", None) == ticket or str(getattr(p, "ticket", "")) == clean_pid:
                        pos = p
                        ticket = int(p.ticket)
                        break

        if pos and ticket:
            symbol_info = self.get_cached_symbol_info(pos.symbol)
            digits = symbol_info.digits if symbol_info else 4

            cur_p_sl = float(getattr(pos, "sl", 0.0) or 0.0)
            cur_p_tp = float(getattr(pos, "tp", 0.0) or 0.0)

            final_sl = round(sl, digits) if (sl is not None and sl > 0) else cur_p_sl
            final_tp = round(tp, digits) if (tp is not None and tp > 0) else cur_p_tp

            if mt5 is None:
                try:
                    import requests
                    bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                    r_m = requests.get(f"http://127.0.0.1:{bridge_port}/modify_sl_tp?ticket={ticket}&sl={final_sl}&tp={final_tp}", timeout=2.0)
                    is_ok = r_m.status_code == 200 and r_m.json().get("success")
                except Exception:
                    is_ok = False
            else:
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
                pid_key = self.ticket_to_position_id.get(ticket, f"live_{ticket}")
                pos_obj = self.open_positions.get(pid_key)
                if pos_obj:
                    pos_obj.sl = final_sl
                    pos_obj.tp = final_tp
            return is_ok

        # Fix #15: Return False when position not found on MT5.
        # Previously returned True unconditionally here, causing a silent SL tracking desync:
        # local pos_obj.sl was updated (trail_stop_loss does setattr), but MT5 SL never moved.
        # On next tick, target_sl > cur_sl is False (local already updated) → trail stops working.
        return False

    def modify_order(self, order_id: str, price: Optional[float] = None, sl: Optional[float] = None, tp: Optional[float] = None) -> bool:
        return self.modify_position_sl_tp(order_id, sl=sl, tp=tp)

    def partial_close_position(self, position_id: str, close_fraction: float, exit_price: float, timestamp: float) -> Optional[dict]:
        """
        Partially closes a position by `close_fraction` of its current volume.
        close_fraction: 0.0–1.0 (e.g. 0.40 closes 40% of the lot).
        Returns a trade record dict on success, or None on failure.
        This is the foundation for TP1 / TP2 scale-out logic.
        """
        if not self.ensure_connected():
            return None

        close_fraction = max(0.01, min(1.0, float(close_fraction)))

        # Resolve MT5 ticket from position_id
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
                except Exception as e:
                    import logging; logging.warning(f"Exception: {e}")
        if not ticket:
            return None

        pos_list = self._fetch_live_positions(ticket=ticket)
        if not pos_list:
            return None
        pos = pos_list[0]

        # Calculate close volume — round to broker's volume_step
        symbol_info = self.get_cached_symbol_info(pos.symbol)
        vol_step = getattr(symbol_info, "volume_step", 0.01) or 0.01
        vol_min  = getattr(symbol_info, "volume_min",  0.01) or 0.01
        digits_v = max(0, round(-__import__("math").log10(vol_step))) if vol_step < 1 else 0
        close_vol = round(round(pos.volume * close_fraction / vol_step) * vol_step, digits_v)
        close_vol = max(vol_min, min(pos.volume, close_vol))

        close_type = "SELL" if getattr(pos, "type", 0) == 0 else "BUY"
        price = exit_price
        if symbol_info:
            price = symbol_info.bid if close_type == "SELL" else symbol_info.ask
            if not price: price = exit_price

        if mt5 is None:
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                r_pc = requests.get(f"http://127.0.0.1:{bridge_port}/position_close?ticket={ticket}&volume={close_vol}", timeout=3.0)
                is_ok = r_pc.status_code == 200 and r_pc.json().get("success")
            except Exception:
                is_ok = False
        else:
            mt5_close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(pos.symbol)
            price = (tick.bid if mt5_close_type == mt5.ORDER_TYPE_SELL else tick.ask) if tick else exit_price

            filling_mode = getattr(symbol_info, "filling_mode", 0) or 0
            best_filling = mt5.ORDER_FILLING_IOC
            if (filling_mode & mt5.ORDER_FILLING_FOK) != 0:
                best_filling = mt5.ORDER_FILLING_FOK
            elif (filling_mode & mt5.ORDER_FILLING_RETURN) != 0:
                best_filling = mt5.ORDER_FILLING_RETURN

            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       close_vol,
                "type":         mt5_close_type,
                "position":     ticket,
                "price":        price,
                "deviation":    20,
                "magic":        getattr(pos, "magic", self.magic_number),
                "comment":      "Maty Partial TP",
                "type_filling": best_filling,
            }

            res = mt5.order_send(req)
            if res is None or getattr(res, "retcode", -1) not in (0, 10009, 10008, 10004):
                for alt_fill in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                    if alt_fill != best_filling:
                        req["type_filling"] = alt_fill
                        res = mt5.order_send(req)
                        if res is not None and getattr(res, "retcode", -1) in (0, 10009, 10008, 10004):
                            break

            is_ok = res is not None and (
                getattr(res, "retcode", -1) in (0, 10009, 10008, 10004)
                or getattr(res, "deal", 0) > 0
                or getattr(res, "comment", "") == "ok"
            )
        if not is_ok:
            return None

        act_exit = getattr(res, "price", 0.0) or price
        # Partial PnL estimate: pro-rated from MT5 position profit
        total_vol = float(pos.volume) if pos.volume > 0 else 1.0
        pnl = float(getattr(pos, "profit", 0.0)) * (close_vol / total_vol)

        st_sec = float(pos.time / 1000.0) if pos.time > 1e11 else float(pos.time)
        ex_sec = float(timestamp / 1000.0) if timestamp > 1e11 else float(timestamp)
        if ex_sec <= st_sec:
            ex_sec = st_sec + 1.0

        record = {
            "position_id":  position_id,
            "type":         "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
            "entry_price":  float(pos.price_open),
            "exit_price":   act_exit,
            "size":         close_vol,
            "pnl":          round(pnl, 4),
            "entry_time":   st_sec,
            "exit_time":    ex_sec,
            "commission":   0.0,
            "partial":      True,
            "fraction":     close_fraction,
        }
        try:
            self.closed_trades.append(record)
            if len(self.closed_trades) > 500:
                self.closed_trades = self.closed_trades[-500:]
            self.realized_pnl += pnl
            # Update local position volume tracking
            pos_obj = self.open_positions.get(position_id)
            if pos_obj:
                remaining_vol = round(pos.volume - close_vol, digits_v)
                if remaining_vol < vol_min:
                    # Entire position is now closed — remove from tracking
                    self.open_positions.pop(position_id, None)
                    self.ticket_to_position_id.pop(ticket, None)
                else:
                    pos_obj.size = remaining_vol
        except Exception as e:
            import logging; logging.warning(f"Exception: {e}")
        return record

    def close_all_positions(self, exit_price: float = 0.0, timestamp: float = 0.0, symbol: Optional[str] = None, side: Optional[str] = None, exclude_ids: Optional[set] = None) -> List[dict]:
        if not self.ensure_connected():
            return []

        closed = []
        exclude_ids = exclude_ids or set()
        exness_symbol = self.get_exness_symbol(symbol) if symbol else ""

        if mt5 is None:
            try:
                import requests
                bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                params = []
                if exness_symbol:
                    params.append(f"symbol={exness_symbol}")
                if side:
                    params.append(f"side={side}")
                if getattr(self, "magic_number", None) is not None:
                    params.append(f"magic={self.magic_number}")
                query_str = ("?" + "&".join(params)) if params else ""
                url = f"http://127.0.0.1:{bridge_port}/close_all{query_str}"
                r_c = requests.get(url, timeout=4.0)
                if r_c.status_code == 200:
                    data = r_c.json()
                    if data.get("success"):
                        if side:
                            target_side = str(side).upper()
                            for pid, pos in list(self.open_positions.items()):
                                if str(getattr(pos, "type", "")).upper() == target_side:
                                    self.open_positions.pop(pid, None)
                            self.ticket_to_position_id = {
                                tk: pid for tk, pid in self.ticket_to_position_id.items()
                                if pid in self.open_positions
                            }
                        else:
                            self.open_positions.clear()
                            self.ticket_to_position_id.clear()
                        return [{"position_id": "all", "pnl": 0.0, "side": side or "ALL"}]
            except Exception as e:
                print(f"[MT5Broker] REST Bridge close_all exception: {e}")
            return closed

        if symbol:
            positions = mt5.positions_get(symbol=exness_symbol) if exness_symbol else None
        else:
            positions = mt5.positions_get() if MT5_AVAILABLE else None

        if positions:
            # Pre-fetch ALL ticks in one pass so the close loop has zero I/O delay per position
            tick_cache = {}
            sym_info_cache = {}
            for pos in positions:
                if pos.symbol not in tick_cache:
                    tick_cache[pos.symbol] = mt5.symbol_info_tick(pos.symbol)
                if pos.symbol not in sym_info_cache:
                    sym_info_cache[pos.symbol] = self.get_cached_symbol_info(pos.symbol)

            # Now fire all close orders in a tight sequential loop — MT5 API is single-threaded,
            # so this is the fastest safe approach. All calls happen back-to-back with no delays.
            for pos in list(positions):
                try:
                    if f"live_{pos.ticket}" in exclude_ids:
                        continue

                    # Guarantee complete isolation: only close positions belonging to this broker instance
                    if getattr(self, "magic_number", None) is not None:
                        if getattr(pos, "magic", 0) != self.magic_number:
                            continue

                    pos_side = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                    if side and str(side).upper() != pos_side:
                        continue

                    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    tick = tick_cache.get(pos.symbol)
                    price = (tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask) if tick else getattr(pos, "price_current", exit_price)

                    symbol_info = sym_info_cache.get(pos.symbol)
                    filling_mode = getattr(symbol_info, "filling_mode", 0) or 0
                    best_filling = mt5.ORDER_FILLING_IOC
                    if (filling_mode & mt5.ORDER_FILLING_FOK) != 0:
                        best_filling = mt5.ORDER_FILLING_FOK
                    elif (filling_mode & mt5.ORDER_FILLING_RETURN) != 0:
                        best_filling = mt5.ORDER_FILLING_RETURN

                    req = {
                        "action":       mt5.TRADE_ACTION_DEAL,
                        "symbol":       pos.symbol,
                        "volume":       pos.volume,
                        "type":         close_type,
                        "position":     int(pos.ticket),
                        "price":        price,
                        "magic":        getattr(pos, "magic", self.magic_number),
                        "comment":      "Maty BulkClose",
                        "type_filling": best_filling,
                    }

                    res = mt5.order_send(req)
                    if res is None or getattr(res, "retcode", -1) not in (0, 10009, 10008, 10004):
                        for alt_fill in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                            if alt_fill == best_filling:
                                continue
                            req["type_filling"] = alt_fill
                            res = mt5.order_send(req)
                            if res is not None and getattr(res, "retcode", -1) in (0, 10009, 10008, 10004):
                                break

                    is_ok = res is not None and (
                        getattr(res, "retcode", -1) in (0, 10009, 10008, 10004)
                        or getattr(res, "deal", 0) > 0
                        or getattr(res, "comment", "") == "ok"
                    )
                    if is_ok:
                        closed.append({"position_id": f"live_{pos.ticket}", "pnl": float(getattr(pos, "profit", 0.0)), "side": pos_side})
                        self.open_positions.pop(f"live_{pos.ticket}", None)
                        self.open_positions.pop(str(pos.ticket), None)
                        self.ticket_to_position_id.pop(pos.ticket, None)
                except Exception as e:
                    import logging; logging.warning(f"close_all ticket={getattr(pos,'ticket','?')}: {e}")

        return closed

    def close_buy_positions(self, symbol: Optional[str] = None) -> List[dict]:
        return self.close_all_positions(symbol=symbol, side="BUY")

    def close_sell_positions(self, symbol: Optional[str] = None) -> List[dict]:
        return self.close_all_positions(symbol=symbol, side="SELL")

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: Optional[str] = None) -> List[Any]:
        from core.engine import Position
        if not self.ensure_connected():
            return []

        sym = symbol or self.symbol
        exness_symbol = self.get_exness_symbol(sym)

        self.purge_duplicate_mt5_orders()  # Fix #6: Removed duplicate call — was called twice, causing race-condition cancels
        self.purge_duplicate_mt5_positions()
        mt5_orders = self._fetch_live_orders(exness_symbol)
        active_order_tickets = set()
        if mt5_orders:
            for o in mt5_orders:
                if getattr(o, "magic", 0) == self.magic_number or getattr(self, "magic_number", None) is None:
                    active_order_tickets.add(o.ticket)
                    if o.ticket not in self.ticket_to_order_id:
                        ord_id = f"live_ord_{o.ticket}"
                        self.ticket_to_order_id[o.ticket] = ord_id
                        ord_type_val = getattr(o, "type", 2)
                        type_str = (
                            "BUY_LIMIT" if ord_type_val == 2 else
                            "SELL_LIMIT" if ord_type_val == 3 else
                            "BUY_STOP" if ord_type_val == 4 else
                            "SELL_STOP" if ord_type_val == 5 else
                            "ORDER"
                        )
                        ord_obj = self.OrderClass(
                            type=type_str,
                            trigger_price=float(getattr(o, "price_open", 0.0) or 0.0),
                            size=float(getattr(o, "volume_initial", 0.01) or 0.01),
                            timestamp=float(getattr(o, "time_setup", time.time()) or time.time())
                        )
                        ord_obj.order_id = ord_id
                        ord_obj.sl = float(getattr(o, "sl", 0.0) or 0.0)
                        ord_obj.tp = float(getattr(o, "tp", 0.0) or 0.0)
                        self.pending_orders[ord_id] = ord_obj

        if mt5_orders is not None:
            current_time = time.time()
            for ticket, oid in list(self.ticket_to_order_id.items()):
                if ticket not in active_order_tickets:
                    # Give pending orders a 5-second grace period to appear on MT5 to prevent instant wiping
                    p_ord = self.pending_orders.get(oid)
                    if p_ord and hasattr(p_ord, "timestamp"):
                        ts = p_ord.timestamp
                        ts_sec = ts / 1000.0 if ts > 1e11 else ts
                        if current_time - ts_sec < 5.0:
                            continue
                    self.pending_orders.pop(oid, None)
                    self.ticket_to_order_id.pop(ticket, None)

        mt5_positions = self._fetch_live_positions(exness_symbol)
        if not mt5_positions:
            all_poss = self._fetch_live_positions()
            if all_poss:
                clean_target = "XAU" if any(x in self.symbol.upper() for x in ["XAU", "GOLD"]) else ("PAXG" if "PAXG" in self.symbol.upper() else self.symbol.replace("USDT", "").replace("USDC", "").replace("USD", "").upper())
                mt5_positions = [p for p in all_poss if clean_target in str(p.symbol).upper()]

        active_pos_tickets = set()
        triggered_positions = []

        if mt5_positions:
            for p in mt5_positions:
                if getattr(p, "magic", 0) != self.magic_number and getattr(self, "magic_number", None) is not None:
                    continue
                active_pos_tickets.add(p.ticket)
                pid = self.ticket_to_position_id.get(p.ticket)

                cur_p_sl = float(getattr(p, "sl", 0.0) or 0.0)
                cur_p_tp = float(getattr(p, "tp", 0.0) or 0.0)

                if not pid:
                    p_type_val = getattr(p, "type", 0)
                    pos_type = "BUY" if (p_type_val == 0 or p_type_val == "BUY") else "SELL"
                    new_pos = Position(pos_type, float(p.price_open), float(p.volume), float(p.time))
                    new_pos.position_id = f"live_{p.ticket}"
                    new_pos.sl = cur_p_sl
                    new_pos.tp = cur_p_tp
                    new_pos.profit = float(getattr(p, "profit", 0.0) or 0.0)
                    self.ticket_to_position_id[p.ticket] = new_pos.position_id
                    self.open_positions[new_pos.position_id] = new_pos
                    triggered_positions.append(new_pos)
                else:
                    pos_obj = self.open_positions.get(pid)
                    if pos_obj:
                        pos_obj.sl = cur_p_sl
                        pos_obj.tp = cur_p_tp
                        pos_obj.profit = float(getattr(p, "profit", 0.0) or 0.0)

        if mt5_positions is not None:
            for ticket, pid in list(self.ticket_to_position_id.items()):
                if ticket not in active_pos_tickets:
                    self.open_positions.pop(pid, None)
                    self.ticket_to_position_id.pop(ticket, None)

        return triggered_positions

    def get_floating_pnl(self, current_price: float = 0.0) -> float:
        if not self.ensure_connected():
            return 0.0
        ex_s = self.get_exness_symbol(self.symbol) if hasattr(self, "get_exness_symbol") else self.symbol
        aliases = {ex_s.upper(), self.symbol.upper(), f"{ex_s}m".upper(), f"{ex_s}c".upper()}
        if any(x in self.symbol.upper() for x in ["PAXG", "XAU", "GOLD"]):
            aliases.update(["XAUUSD", "GOLD", "PAXGUSDT", "XAUUSDm", "XAUUSDc"])

        positions = self._fetch_live_positions()
        total_pnl = 0.0
        found_matching = False
        if positions:
            for p in positions:
                if getattr(p, "magic", 0) != self.magic_number and getattr(self, "magic_number", None) is not None:
                    continue
                p_sym = str(getattr(p, "symbol", "")).upper()
                if p_sym and any(a in p_sym or p_sym in a for a in aliases):
                    total_pnl += float(getattr(p, "profit", 0.0) or 0.0)
                    found_matching = True
        
        if not found_matching and hasattr(self, "open_positions") and self.open_positions:
            for p_obj in self.open_positions.values():
                total_pnl += float(getattr(p_obj, "profit", 0.0) or 0.0)

        return total_pnl

    def sync_history_from_mt5(self, days: int = 180, force: bool = False):
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
            deals = None
            if MT5_AVAILABLE and mt5 is not None:
                deals = mt5.history_deals_get(from_date, to_date)
            else:
                try:
                    import requests
                    bridge_port = os.getenv("WINE_BRIDGE_PORT", "8001")
                    r_h = requests.get(f"http://127.0.0.1:{bridge_port}/history?days={days}", timeout=2.0)
                    if r_h.status_code == 200:
                        d_data = r_h.json()
                        raw_deals = d_data.get("deals", [])
                        class BridgeDeal:
                            def __init__(self, item):
                                for k, v in item.items():
                                    setattr(self, k, v)
                        deals = [BridgeDeal(d_item) for d_item in raw_deals]
                except Exception as b_err:
                    print(f"Notice: Wine bridge history fetch: {b_err}")
            if deals:
                pos_entry_times = {d.position_id: float(d.time) for d in deals if getattr(d, "entry", 0) == 0}
                pos_entry_prices = {d.position_id: float(d.price) for d in deals if getattr(d, "entry", 0) == 0}
                pos_entry_types = {d.position_id: ("BUY" if getattr(d, "type", 0) == 0 else "SELL") for d in deals if getattr(d, "entry", 0) == 0}
                synced_trades = []
                synced_pnl = 0.0
                target_syms = {self.symbol.upper(), (exness_symbol or "").upper()}
                # Detect Cent account at broker level
                is_cent_account = False
                acc_info = getattr(self, "account_info", None)
                if acc_info:
                    curr = str(getattr(acc_info, "currency", "")).upper()
                    if curr in ["USC", "USX", "EUC", "GBPC"]:
                        is_cent_account = True

                for d in deals:
                    d_sym = str(getattr(d, "symbol", "")).upper()
                    d_magic = getattr(d, "magic", self.magic_number)
                    if d_magic != self.magic_number and d_magic != 0:
                        continue
                    if d_sym and (d_sym in target_syms or any(ts in d_sym or d_sym in ts for ts in target_syms if ts)):
                        if not is_cent_account and any(d_sym.endswith(s) for s in ["C", "MICRO"]):
                            is_cent_account = True
                        cent_mult = 100.0 if is_cent_account else 1.0

                        raw_pnl = float(getattr(d, "profit", 0.0)) + float(getattr(d, "swap", 0.0)) + float(getattr(d, "commission", 0.0))
                        pnl = raw_pnl / cent_mult
                        # Only process OUT (1) or INOUT (2) deals as closed trades.
                        # Do NOT process IN (0) deals, even if they have upfront commission.
                        if getattr(d, "entry", 0) in (1, 2):
                            ex_sec = float(d.time / 1000.0) if d.time > 1e11 else float(d.time)
                            raw_e = pos_entry_times.get(d.position_id, None)
                            if raw_e is not None:
                                raw_sec = float(raw_e / 1000.0) if raw_e > 1e11 else float(raw_e)
                                e_sec = min(raw_sec, ex_sec - 1.0)
                            else:
                                e_sec = ex_sec - 15.0
                            
                            en_price = pos_entry_prices.get(d.position_id, float(d.price))
                            ex_price = float(d.price)
                            
                            # In MT5: IN deal type 0 = BUY, 1 = SELL. OUT deal type 1 = closed BUY, 0 = closed SELL.
                            # Use stored entry type, fallback to inverted OUT deal type.
                            trade_type = pos_entry_types.get(
                                d.position_id,
                                "BUY" if getattr(d, "type", 0) == 1 else "SELL"
                            )
                            
                            # Use MT5 deal reason code to label exit correctly:
                            # reason=5 → broker TP hit, reason=4 → broker SL hit,
                            # reason=0/1/2/3 → manual/bot/expert close
                            deal_reason = getattr(d, "reason", -1)
                            if deal_reason == 4:
                                exit_r = "TRAILING_SL" if pnl > 0 else "STOP_LOSS"
                            elif deal_reason == 5:
                                exit_r = "TARGET_PROFIT"
                            elif deal_reason in (0, 1, 2, 3):
                                # If the bot closed it, don't falsely label it TARGET_PROFIT just because pnl > 0
                                exit_r = "PARTIAL_TP" if pnl > 0 else "BOT_CLOSE"
                            else:
                                exit_r = "STOP_LOSS" if pnl < 0 else "CLOSED"
                            
                            t_record = {
                                "position_id": f"deal_{d.ticket}",
                                "type": trade_type,
                                "entry_price": en_price,
                                "deploy_price": en_price,
                                "exit_price": ex_price,
                                "size": float(d.volume) / cent_mult,
                                "fills_count": max(1, int(round((float(d.volume) / cent_mult) / 0.01))) if any(x in d_sym for x in ["XAU", "GOLD", "PAXG"]) else 1,
                                "pnl": pnl,
                                "entry_time": e_sec,
                                "start_time": e_sec,
                                "exit_time": ex_sec,
                                "timestamp": ex_sec,
                                "duration": max(1, int(ex_sec - e_sec)),
                                "commission": float(getattr(d, "commission", 0.0)),
                                "exit_reason": exit_r
                            }

                            synced_trades.append(t_record)
                            synced_pnl += pnl
                if synced_trades:
                    # Merge by position_id — don't overwrite session-added trades
                    existing_ids = {t.get("position_id") for t in self.closed_trades}
                    for t in synced_trades:
                        if t.get("position_id") not in existing_ids:
                            self.closed_trades.append(t)
                    if len(self.closed_trades) > 500:
                        self.closed_trades = self.closed_trades[-500:]
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
        self.pending_orders: Dict[str, Any] = {}
        self.open_positions: Dict[str, Any] = {}
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

    def place_order(self, order_type: str, price: float, size: float, timestamp: float, tp: float = 0.0, sl: float = 0.0) -> Any:
        from core.engine import Order
        order_id = f"sim_{int(time.time() * 1000)}_{len(self.pending_orders)+1}"
        order = Order(order_type, price, size, timestamp)
        order.order_id = order_id
        order.tp = tp
        order.sl = sl
        self.pending_orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> Any:
        return self.pending_orders.pop(order_id, None)

    def cancel_all_orders(self, symbol: Optional[str] = None):
        if symbol:
            to_remove = [oid for oid, ord_obj in list(self.pending_orders.items()) if getattr(ord_obj, "symbol", symbol) == symbol]
            for oid in to_remove:
                self.pending_orders.pop(oid, None)
        else:
            self.pending_orders.clear()

    def purge_duplicate_mt5_orders(self) -> int:
        return 0

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

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, symbol: Optional[str] = None) -> List[Any]:
        from core.engine import Position
        triggered = []
        for order_id, order in list(self.pending_orders.items()):
            is_trig = False
            if order.type == "BUY_STOP" and current_price >= order.trigger_price:
                is_trig = True
                pos_type = "BUY"
            elif order.type == "BUY_LIMIT" and current_price <= order.trigger_price:
                is_trig = True
                pos_type = "BUY"
            elif order.type == "SELL_STOP" and current_price <= order.trigger_price:
                is_trig = True
                pos_type = "SELL"
            elif order.type == "SELL_LIMIT" and current_price >= order.trigger_price:
                is_trig = True
                pos_type = "SELL"

            if is_trig:
                self.pending_orders.pop(order_id, None)
                pos = Position(pos_type, order.trigger_price, order.size, timestamp)
                pos.tp = float(getattr(order, "tp", 0.0) or 0.0)  # Transfer TP from order
                pos.sl = float(getattr(order, "sl", 0.0) or 0.0)  # Transfer SL from order
                self.open_positions[pos.position_id] = pos
                triggered.append(pos)

        # Software-side TP/SL enforcement for simulated broker
        for pid, pos in list(self.open_positions.items()):
            pos_tp = float(getattr(pos, "tp", 0.0) or 0.0)
            pos_sl = float(getattr(pos, "sl", 0.0) or 0.0)
            pos_type_str = str(getattr(pos, "type", "")).upper()
            if "BUY" in pos_type_str:
                if pos_tp > 0 and current_price >= pos_tp:
                    self.close_position(pid, current_price, timestamp)
                elif pos_sl > 0 and current_price <= pos_sl:
                    self.close_position(pid, current_price, timestamp)
            elif "SELL" in pos_type_str:
                if pos_tp > 0 and current_price <= pos_tp:
                    self.close_position(pid, current_price, timestamp)
                elif pos_sl > 0 and current_price >= pos_sl:
                    self.close_position(pid, current_price, timestamp)

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
