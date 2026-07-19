#!/usr/bin/env python3
"""SFTP upload files to Alibaba Cloud and restart service"""
import paramiko
import sys

HOST = "120.26.176.215"
USER = "root"
PASS = "DOWson1108"
REMOTE_DIR = "/opt/luxiaocang"
FILES = ["app.py", "agent_loop.py", "analytics.py", "memory.py", "ingestion.py", "build_store.py", "calculator.py", "pricing.py", "static/index.html"]
LIB_FILES = ["static/lib/echarts.min.js"]

transport = paramiko.Transport((HOST, 22))
transport.connect(username=USER, password=PASS)
sftp = paramiko.SFTPClient.from_transport(transport)

# Ensure static/lib exists for echarts bundle
try:
    sftp.stat(f"{REMOTE_DIR}/static/lib")
except IOError:
    sftp.mkdir(f"{REMOTE_DIR}/static/lib")

for f in FILES + LIB_FILES:
    local = f"C:\\Users\\13522\\diancanmou\\{f}"
    remote = f"{REMOTE_DIR}/{f}"
    print(f"Uploading {f}...")
    sftp.put(local, remote)
    print(f"  OK: {f} -> {remote}")

sftp.close()

# Restart service
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS)
stdin, stdout, stderr = ssh.exec_command("systemctl restart luxiaocang.service && sleep 2 && systemctl status luxiaocang.service --no-pager -l")
print("\n=== Service Status ===")
print(stdout.read().decode())
print(stderr.read().decode())
ssh.close()
transport.close()
print("\nDone!")
