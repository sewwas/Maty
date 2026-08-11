import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to VPS 169.58.190.245...")
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected!\n")

    # 1. System stats
    stdin, stdout, stderr = ssh.exec_command("uptime; free -m; df -h /")
    print("=== SYSTEM LOAD & MEMORY ===")
    print(stdout.read().decode("utf-8", errors="ignore"))

    # 2. Process list
    stdin, stdout, stderr = ssh.exec_command("ps aux --sort=-%cpu | head -n 25")
    print("=== TOP CPU PROCESSES ===")
    print(stdout.read().decode("utf-8", errors="ignore"))

    # 3. Streamlit Logs tail
    stdin, stdout, stderr = ssh.exec_command("tail -n 40 /root/Maty/streamlit_8501.log 2>/dev/null || echo 'No log'")
    print("=== STREAMLIT 8501 LOGS (Last 40 lines) ===")
    print(stdout.read().decode("utf-8", errors="ignore"))

    stdin, stdout, stderr = ssh.exec_command("tail -n 40 /root/Maty/streamlit_8502.log 2>/dev/null || echo 'No log'")
    print("=== STREAMLIT 8502 LOGS (Last 40 lines) ===")
    print(stdout.read().decode("utf-8", errors="ignore"))

    # 4. Bridge Logs tail
    stdin, stdout, stderr = ssh.exec_command("tail -n 40 /root/Maty/start_bridges.log 2>/dev/null || echo 'No log'")
    print("=== START BRIDGES LOG (Last 40 lines) ===")
    print(stdout.read().decode("utf-8", errors="ignore"))

    # 5. Test Bridge REST endpoints
    stdin, stdout, stderr = ssh.exec_command("curl -s --max-time 3 http://127.0.0.1:8001/account; echo ''; curl -s --max-time 3 http://127.0.0.1:8002/account")
    print("=== BRIDGE REST RESPONSES ===")
    print(stdout.read().decode("utf-8", errors="ignore"))

finally:
    ssh.close()
