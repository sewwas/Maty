import paramiko
import json
import sys
import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

def audit_port(port):
    print(f"\n=================================================================")
    print(f"  🔍 AUDIT FOR BRIDGE PORT {port}")
    print(f"=================================================================")

    stdin, stdout, stderr = ssh.exec_command(f"curl -s http://127.0.0.1:{port}/account")
    acc_data = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")

    stdin, stdout, stderr = ssh.exec_command(f"curl -s http://127.0.0.1:{port}/positions")
    pos_data = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")

    stdin, stdout, stderr = ssh.exec_command(f"curl -s http://127.0.0.1:{port}/orders")
    ord_data = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")

    stdin, stdout, stderr = ssh.exec_command(f"curl -s 'http://127.0.0.1:{port}/history?days=90'")
    hist_data = json.loads(stdout.read().decode("utf-8", errors="replace") or "{}")
    deals = hist_data.get("deals", [])

    print(f"Account: #{acc_data.get('login')} @ {acc_data.get('server')}")
    print(f"Balance: {acc_data.get('balance')} {acc_data.get('currency')} | Equity: {acc_data.get('equity')} | Leverage: {acc_data.get('leverage')}")
    print(f"Live Open Positions: {len(pos_data.get('positions', []))} | Pending Orders: {len(ord_data.get('orders', []))}")
    print(f"Total History Deals: {len(deals)}")

    if not deals:
        print("-> No trading history found on this account.")
        return

    out_deals = [d for d in deals if d.get("entry") in (1, 2)]
    in_deals = {d.get("position_id"): d for d in deals if d.get("entry") == 0}

    total_profit, total_loss = 0.0, 0.0
    wins, losses = 0, 0
    by_symbol, by_reason = {}, {}
    trade_list = []

    for d in out_deals:
        profit = float(d.get("profit", 0.0)) + float(d.get("swap", 0.0)) + float(d.get("commission", 0.0))
        sym = d.get("symbol", "UNKNOWN")
        vol = float(d.get("volume", 0.0))
        ticket = d.get("ticket")
        pos_id = d.get("position_id")
        reason_code = d.get("reason", -1)
        time_ts = float(d.get("time", 0))
        if time_ts > 1e11: time_ts /= 1000.0
        time_str = datetime.datetime.fromtimestamp(time_ts).strftime('%Y-%m-%d %H:%M:%S') if time_ts else "N/A"

        in_d = in_deals.get(pos_id, {})
        entry_price = float(in_d.get("price", d.get("price", 0.0)))
        exit_price = float(d.get("price", 0.0))
        entry_type = "BUY" if in_d.get("type", 0) == 0 else ("SELL" if in_d.get("type", 1) == 1 else "UNKNOWN")

        reason_map = {0: "MANUAL/BOT_CLOSE", 1: "MOBILE", 2: "WEB", 3: "EXPERT_CLOSE", 4: "STOP_LOSS", 5: "TARGET_PROFIT", 6: "MARGIN_STOPOUT"}
        reason_desc = reason_map.get(reason_code, f"CODE_{reason_code}")
        if profit > 0 and reason_code in (0, 1, 2, 3): reason_desc = "TARGET_PROFIT"
        elif profit < 0 and reason_code in (0, 1, 2, 3): reason_desc = "BOT_CLOSE"

        if profit > 0:
            wins += 1
            total_profit += profit
        else:
            losses += 1
            total_loss += abs(profit)

        if sym not in by_symbol:
            by_symbol[sym] = {"wins": 0, "losses": 0, "pnl": 0.0, "volume": 0.0}
        by_symbol[sym]["pnl"] += profit
        by_symbol[sym]["volume"] += vol
        if profit > 0: by_symbol[sym]["wins"] += 1
        else: by_symbol[sym]["losses"] += 1

        by_reason[reason_desc] = by_reason.get(reason_desc, 0) + 1
        trade_list.append({
            "time": time_str, "ticket": ticket, "symbol": sym, "type": entry_type,
            "volume": vol, "entry_price": entry_price, "exit_price": exit_price,
            "pnl": profit, "reason": reason_desc
        })

    net_pnl = total_profit - total_loss
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 0.0

    print(f"\n📊 PERFORMANCE SUMMARY:")
    print(f"  • Total Trades:     {total_trades}")
    print(f"  • Wins / Losses:    {wins} Wins / {losses} Losses ({win_rate:.1f}% Win Rate)")
    print(f"  • Gross Profit:    +${total_profit:.2f}")
    print(f"  • Gross Loss:      -${total_loss:.2f}")
    print(f"  • Net Realized:     ${net_pnl:+.2f}")
    print(f"  • Profit Factor:    {profit_factor:.2f}")
    print(f"  • Avg Win:         +${(total_profit/wins if wins else 0):.2f}")
    print(f"  • Avg Loss:        -${(total_loss/losses if losses else 0):.2f}")

    print(f"\n🏷️ EXIT REASONS:")
    for r_name, count in by_reason.items():
        print(f"  • {r_name}: {count} trades")

    print(f"\n🔍 RECENT 25 TRADES (Chronological):")
    for idx, t in enumerate(trade_list[-25:]):
        print(f"  #{idx+1:02d} | {t['time']} | {t['symbol']} | {t['type']:<4} {t['volume']:>5.2f} lot | {t['entry_price']:>9.3f} -> {t['exit_price']:>9.3f} | PnL: {t['pnl']:>+7.2f} | {t['reason']}")

try:
    print("Connecting to VPS 169.58.190.245...")
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    audit_port(8001)
    audit_port(8002)
finally:
    ssh.close()
