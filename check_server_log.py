import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", username="root", password="DOWson1108")
cmd = "journalctl -u luxiaocang.service --no-pager -n 40"
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
print("STDERR:", stderr.read().decode())
ssh.close()
