import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('169.58.190.245', username='root', password='Sasaqwe123')

print("1. Nuking stuck Wine servers and processes...")
client.exec_command('killall -9 wineserver wine wine64 python.exe || true')
time.sleep(2)

print("1.5 Pulling latest code...")
client.exec_command('cd /root/Maty && git pull')

print("2. Ensuring MetaTrader 5_6 exists for Bot 6...")
client.exec_command('cp -R "/root/.wine/drive_c/Program Files/MetaTrader 5" "/root/.wine/drive_c/Program Files/MetaTrader 5_6" || true')

print("3. Clearing old logs...")
stdin, stdout, stderr = client.exec_command('rm -f /root/Maty/logs/bridge_*.log')
stdout.channel.recv_exit_status() # WAIT for rm to finish

print("4. Restarting all bridges via nohup...")
client.exec_command("cd /root/Maty && chmod +x start_bridges.sh")
client.exec_command("cd /root/Maty && nohup ./start_bridges.sh > start_bridges_run.log 2>&1 &")

print("✅ Cleanup and restart dispatched successfully.")
client.close()
