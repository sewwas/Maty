import paramiko
import time

host = '169.58.190.245'
user = 'root'
password = 'Sasaqwe123'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    print(f"Connecting to {host}...")
    client.connect(hostname=host, username=user, password=password, timeout=10)
    print("Connected! Running update commands on your VPS...")
    
    commands = [
        # Pull latest code
        "cd /root/Maty || cd Maty && git reset --hard && git pull",
        
        # Kill the crashed/old hub
        "pkill -f hub.py",
        
        # Start the hub in the background
        "cd /root/Maty || cd Maty && nohup python3 hub.py > hub.log 2>&1 &",
        
        # Permissions
        "cd /root/Maty || cd Maty && chmod +x start_bridges.sh bot6_crossfire/start_bot6.sh",
        
        # Restart all bridges (including the new Port 8006 for Bot 6)
        "cd /root/Maty || cd Maty && ./start_bridges.sh",
        
        # Kill any existing Bot 6 processes before starting
        "pkill -f bot6_crossfire/main.py",
        "pkill -f bot6_crossfire/panel.py",
        
        # Start Bot 6 Engine and Dashboard
        "cd /root/Maty || cd Maty && ./bot6_crossfire/start_bot6.sh",
        
        # Verify it's running
        "sleep 2",
        "ps aux | grep hub.py | grep -v grep"
    ]
    
    for cmd in commands:
        print(f"Executing: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        if out: print(f"OUT: {out}")
        if err: print(f"ERR: {err}")
        
    print("\n✅ VPS Successfully Updated! The Hub is back online.")
except Exception as e:
    print(f"Error connecting to VPS: {e}")
finally:
    client.close()
