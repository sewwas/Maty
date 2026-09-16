import paramiko
import os
import glob

host = '169.58.190.245'
user = 'root'
password = 'Sasaqwe123'
remote_dir = '/root/Maty'

try:
    print(f"Connecting to {host} via SFTP...")
    transport = paramiko.Transport((host, 22))
    transport.connect(username=user, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    
    config_files = glob.glob("bridge_config_*.json")
    for file in config_files:
        local_path = file
        remote_path = f"{remote_dir}/{file}"
        print(f"Uploading {local_path} -> {remote_path}")
        sftp.put(local_path, remote_path)
    
    sftp.close()
    transport.close()
    
    print("Files uploaded! Now restarting bridges via SSH...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, password=password, timeout=10)
    
    # Run bridge restart
    print("Killing zombie Wine Python processes to release ports...")
    client.exec_command("killall -9 python.exe || true")
    
    stdin, stdout, stderr = client.exec_command("cd /root/Maty || cd Maty && ./start_bridges.sh")
    print(stdout.read().decode().strip())
    
    client.close()
    print("✅ All bridges restarted with new credentials!")

except Exception as e:
    print(f"Error: {e}")
