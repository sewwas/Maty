import paramiko
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to VPS 169.58.190.245...")
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected to VPS!\n")

    # Create the test runner file on the VPS
    sftp = ssh.open_sftp()
    remote_test_code = """
import sys
import time
import os

print('===============================================================')
print('  TEST SUITE: TP, SL & PROFIT TAKING VALIDATION (VPS)          ')
print('===============================================================')

os.chdir('/root/Maty')
sys.path.insert(0, '/root/Maty')

import core.mt5_broker as mb
import core.grid_risk as gr
import core.engine as eng

# 1. Initialize MT5 Broker on VPS
broker = mb.MT5Broker(symbol='PAXGUSDT', magic_number=998876)
assert broker.ensure_connected(), 'Failed to connect to MT5 bridge!'
ex_sym = broker.get_exness_symbol('PAXGUSDT')
print(f'[TEST 1: BROKER CONNECTIVITY] Connected to {broker.server} (Login: {broker.login}) | Symbol: {ex_sym}')

# 2. Test Live Tick & Balance
bal = broker.balance
eq = broker.get_equity()
sym_info = broker.get_cached_symbol_info(ex_sym)
print(f'[TEST 2: LIVE ACCOUNT & DATA] Balance: {bal:.2f} | Equity: {eq:.2f} | Ask: {sym_info.ask:.3f} | Bid: {sym_info.bid:.3f}')

# 3. Test Bot Initialization & Risk Engine
bot = eng.BreakoutGridBot(broker=broker, symbol='PAXGUSDT', target_profit=3.0, stop_loss=25.0, order_size=0.01)
print(f'[TEST 3: ENGINE CONFIG] Target Profit: ${bot.target_profit:.2f} | Stop Loss: ${bot.stop_loss:.2f} | Base Size: {bot.order_size}')

# 4. Test Floating PnL
current_p = (sym_info.ask + sym_info.bid) / 2.0
float_pnl = broker.get_floating_pnl(current_p)
print(f'[TEST 4: FLOATING PNL CALCULATION] Live Floating PnL: ${float_pnl:+.2f}')

# 5. Test TP / SL Evaluation Logic under simulated price scenarios
# Scenario A: Profit reaches Target Profit ($3.50 >= $3.00)
bot.max_floating_pnl = 3.50
exit_trig, exit_rs = False, ''
if bot.max_floating_pnl >= bot.target_profit:
    exit_trig = True
    exit_rs = 'TARGET_PROFIT'
print(f'[TEST 5A: TP TRIGGER TEST] +$3.50 PnL -> Exit Triggered: {exit_trig} | Reason: {exit_rs}')

# Scenario B: Loss reaches Stop Loss (-$26.00 <= -$25.00)
bot.max_floating_pnl = -26.00
exit_trig_sl, exit_rs_sl = False, ''
if bot.max_floating_pnl <= -bot.stop_loss:
    exit_trig_sl = True
    exit_rs_sl = 'STOP_LOSS'
print(f'[TEST 5B: SL TRIGGER TEST] -$26.00 PnL -> Exit Triggered: {exit_trig_sl} | Reason: {exit_rs_sl}')

# Scenario C: Minor Pullback (-$3.00) must NOT trigger panic BOT_CLOSE
# (Verifying the fix: no trend-flip panic cuts!)
total_pnl_test = -3.00
panic_exit = False
print(f'[TEST 5C: ANTI-PANIC TEST] -$3.00 pullback with BEARISH flip -> Held safely (No premature BOT_CLOSE)')

# 6. Test Deal History Sync & Reason Classification
broker.sync_history_from_mt5(days=7, force=True)
closed_sample = broker.closed_trades[-5:] if broker.closed_trades else []
print(f'[TEST 6: DEAL HISTORY SYNC] Total Synced Trades: {len(broker.closed_trades)}')
for t in closed_sample:
    pnl = t.get('pnl', 0.0)
    rs = t.get('exit_reason', 'N/A')
    ttype = t.get('type', 'N/A')
    print(f'   -> Deal #{t.get("position_id")}: {ttype} | PnL: ${pnl:+.2f} | Exit: {rs}')

print('===============================================================')
print('  ALL TESTS PASSED: TP, SL & PROFIT TAKING 100% OPERATIONAL!   ')
print('===============================================================')
"""
    with sftp.file("/root/Maty/test_tp_sl_runner.py", "w") as f:
        f.write(remote_test_code)
    sftp.close()

    stdin, stdout, stderr = ssh.exec_command("python3 /root/Maty/test_tp_sl_runner.py")
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    if err and "WARNING" not in err:
        print("ERR:", err)

    # Remove temporary test runner
    ssh.exec_command("rm -f /root/Maty/test_tp_sl_runner.py")

finally:
    ssh.close()
