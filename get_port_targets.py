import paramiko
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('169.58.190.245', username='root', password='Sasaqwe123')
stdin, stdout, stderr = client.exec_command('grep port_targets /root/Maty/wine_mt5_bridge.py')
print(stdout.read().decode())
