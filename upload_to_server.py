#!/usr/bin/env python3
"""SFTP upload files to Alibaba Cloud and restart service"""
import paramiko
import sys

HOST = "120.26.176.215"
USER = "root"
PASS = "DOWson1108"
REMOTE_DIR = "/opt/luxiaocang"
FILES = ["app.py", "agent_loop.py", "analytics.py", "memory.py", "ingestion.py", "build_store.py", "calculator.py", "pricing.py", "dynamic_profit_engine.py", "profit_tools.py", "intelligence_tools.py", "WORKFLOW_MANDATORY.md", "static/index.html"]
COMP_INTEL_FILES = [
    "competitor_intelligence_skill/README_FOR_AGENT.md",
    "competitor_intelligence_skill/tool_schemas.json",
    "competitor_intelligence_skill/core_logic.py",
    "competitor_intelligence_skill/data_collection_checklist.md",
    "competitor_intelligence_skill/agent_workflow_integration.md",
]
LIB_FILES = ["static/lib/echarts.min.js"]

transport = paramiko.Transport((HOST, 22))
transport.connect(username=USER, password=PASS)
sftp = paramiko.SFTPClient.from_transport(transport)

# Ensure static/lib exists for echarts bundle
try:
    sftp.stat(f"{REMOTE_DIR}/static/lib")
except IOError:
    sftp.mkdir(f"{REMOTE_DIR}/static/lib")

for f in FILES + LIB_FILES + COMP_INTEL_FILES:
    local = f"C:\\Users\\13522\\diancanmou\\{f}"
    remote = f"{REMOTE_DIR}/{f}"
    # 确保子目录存在
    if "/" in f:
        remote_dir = f"{REMOTE_DIR}/{f.rsplit('/', 1)[0]}"
        try:
            sftp.stat(remote_dir)
        except IOError:
            sftp.mkdir(remote_dir)
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
