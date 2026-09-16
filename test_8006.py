import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('169.58.190.245', username='root', password='Sasaqwe123')

print("Executing test for Bridge 8006...")
cmd = "env WINEPREFIX=/root/.wine WINEDEBUG=-all DISPLAY=:1 WINE_BRIDGE_PORT=8006 MT5_PATH='C:\\Program Files\\MetaTrader 5_6\\terminal64.exe' wine /root/.wine/drive_c/Program\\ Files/Python311/python.exe Z:/root/Maty/wine_mt5_bridge.py 8006"
stdin, stdout, stderr = client.exec_command(cmd)

print("OUT:", stdout.read().decode())
print("ERR:", stderr.read().decode())
client.close()
