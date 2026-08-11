import paramiko
import json
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected to VPS!\n")

    # 1. Check live positions on port 8001
    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8001/positions")
    pos_data = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")
    print("=== LIVE OPEN POSITIONS (8001) ===")
    print(f"Total Open Positions: {len(pos_data.get('positions', []))}")
    for p in pos_data.get("positions", []):
        print(f"  -> Ticket #{p.get('ticket')}: {p.get('symbol')} {'BUY' if p.get('type')==0 else 'SELL'} {p.get('volume')} lot @ {p.get('price_open')} | Current: {p.get('price_current')} | PnL: ${p.get('profit')}")

    # 2. Check live pending orders on port 8001
    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8001/orders")
    ord_data = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")
    print("\n=== LIVE PENDING ORDERS / TRAPS (8001) ===")
    orders = ord_data.get("orders", [])
    print(f"Total Pending Traps: {len(orders)}")
    type_map = {2: "BUY_LIMIT", 3: "SELL_LIMIT", 4: "BUY_STOP", 5: "SELL_STOP"}
    for o in orders:
        ot = type_map.get(o.get('type'), f"TYPE_{o.get('type')}")
        print(f"  -> Ticket #{o.get('ticket')}: {o.get('symbol')} {ot} {o.get('volume_initial')} lot @ trigger ${o.get('price_open')} | TP: ${o.get('tp')} | SL: ${o.get('sl')}")

    # 3. Check live price from symbol_info
    stdin, stdout, stderr = ssh.exec_command("curl -s 'http://127.0.0.1:8001/symbol_info?symbol=XAUUSD'")
    sym_info = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")
    print(f"\n=== CURRENT GOLD/PAXG PRICE ===")
    print(f"Ask: ${sym_info.get('ask')} | Bid: ${sym_info.get('bid')} | Spread: {round(float(sym_info.get('ask',0))-float(sym_info.get('bid',0)), 3)}")

    # 4. Check bot state file in /root/Maty
    stdin, stdout, stderr = ssh.exec_command("python3 -c \"import json; f=open('/root/Maty/bot_state_instance_1.json'); d=json.load(f); f.close(); mkts=d.get('markets',{}); print('Active Markets in Bot 1:', {k: {'running': v.get('running'), 'last_price': v.get('last_price'), 'open_positions': len(v.get('open_positions',{}))} for k,v in mkts.items()})\" 2>/dev/null || echo 'State check fallback'")
    print("\n=== BOT STATE (INSTANCE 1) ===")
    print(stdout.read().decode("utf-8", errors="replace"))

finally:
    ssh.close()
