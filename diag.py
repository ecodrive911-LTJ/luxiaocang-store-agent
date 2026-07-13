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

print("=== 服务状态 ===")
run("systemctl is-active luxiaocang")
run("systemctl is-active nginx")

print("\n=== 端口监听 ===")
run("ss -tlnp | grep -E '80|8420'")

print("\n=== 最近服务日志 ===")
run("journalctl -u luxiaocang --no-pager -n 15")

print("\n=== Nginx错误日志(最近5行) ===")
run("tail -5 /var/log/nginx/error.log")

print("\n=== Nginx访问日志(最近5行) ===")
run("tail -5 /var/log/nginx/access.log")

print("\n=== 本地curl测试 ===")
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8420/api/status")
print()
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80/api/status")
print()

print("\n=== 前端index.html检查 ===")
run("head -3 /opt/luxiaocang/static/index.html")
run("wc -c /opt/luxiaocang/static/index.html")

ssh.close()
