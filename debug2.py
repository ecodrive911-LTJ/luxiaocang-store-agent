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

# 1. 检查前端文件是否真的更新了
print("=== 前端文件检查 ===")
run("wc -c /opt/luxiaocang/static/index.html")
run("grep -c 'XMLHttpRequest' /opt/luxiaocang/static/index.html")
run("grep -c 'getReader' /opt/luxiaocang/static/index.html")

# 2. 查看最近的Nginx和app日志
print("\n=== Nginx访问日志(最近10条) ===")
run("tail -10 /var/log/nginx/access.log")

print("\n=== Nginx错误日志(最近10条) ===")
run("tail -10 /var/log/nginx/error.log")

print("\n=== App日志(最近20条) ===")
run("journalctl -u luxiaocang --no-pager -n 20")

# 3. 直接从服务器外部curl测试公网
print("\n=== 服务器上curl公网测试 ===")
run("curl -v -N -X POST http://120.26.176.215/api/chat -H 'Content-Type: application/json' -d '{\"message\":\"hi\",\"session_id\":\"curl_test\"}' --max-time 30 2>&1 | head -40", timeout=35)

ssh.close()
