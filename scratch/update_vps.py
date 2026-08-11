import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to 169.58.190.245 as root...")
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected!")

    # 1. Restart Streamlit
    restart_cmd = (
        'pkill -f "streamlit run /root/Maty/app.py" || true; '
        'sleep 2; '
        'nohup /usr/bin/python3 -m streamlit run /root/Maty/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true > /root/Maty/streamlit_8501.log 2>&1 & '
        'nohup /usr/bin/python3 -m streamlit run /root/Maty/app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true > /root/Maty/streamlit_8502.log 2>&1 & '
        'sleep 3; '
        'ps aux | grep streamlit'
    )
    stdin, stdout, stderr = ssh.exec_command(restart_cmd)
    print("--- STREAMLIT STATUS ---")
    print(stdout.read().decode("utf-8", errors="ignore"))

    # 2. Check Wine MT5 Bridges
    stdin, stdout, stderr = ssh.exec_command(
        'curl -s http://127.0.0.1:8001/account || true; echo ""; '
        'curl -s http://127.0.0.1:8002/account || true'
    )
    print("--- WINE BRIDGES RESPONSE ---")
    print(stdout.read().decode("utf-8", errors="ignore"))

finally:
    ssh.close()
    print("All VPS updates completed successfully!")
