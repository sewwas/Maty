import paramiko
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    
    # 1. Query /account and /terminal_info
    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8001/account")
    print("=== ACCOUNT 8001 ===")
    print(stdout.read().decode("utf-8", errors="replace"))

    # 2. Check symbol info for XAUUSD / PAXGUSDT
    stdin, stdout, stderr = ssh.exec_command("curl -s 'http://127.0.0.1:8001/symbol_info?symbol=XAUUSD'")
    print("=== SYMBOL INFO (XAUUSD) ===")
    print(stdout.read().decode("utf-8", errors="replace"))

    # 3. Check start_bridges.log
    stdin, stdout, stderr = ssh.exec_command("tail -n 60 /root/Maty/start_bridges.log 2>/dev/null || true")
    print("=== START BRIDGES LOG (Last 60 lines) ===")
    print(stdout.read().decode("utf-8", errors="replace"))

    # 4. Check streamlit 8501 log
    stdin, stdout, stderr = ssh.exec_command("tail -n 60 /root/Maty/streamlit_8501.log 2>/dev/null || true")
    print("=== STREAMLIT 8501 LOG (Last 60 lines) ===")
    print(stdout.read().decode("utf-8", errors="replace"))

    # 5. Check pending orders and open positions from MT5
    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8001/positions; echo ''; curl -s http://127.0.0.1:8001/orders")
    print("=== MT5 OPEN POSITIONS & PENDING ORDERS ===")
    print(stdout.read().decode("utf-8", errors="replace"))

finally:
    ssh.close()
