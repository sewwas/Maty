import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    
    cmd = (
        'echo "=== BRIDGE 8001 ACCOUNT ==="; '
        'curl -s http://127.0.0.1:8001/account || true; echo ""; '
        'echo "=== BRIDGE 8002 ACCOUNT ==="; '
        'curl -s http://127.0.0.1:8002/account || true; echo ""; '
        'echo "=== SYSTEM UPTIME & LOAD ==="; '
        'uptime; '
        'echo "=== ACTIVE PROCESSES ==="; '
        'ps aux | grep -E "streamlit|wine_mt5_bridge" | grep -v grep'
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print(stdout.read().decode("utf-8", errors="ignore"))
finally:
    ssh.close()
