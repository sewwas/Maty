import paramiko
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('169.58.190.245', username='root', password='Sasaqwe123')

for port in [8001, 8002, 8003, 8004, 8005, 8006]:
    stdin, stdout, stderr = client.exec_command(f'curl --max-time 2 -sf http://127.0.0.1:{port}/account')
    out = stdout.read().decode().strip()
    if out:
        print(f"Bot {port}: {out}")
    else:
        print(f"Bot {port} failed")
