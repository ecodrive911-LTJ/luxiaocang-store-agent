# -*- coding: utf-8 -*-
"""读取服务器上的app.py和agent_loop.py，导出完整功能清单"""
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

def run(cmd, timeout=15):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace")

print("=== app.py 全文 ===")
print(run("cat /opt/luxiaocang/app.py"))

print("\n=== agent_loop.py 全文 ===")
print(run("cat /opt/luxiaocang/agent_loop.py"))

print("\n=== config.ini ===")
print(run("cat /opt/luxiaocang/config.ini"))

print("\n=== 目录结构 ===")
print(run("find /opt/luxiaocang -type f | head -50"))

print("\n=== scripts目录 ===")
print(run("ls -la /opt/luxiaocang/scripts/ 2>/dev/null || echo 'no scripts dir'"))

print("\n=== knowledge目录 ===")
print(run("ls -la /opt/luxiaocang/knowledge/ 2>/dev/null || echo 'no knowledge dir'"))

ssh.close()
