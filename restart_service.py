import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", username="root", password="DOWson1108")
cmd = "systemctl restart luxiaocang.service && sleep 2 && systemctl status luxiaocang.service | head -10 && echo '=== verify Path in fresh process ===' && head -22 /opt/luxiaocang/agent_loop.py | tail -5"
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode())
print("STDERR:", stderr.read().decode())
ssh.close()
