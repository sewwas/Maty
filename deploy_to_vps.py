import paramiko
import sys

# Configure stdout for utf-8
sys.stdout.reconfigure(encoding="utf-8")

VPS_IP = "169.58.190.245"
VPS_USER = "root"
VPS_PASS = "Sasaqwe123"

def deploy():
    print(f"Connecting to VPS ({VPS_IP})...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(
            VPS_IP,
            username=VPS_USER,
            password=VPS_PASS,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
        )
        print("Connected successfully!")
        print("Running /root/Maty/deploy_vps.sh ...\n")
        
        cmd = """
        cd /root/Maty
        git fetch origin main
        git reset --hard origin/main
        bash deploy_vps.sh
        """
        
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        
        print(out)
        if err:
            print("STDERR:")
            print(err)
            
        print("\nDeployment completed successfully!")
    except Exception as e:
        print(f"Deployment error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    deploy()
