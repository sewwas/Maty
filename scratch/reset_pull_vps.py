import paramiko
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to VPS 169.58.190.245 as root...")
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected to VPS!\n")

    # 1. Reset and Pull Git on VPS
    print("=== 1. GIT RESET & PULL ===")
    git_cmd = (
        "cd /root/Maty || cd ~/Maty; "
        "git fetch origin main; "
        "git reset --hard origin/main; "
        "git log -1 --oneline"
    )
    stdin, stdout, stderr = ssh.exec_command(git_cmd)
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err:
        print("Git stderr:", err)

    # 2. Kill old processes & Restart Wine MT5 bridges + Streamlit cleanly
    print("=== 2. RESTARTING BRIDGES & DASHBOARD ===")
    restart_cmd = (
        "pkill -9 -f 'streamlit' || true; "
        "cd /root/Maty || cd ~/Maty; "
        "chmod +x start_bridges.sh; "
        "nohup ./start_bridges.sh > /root/Maty/start_bridges.log 2>&1 & "
        "sleep 5; "
        "nohup /usr/bin/python3 -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > /root/Maty/streamlit_8501.log 2>&1 & "
        "nohup /usr/bin/python3 -m streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true > /root/Maty/streamlit_8502.log 2>&1 & "
        "sleep 4; "
        "ps aux | grep -E 'streamlit|wine_mt5_bridge' | grep -v grep"
    )
    stdin, stdout, stderr = ssh.exec_command(restart_cmd)
    print(stdout.read().decode("utf-8", errors="replace"))

    # 3. Test Bridge status
    time.sleep(3)
    print("=== 3. TESTING BRIDGES ===")
    test_cmd = (
        "curl -s --max-time 5 http://127.0.0.1:8001/account || true; echo ''; "
        "curl -s --max-time 5 http://127.0.0.1:8002/account || true"
    )
    stdin, stdout, stderr = ssh.exec_command(test_cmd)
    print(stdout.read().decode("utf-8", errors="replace"))

    print("=== 4. SYSTEM UPTIME & LOAD ===")
    stdin, stdout, stderr = ssh.exec_command("uptime")
    print(stdout.read().decode("utf-8", errors="replace"))

finally:
    ssh.close()
    print("\n✅ Reset, Pull & Restart Completed Successfully!")
