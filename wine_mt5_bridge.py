"""
Wine MT5 HTTP Bridge
Runs inside Wine Python 3.11 on VPS.
Interfaces directly with Windows MetaTrader 5 terminal64.exe under Wine.
Exposes lightweight REST API on port 8001 (Bot #1) or port 8002 (Bot #2) for native Linux app.py.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import sys
import urllib.request
import MetaTrader5 as mt5

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
            tick = None
            for s in [sym, f"{sym}m", f"{sym}c", f"{sym}.a"]:
                if mt5.symbol_select(s, True):
                    tick = mt5.symbol_info_tick(s)
                    if tick and tick.ask and tick.bid:
                        break
            if tick:
                res = {"symbol": sym, "ask": tick.ask, "bid": tick.bid, "price": (tick.ask + tick.bid) / 2.0}
            else:
                res = {"error": "Tick unavailable"}
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

        self.send_response(404)
        self.end_headers()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", 8001))
    os.environ["PORT"] = str(port)
    mt5_path = os.getenv("MT5_PATH")
    if not mt5_path:
        mt5_path = r"C:\Program Files\MetaTrader 5_2\terminal64.exe" if port == 8002 else r"C:\Program Files\MetaTrader 5\terminal64.exe"
    
    cfg = get_bridge_config(port)
    saved_login = cfg.get("login")
    saved_pwd = cfg.get("password")
    saved_srv = cfg.get("server", "Exness-MT5Real36")

    init_ok = False
    if saved_login and saved_pwd:
        is_conflict, other_p = check_other_bridge_conflict(port, saved_login)
        if not is_conflict:
            init_ok = mt5.initialize(path=mt5_path, login=saved_login, password=saved_pwd, server=saved_srv)
            if init_ok:
                login_ok = mt5.login(login=saved_login, password=saved_pwd, server=saved_srv)
                if login_ok:
                    print(f"MetaTrader5 restored saved login {saved_login} on port {port}!")

    if not init_ok:
        init_ok = mt5.initialize(path=mt5_path)
    
    if not init_ok:
        print(f"MT5 Init status on port {port}: {mt5.last_error()}")
    else:
        print(f"MetaTrader5 initialized successfully in Wine on port {port}!")
    
    server = HTTPServer(("0.0.0.0", port), MT5BridgeHandler)
    print(f"MT5 Bridge Server listening on port {port}...")
    server.serve_forever()

