# -*- coding: utf-8 -*-
import paramiko
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOST = "120.26.176.215"
PORT = 22
USER = "root"
PASSWORD = "DOWson1108"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(f"STDERR: {err.rstrip()}")

print("=== 1. 服务状态 ===")
run("systemctl is-active luxiaocang")
run("systemctl is-active nginx")

print("\n=== 2. 端口监听 ===")
run("ss -tlnp | grep -E '80|8420'")

print("\n=== 3. Nginx配置测试 ===")
run("nginx -t 2>&1")

print("\n=== 4. Nginx错误日志(最近20行) ===")
run("tail -20 /var/log/nginx/error.log")

print("\n=== 5. App日志(最近20行) ===")
run("journalctl -u luxiaocang --no-pager -n 20")

print("\n=== 6. 本地curl测试 ===")
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8420/")
print()
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/")
print()

print("\n=== 7. Nginx配置全文 ===")
run("cat /etc/nginx/sites-available/luxiaocang")
run("ls -la /etc/nginx/sites-enabled/")

ssh.close()
