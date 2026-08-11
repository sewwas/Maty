import paramiko
import json
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)

    # Check bridge 8001
    stdin, stdout, stderr = ssh.exec_command("curl -s 'http://127.0.0.1:8001/history?days=365'")
    d1 = json.loads(stdout.read().decode('utf-8', errors='replace') or '{}')
    print(f"Account 160142171 (Port 8001): {len(d1.get('deals', []))} total deals")

    # Check bridge 8002
    stdin, stdout, stderr = ssh.exec_command("curl -s 'http://127.0.0.1:8002/history?days=365'")
    d2 = json.loads(stdout.read().decode('utf-8', errors='replace') or '{}')
    deals_8002 = d2.get('deals', [])
    print(f"Account 257515247 (Port 8002): {len(deals_8002)} total deals")
    if deals_8002:
        print("Deals on 8002:", json.dumps(deals_8002, indent=2))
    else:
        print("-> 0 deals found on 257515247. No deposits, withdrawals, or trades ever occurred on this MT5 login.")

    # Query account info directly for 8001 and 8002
    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8001/account")
    print("\nAccount 8001 (160142171) Live Account Info:", stdout.read().decode('utf-8', errors='replace'))

    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8002/account")
    print("Account 8002 (257515247) Live Account Info:", stdout.read().decode('utf-8', errors='replace'))

finally:
    ssh.close()
