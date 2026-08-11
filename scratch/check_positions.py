import paramiko
import json
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)

    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8001/positions")
    res1 = stdout.read().decode("utf-8", errors="replace")
    print("=== LIVE POSITIONS ON PORT 8001 ===")
    print(res1)

    stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8002/positions")
    res2 = stdout.read().decode("utf-8", errors="replace")
    print("\n=== LIVE POSITIONS ON PORT 8002 ===")
    print(res2)

finally:
    ssh.close()
