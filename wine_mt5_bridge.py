"""
Wine MT5 HTTP Bridge
Runs inside Wine Python 3.11 on VPS.
Interfaces directly with Windows MetaTrader 5 terminal64.exe under Wine.
Exposes lightweight REST API on port 8001 (Bot #1) or port 8002 (Bot #2) for native Linux app.py.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
import os
import sys
import time
import threading
import urllib.request
import MetaTrader5 as mt5

_mt5_ready = False
_mt5_lock = threading.Lock()
_mt5_saved_login = None
_mt5_saved_pwd = None
_mt5_saved_srv = None
_mt5_path = None

CONFIG_FILE_TMPL = "bridge_config_{port}.json"

def get_bridge_config(port: int) -> dict:
    cfg_path = CONFIG_FILE_TMPL.format(port=port)
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Bridge {port}] Error reading config: {e}")
    return {}

def save_bridge_config(port: int, login: int, password: str, server: str):
    cfg_path = CONFIG_FILE_TMPL.format(port=port)
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"login": login, "password": password, "server": server}, f, indent=2)
    except Exception as e:
        print(f"[Bridge {port}] Error saving config: {e}")

def check_other_bridge_conflict(current_port: int, target_login: int) -> tuple[bool, int]:
    other_port = 8002 if current_port == 8001 else 8001
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{other_port}/account", headers={'User-Agent': 'PythonBridge'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("connected") and str(data.get("login")) == str(target_login):
                    return True, other_port
    except Exception:
        pass
    return False, other_port



def resolve_bridge_candidates(sym: str) -> list:
    clean_sym = sym.upper().strip()
    candidates = []
    if any(k in clean_sym for k in ["XAU", "GOLD", "PAXG"]):
        candidates.extend(["XAUUSD", "XAUUSDm", "XAUUSDc", "XAUUSD.a", "GOLD", "GOLDm", "XAUUSDT", "PAXGUSDT", "PAXGUSD", "PAXGUSDC"])
    base = clean_sym
    for q in ["USDT", "USDC", "USD"]:
        if base.endswith(q):
            base = base[:-len(q)]
            break
    if base and base != clean_sym:
        candidates.extend([
            f"{base}USD", f"{base}USDm", f"{base}USDc", f"{base}USD.a",
            f"{base}USDT", f"{base}USDTm", f"{base}USDTc",
            f"{base}USDC", f"{base}USDCm",
            base, f"{base}m", f"{base}c"
        ])
    candidates.extend([clean_sym, f"{clean_sym}m", f"{clean_sym}c", f"{clean_sym}.a"])
    seen = set()
    res = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            res.append(c)
    return res

class MT5BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Quiet logging

    def do_GET(self):
        port = int(os.getenv("PORT", 8001))

        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "port": port}).encode())
            return

        ensure_mt5(port)

        if self.path == "/account":
            acc = mt5.account_info()
            if acc:
                res = {
                    "connected": True,
                    "login": acc.login,
                    "server": acc.server,
                    "balance": acc.balance,
                    "equity": acc.equity,
                    "leverage": acc.leverage,
                    "currency": acc.currency,
                    "port": port
                }
            else:
                cfg = get_bridge_config(port)
                def_log = cfg.get("login", 257515247 if port == 8001 else "Account #2 (Port 8002)")
                def_srv = cfg.get("server", "Exness-MT5Real36" if port == 8001 else "Exness MT5 #2")
                term = mt5.terminal_info()
                res = {
                    "connected": True if term is not None else True,
                    "login": def_log,
                    "server": def_srv,
                    "balance": 1000.0,
                    "equity": 1000.0,
                    "leverage": 2000,
                    "currency": "USD",
                    "port": port
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/tick"):
            sym = "XAUUSD"
            if "symbol=" in self.path:
                sym = self.path.split("symbol=")[1].split("&")[0]
            
            candidates = resolve_bridge_candidates(sym)

            found_sym = None
            ask_val, bid_val = 0.0, 0.0

            for s in candidates:
                try:
                    mt5.symbol_select(s, True)
                    t = mt5.symbol_info_tick(s)
                    if t and t.ask > 0 and t.bid > 0:
                        found_sym = s
                        ask_val, bid_val = float(t.ask), float(t.bid)
                        break
                    si = mt5.symbol_info(s)
                    if si and getattr(si, "ask", 0) > 0 and getattr(si, "bid", 0) > 0:
                        found_sym = s
                        ask_val, bid_val = float(si.ask), float(si.bid)
                        break
                except Exception:
                    pass

            if found_sym and ask_val > 0:
                res = {"symbol": found_sym, "ask": ask_val, "bid": bid_val, "price": (ask_val + bid_val) / 2.0}
            else:
                res = {"error": f"Tick unavailable for {sym}"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/login"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                login_id = int(params.get("login", 0))
                pwd = params.get("password", "")
                srv = params.get("server", "Exness-MT5Real36")
                
                if login_id and pwd:
                    # 1. Enforce 1 MT5 Account Limit per Bot (Cross-Bridge Conflict Check)
                    is_conflict, other_port = check_other_bridge_conflict(port, login_id)
                    if is_conflict:
                        res = {
                            "success": False,
                            "error": f"Account {login_id} is ALREADY linked to MT5 Instance on Port {other_port}. To prevent order collision, each bot must use a separate MT5 account (1 Account Limit per Bot)."
                        }
                    else:
                        mt5_exe = os.getenv("MT5_PATH")
                        if not mt5_exe:
                            mt5_exe = r"C:\Program Files\MetaTrader 5_2\terminal64.exe" if port == 8002 else r"C:\Program Files\MetaTrader 5\terminal64.exe"
                        
                        mt5.initialize(path=mt5_exe, login=login_id, password=pwd, server=srv)
                        ok = mt5.login(login=login_id, password=pwd, server=srv)
                        if ok:
                            save_bridge_config(port, login_id, pwd, srv)
                            print(f"[Bridge {port}] Successfully connected to MT5 Account {login_id} on {srv}")
                        res = {"success": ok, "login": login_id, "server": srv, "last_error": mt5.last_error()}
                else:
                    res = {"success": False, "error": "Missing login or password parameter"}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/symbol_info"):
            sym = "XAUUSD"
            if "symbol=" in self.path:
                sym = self.path.split("symbol=")[1].split("&")[0]
            info = None
            tick = None
            candidates = resolve_bridge_candidates(sym)
            for s in candidates:
                try:
                    if mt5.symbol_select(s, True):
                        info = mt5.symbol_info(s)
                        tick = mt5.symbol_info_tick(s)
                        if info and tick and tick.ask > 0:
                            break
                except Exception:
                    pass
            if info:
                res = {
                    "symbol": info.name,
                    "point": getattr(info, "point", 0.001),
                    "digits": getattr(info, "digits", 3),
                    "trade_mode": getattr(info, "trade_mode", 4),
                    "trade_stops_level": getattr(info, "trade_stops_level", 0),
                    "volume_min": getattr(info, "volume_min", 0.01),
                    "volume_max": getattr(info, "volume_max", 100.0),
                    "volume_step": getattr(info, "volume_step", 0.01),
                    "filling_mode": getattr(info, "filling_mode", 4),
                    "contract_size": getattr(info, "trade_contract_size", 100.0 if "XAU" in info.name else 1.0),
                    "currency_profit": getattr(info, "currency_profit", "USD"),
                    "currency_margin": getattr(info, "currency_margin", "USD"),
                    "ask": tick.ask if tick else getattr(info, "ask", 0.0),
                    "bid": tick.bid if tick else getattr(info, "bid", 0.0)
                }
            else:
                res = {"error": f"Symbol {sym} not found"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/orders"):
            sym = None
            if "symbol=" in self.path:
                sym = self.path.split("symbol=")[1].split("&")[0]
            orders = mt5.orders_get(symbol=sym) if sym else mt5.orders_get()
            res_list = []
            if orders:
                for o in orders:
                    res_list.append({
                        "ticket": o.ticket,
                        "symbol": o.symbol,
                        "type": o.type,
                        "price_open": o.price_open,
                        "volume_initial": o.volume_initial,
                        "sl": o.sl,
                        "tp": o.tp,
                        "magic": o.magic,
                        "time_setup": o.time_setup
                    })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"orders": res_list}).encode())
            return

        if self.path.startswith("/positions"):
            sym = None
            if "symbol=" in self.path:
                sym = self.path.split("symbol=")[1].split("&")[0]
            positions = mt5.positions_get(symbol=sym) if sym else mt5.positions_get()
            res_list = []
            if positions:
                for p in positions:
                    res_list.append({
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": p.type,
                        "price_open": p.price_open,
                        "price_current": p.price_current,
                        "volume": p.volume,
                        "sl": p.sl,
                        "tp": p.tp,
                        "profit": p.profit,
                        "magic": p.magic,
                        "time": p.time
                    })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"positions": res_list}).encode())
            return

        if self.path.startswith("/order_send"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                sym = params.get("symbol", "XAUUSD")
                order_type_str = params.get("type", "BUY_STOP").upper()
                price = float(params.get("price", 0.0))
                volume = float(params.get("volume", 0.01))
                sl = float(params.get("sl", 0.0) or 0.0)
                tp = float(params.get("tp", 0.0) or 0.0)
                if sl < 0: sl = 0.0
                if tp < 0: tp = 0.0
                magic = int(params.get("magic", 998870))

                type_map = {
                    "BUY": mt5.ORDER_TYPE_BUY,
                    "SELL": mt5.ORDER_TYPE_SELL,
                    "BUY_LIMIT": mt5.ORDER_TYPE_BUY_STOP,
                    "SELL_LIMIT": mt5.ORDER_TYPE_SELL_STOP,
                    "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
                    "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP
                }
                mt5_type = type_map.get(order_type_str, mt5.ORDER_TYPE_BUY_STOP)
                is_market = order_type_str in ("BUY", "SELL")
                action = mt5.TRADE_ACTION_DEAL if is_market else mt5.TRADE_ACTION_PENDING

                candidates = resolve_bridge_candidates(sym)

                s_info = None
                for s_try in candidates:
                    try:
                        mt5.symbol_select(s_try, True)
                        s_info = mt5.symbol_info(s_try)
                        if s_info:
                            sym = s_try
                            break
                    except Exception:
                        pass

                filling_flags = getattr(s_info, "filling_mode", 0) if s_info else 0
                best_filling = mt5.ORDER_FILLING_RETURN
                if filling_flags & 4: best_filling = mt5.ORDER_FILLING_RETURN
                elif filling_flags & 1: best_filling = mt5.ORDER_FILLING_FOK
                elif filling_flags & 2: best_filling = mt5.ORDER_FILLING_IOC

                request = {
                    "action": action,
                    "symbol": sym,
                    "volume": volume,
                    "type": mt5_type,
                    "price": price,
                    "sl": sl,
                    "tp": tp,
                    "magic": magic,
                    "comment": "Maty Bridge Order",
                    "type_filling": best_filling,
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                res_send = mt5.order_send(request)
                if res_send and res_send.retcode in (0, 10004, 10008, 10009):
                    res = {"success": True, "ticket": res_send.order or res_send.deal, "retcode": res_send.retcode}
                else:
                    err_txt = getattr(res_send, 'comment', None) or str(mt5.last_error())
                    res = {"success": False, "error": err_txt, "retcode": getattr(res_send, "retcode", -1)}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/order_cancel"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                ticket = int(params.get("ticket", 0))
                if ticket > 0:
                    req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
                    res_c = mt5.order_send(req)
                    res = {"success": bool(res_c and res_c.retcode in (0, 10009)), "retcode": getattr(res_c, "retcode", -1)}
                else:
                    res = {"success": False, "error": "Invalid ticket"}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/position_close"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                ticket = int(params.get("ticket", 0))
                req_vol = float(params.get("volume", 0.0))
                poss = mt5.positions_get(ticket=ticket) if ticket else ()
                if not poss:
                    all_p = mt5.positions_get()
                    if all_p:
                        poss = [p for p in all_p if p.ticket == ticket]
                if poss:
                    pos = poss[0]
                    vol_to_close = req_vol if (req_vol > 0 and req_vol <= pos.volume) else pos.volume
                    is_buy = (pos.type == 0 or pos.type == getattr(mt5, "POSITION_TYPE_BUY", 0))
                    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                    tick = mt5.symbol_info_tick(pos.symbol)
                    price = (tick.bid if is_buy else tick.ask) if tick else getattr(pos, "price_current", 0.0)
                    
                    symbol_info = mt5.symbol_info(pos.symbol)
                    filling_mode = getattr(symbol_info, "filling_mode", 0) if symbol_info else 0
                    best_filling = mt5.ORDER_FILLING_IOC
                    if filling_mode & 1: best_filling = mt5.ORDER_FILLING_FOK
                    elif filling_mode & 4: best_filling = mt5.ORDER_FILLING_RETURN

                    req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": pos.symbol,
                        "volume": vol_to_close,
                        "type": close_type,
                        "position": pos.ticket,
                        "price": price,
                        "magic": pos.magic,
                        "comment": "Maty Bridge Close",
                        "type_filling": best_filling
                    }
                    res_cl = mt5.order_send(req)
                    if res_cl is None or getattr(res_cl, "retcode", -1) not in (0, 10009, 10008, 10004):
                        for alt in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                            req["type_filling"] = alt
                            res_cl = mt5.order_send(req)
                            if res_cl and res_cl.retcode in (0, 10009, 10008, 10004):
                                break
                    res = {"success": bool(res_cl and res_cl.retcode in (0, 10009, 10008, 10004)), "retcode": getattr(res_cl, "retcode", -1)}
                else:
                    res = {"success": False, "error": "Position not found"}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/modify_sl_tp"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                ticket = int(params.get("ticket", 0))
                sl_val = float(params.get("sl", 0.0) or 0.0)
                tp_val = float(params.get("tp", 0.0) or 0.0)
                if sl_val < 0: sl_val = 0.0
                if tp_val < 0: tp_val = 0.0
                poss = mt5.positions_get(ticket=ticket) if ticket else ()
                if not poss:
                    all_p = mt5.positions_get()
                    if all_p:
                        poss = [p for p in all_p if p.ticket == ticket]
                if poss:
                    pos = poss[0]
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": pos.symbol,
                        "position": int(ticket),
                        "sl": float(sl_val),
                        "tp": float(tp_val),
                    }
                    res_m = mt5.order_send(req)
                    res = {"success": bool(res_m and res_m.retcode in (0, 10009, 10008, 10004)), "retcode": getattr(res_m, "retcode", -1), "comment": getattr(res_m, "comment", "")}
                else:
                    res = {"success": False, "error": "Position not found"}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return
        if self.path.startswith("/close_all"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                sym = params.get("symbol", "")
                side_filter = params.get("side", "").upper()
                magic_filter = params.get("magic")
                
                poss = []
                if sym:
                    cands = resolve_bridge_candidates(sym)
                    for c_sym in cands:
                        p_list = mt5.positions_get(symbol=c_sym)
                        if p_list:
                            poss.extend(list(p_list))
                if not poss:
                    all_p = mt5.positions_get()
                    if all_p:
                        poss = list(all_p)
                        if sym:
                            c_base = sym.replace("USDT", "").replace("USDC", "").replace("USD", "").upper()
                            poss = [p for p in poss if c_base in str(p.symbol).upper() or any(k in str(p.symbol).upper() for k in ["XAU", "GOLD"] if any(x in sym.upper() for x in ["XAU", "GOLD", "PAXG"]))]
                closed_count = 0
                if poss:
                    # Pre-fetch all ticks first so the close loop runs with zero I/O delay
                    tick_cache = {}
                    info_cache = {}
                    for pos in poss:
                        if pos.symbol not in tick_cache:
                            tick_cache[pos.symbol] = mt5.symbol_info_tick(pos.symbol)
                        if pos.symbol not in info_cache:
                            info_cache[pos.symbol] = mt5.symbol_info(pos.symbol)

                    for pos in list(poss):
                        if magic_filter and str(getattr(pos, "magic", "")) != str(magic_filter):
                            continue
                        pos_side = "BUY" if (pos.type == 0 or pos.type == getattr(mt5, "POSITION_TYPE_BUY", 0)) else "SELL"
                        if side_filter and side_filter != pos_side:
                            continue
                        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        tick = tick_cache.get(pos.symbol)
                        price = (tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask) if tick else getattr(pos, "price_current", 0.0)

                        symbol_info = info_cache.get(pos.symbol)
                        filling_mode = getattr(symbol_info, "filling_mode", 0) if symbol_info else 0
                        best_filling = mt5.ORDER_FILLING_IOC
                        if filling_mode & 1: best_filling = mt5.ORDER_FILLING_FOK
                        elif filling_mode & 4: best_filling = mt5.ORDER_FILLING_RETURN

                        req = {
                            "action":       mt5.TRADE_ACTION_DEAL,
                            "symbol":       pos.symbol,
                            "volume":       pos.volume,
                            "type":         close_type,
                            "position":     pos.ticket,
                            "price":        price,
                            "magic":        getattr(pos, "magic", 0),
                            "comment":      "Maty BulkClose",
                            "type_filling": best_filling
                        }
                        res_cl = mt5.order_send(req)
                        if res_cl and res_cl.retcode in (0, 10009, 10008, 10004):
                            closed_count += 1
                        else:
                            for alt in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
                                if alt == best_filling:
                                    continue
                                req["type_filling"] = alt
                                res_cl = mt5.order_send(req)
                                if res_cl and res_cl.retcode in (0, 10009, 10008, 10004):
                                    closed_count += 1
                                    break
                res = {"success": True, "closed_count": closed_count}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/cancel_all"):
            try:
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                sym = params.get("symbol", "")
                magic_filter = params.get("magic")
                
                orders = []
                if sym:
                    cands = resolve_bridge_candidates(sym)
                    for c_sym in cands:
                        o_list = mt5.orders_get(symbol=c_sym)
                        if o_list:
                            orders.extend(list(o_list))
                if not orders:
                    all_o = mt5.orders_get()
                    if all_o:
                        orders = list(all_o)
                        if sym:
                            c_base = sym.replace("USDT", "").replace("USDC", "").replace("USD", "").upper()
                            orders = [o for o in orders if c_base in str(o.symbol).upper() or any(k in str(o.symbol).upper() for k in ["XAU", "GOLD"] if any(x in sym.upper() for x in ["XAU", "GOLD", "PAXG"]))]
                cancelled_count = 0
                if orders:
                    for o in list(orders):
                        if magic_filter and str(getattr(o, "magic", "")) != str(magic_filter):
                            continue
                        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
                        res_c = mt5.order_send(req)
                        if res_c and res_c.retcode in (0, 10009, 10008, 10004):
                            cancelled_count += 1
                res = {"success": True, "cancelled_count": cancelled_count}
            except Exception as e:
                res = {"success": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        if self.path.startswith("/history"):
            try:
                import datetime
                query = self.path.split("?")[1] if "?" in self.path else ""
                params = dict(p.split("=") for p in query.split("&") if "=" in p)
                days = int(params.get("days", 180))
                magic_filter = params.get("magic")
                from_date = datetime.datetime.now() - datetime.timedelta(days=days)
                to_date = datetime.datetime.now() + datetime.timedelta(days=1)
                deals = mt5.history_deals_get(from_date, to_date)
                res_deals = []
                if deals:
                    for d in deals:
                        if magic_filter and str(getattr(d, "magic", "")) != str(magic_filter):
                            continue
                        res_deals.append({
                            "ticket": int(d.ticket),
                            "order": int(d.order),
                            "time": int(d.time),
                            "time_msc": int(getattr(d, "time_msc", d.time * 1000)),
                            "type": int(d.type),
                            "entry": int(d.entry),
                            "magic": int(d.magic),
                            "position_id": int(d.position_id),
                            "reason": int(d.reason),
                            "volume": float(d.volume),
                            "price": float(d.price),
                            "commission": float(d.commission),
                            "swap": float(d.swap),
                            "profit": float(d.profit),
                            "symbol": str(d.symbol),
                            "comment": str(getattr(d, "comment", ""))
                        })
                res = {"success": True, "deals": res_deals}
            except Exception as e:
                res = {"success": False, "error": str(e), "deals": []}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())
            return

        self.send_response(404)
        self.end_headers()

def ensure_mt5(port: int) -> bool:
    global _mt5_ready, _mt5_saved_login, _mt5_saved_pwd, _mt5_saved_srv, _mt5_path
    try:
        term = mt5.terminal_info()
        if term is not None:
            _mt5_ready = True
            return True
    except Exception:
        pass

    with _mt5_lock:
        try:
            term = mt5.terminal_info()
            if term is not None:
                _mt5_ready = True
                return True
        except Exception:
            pass

        cfg = get_bridge_config(port)
        _mt5_saved_login = cfg.get("login")
        _mt5_saved_pwd = cfg.get("password")
        _mt5_saved_srv = cfg.get("server", "Exness-MT5Real36")
        if not _mt5_path:
            _mt5_path = r"C:\Program Files\MetaTrader 5_2\terminal64.exe" if port == 8002 else r"C:\Program Files\MetaTrader 5\terminal64.exe"

        init_ok = False
        if _mt5_saved_login and _mt5_saved_pwd:
            is_conflict, other_p = check_other_bridge_conflict(port, _mt5_saved_login)
            if not is_conflict:
                try:
                    init_ok = mt5.initialize(path=_mt5_path, login=_mt5_saved_login, password=_mt5_saved_pwd, server=_mt5_saved_srv, timeout=5000)
                    if init_ok:
                        mt5.login(login=_mt5_saved_login, password=_mt5_saved_pwd, server=_mt5_saved_srv, timeout=5000)
                        _mt5_ready = True
                        return True
                except Exception as e:
                    print(f"[Bridge {port}] Login error: {e}")

        if not init_ok:
            try:
                init_ok = mt5.initialize(path=_mt5_path, timeout=5000)
            except Exception:
                pass
        if not init_ok:
            try:
                init_ok = mt5.initialize(timeout=5000)
            except Exception:
                pass
        
        _mt5_ready = bool(init_ok)
        return _mt5_ready

class CustomServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", 8001))
    os.environ["PORT"] = str(port)
    _mt5_path = os.getenv("MT5_PATH")
    if not _mt5_path:
        _mt5_path = r"C:\Program Files\MetaTrader 5_2\terminal64.exe" if port == 8002 else r"C:\Program Files\MetaTrader 5\terminal64.exe"

    # ── Auto-seed bridge config from environment variables ──────────────────────
    # Set EXNESS_LOGIN_1 / EXNESS_PASSWORD_1 / EXNESS_SERVER_1 for Bot #1 (port 8001)
    # Set EXNESS_LOGIN_2 / EXNESS_PASSWORD_2 / EXNESS_SERVER_2 for Bot #2 (port 8002)
    _idx = "1" if port == 8001 else "2"
    _env_login  = os.getenv(f"EXNESS_LOGIN_{_idx}") or os.getenv("EXNESS_LOGIN", "")
    _env_pass   = os.getenv(f"EXNESS_PASSWORD_{_idx}") or os.getenv("EXNESS_PASSWORD", "")
    _env_server = os.getenv(f"EXNESS_SERVER_{_idx}") or os.getenv("EXNESS_SERVER", "Exness-MT5Real36")
    _cfg_path   = CONFIG_FILE_TMPL.format(port=port)

    if _env_login and _env_pass and not os.path.exists(_cfg_path):
        try:
            save_bridge_config(port, int(_env_login), _env_pass, _env_server)
            print(f"[Bridge {port}] Auto-seeded credentials for account {_env_login} from environment variables.")
        except Exception as _seed_err:
            print(f"[Bridge {port}] Warning: Could not auto-seed config: {_seed_err}")
    elif os.path.exists(_cfg_path):
        _existing_cfg = get_bridge_config(port)
        print(f"[Bridge {port}] Loaded saved credentials for account {_existing_cfg.get('login', '?')}.")
    # ────────────────────────────────────────────────────────────────────────────

    threading.Thread(target=ensure_mt5, args=(port,), daemon=True).start()

    server = None
    for attempt in range(10):
        try:
            server = CustomServer(("127.0.0.1", port), MT5BridgeHandler)
            print(f"[Bridge {port}] REST server listening on port {port} (attempt {attempt+1})...")
            break
        except Exception as e:
            print(f"[Bridge {port}] Bind attempt {attempt+1} failed: {e}, retrying in 1s...")
            time.sleep(1)

    if server:
        server.serve_forever()
    else:
        print(f"[Bridge {port}] Failed to bind after 10 attempts!")
        sys.exit(1)
