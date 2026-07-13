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
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print(f"STDERR: {err.rstrip()}")

print("=== 服务日志(最近30行) ===")
run("journalctl -u luxiaocang --no-pager -n 30")

print("\n=== Nginx错误日志 ===")
run("tail -10 /var/log/nginx/error.log")

print("\n=== Nginx访问日志(最近10行) ===")
run("tail -10 /var/log/nginx/access.log")

ssh.close()
