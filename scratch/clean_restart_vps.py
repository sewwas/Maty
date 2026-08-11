import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to 169.58.190.245...")
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected!\n")

    print("1. Killing all old/duplicate wine, mt5, bridge, and streamlit processes...")
    cleanup_cmd = (
        "pkill -9 -f 'wine' || true; "
        "pkill -9 -f 'terminal64' || true; "
        "pkill -9 -f 'wine_mt5_bridge' || true; "
        "pkill -9 -f 'streamlit' || true; "
        "wineserver -k || true; "
        "sleep 3; "
        "echo 'Cleaned up!'"
    )
    stdin, stdout, stderr = ssh.exec_command(cleanup_cmd)
    print(stdout.read().decode("utf-8", errors="ignore"))

    print("2. Starting fresh Wine MT5 bridges via start_bridges.sh...")
    bridge_cmd = (
        "cd /root/Maty || cd ~/Maty; "
        "chmod +x start_bridges.sh; "
        "nohup ./start_bridges.sh > /root/Maty/start_bridges.log 2>&1 & "
        "sleep 8; "
        "ps aux | grep -E 'wine|bridge|terminal64' | grep -v grep"
    )
    stdin, stdout, stderr = ssh.exec_command(bridge_cmd)
    print("Bridge processes:")
    print(stdout.read().decode("utf-8", errors="ignore"))

    print("3. Starting fresh Streamlit instances on ports 8501 and 8502...")
    st_cmd = (
        "cd /root/Maty || cd ~/Maty; "
        "nohup /usr/bin/python3 -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > /root/Maty/streamlit_8501.log 2>&1 & "
        "nohup /usr/bin/python3 -m streamlit run app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true > /root/Maty/streamlit_8502.log 2>&1 & "
        "sleep 4; "
        "ps aux | grep streamlit | grep -v grep"
    )
    stdin, stdout, stderr = ssh.exec_command(st_cmd)
    print("Streamlit processes:")
    print(stdout.read().decode("utf-8", errors="ignore"))

    print("4. Testing Bridge REST endpoints...")
    time.sleep(3)
    test_cmd = (
        "curl -s --max-time 5 http://127.0.0.1:8001/account || true; echo ''; "
        "curl -s --max-time 5 http://127.0.0.1:8002/account || true"
    )
    stdin, stdout, stderr = ssh.exec_command(test_cmd)
    print("Bridge Accounts:")
    print(stdout.read().decode("utf-8", errors="ignore"))

    print("5. Current System Load:")
    stdin, stdout, stderr = ssh.exec_command("uptime; free -m")
    print(stdout.read().decode("utf-8", errors="ignore"))

finally:
    ssh.close()
    print("Clean restart completed successfully!")
