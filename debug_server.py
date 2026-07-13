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
    return out

# 检查服务状态
print("=== luxiaocang服务 ===")
run("systemctl status luxiaocang --no-pager 2>&1 | head -20")

print("\n=== 本地curl测试 ===")
run("curl -s http://127.0.0.1:8420/api/status")

print("\n=== nginx错误日志 ===")
run("tail -20 /var/log/nginx/error.log")

print("\n=== 检查端口 ===")
run("ss -tlnp | grep -E '80|8420'")

print("\n=== 防火墙状态 ===")
run("ufw status 2>&1")

print("\n=== iptables ===")
run("iptables -L -n 2>&1 | head -20")

ssh.close()
