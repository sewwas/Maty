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
client.exec_command('rm -f /root/Maty/logs/bridge_*.log')

print("4. Restarting all bridges inside detached screen...")
client.exec_command("cd /root/Maty && chmod +x start_bridges.sh")
client.exec_command("screen -d -m -S bridges bash -c 'cd /root/Maty && ./start_bridges.sh'")

print("✅ Cleanup and restart dispatched successfully.")
client.close()
