import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect("169.58.190.245", username="root", password="Sasaqwe123", timeout=15)
    print("Connected to VPS!")

    # Cancel all stuck duplicate orders on bot 1 & 2
    stdin, stdout, stderr = ssh.exec_command("curl -s 'http://127.0.0.1:8001/cancel_all'; echo ''; curl -s 'http://127.0.0.1:8002/cancel_all'")
    print("Cancel All Result:")
    print(stdout.read().decode("utf-8", errors="ignore"))

    # Check orders count
    stdin, stdout, stderr = ssh.exec_command("curl -s 'http://127.0.0.1:8001/orders'")
    print("Remaining Orders on 8001:")
    print(stdout.read().decode("utf-8", errors="ignore"))

finally:
    ssh.close()
