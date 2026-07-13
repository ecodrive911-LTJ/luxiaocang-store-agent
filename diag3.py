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

# 1. 确认服务器上index.html确实有 /api/chat/sync
print("=== 1. 检查服务器上的前端文件 ===")
run("grep -n 'chat/sync\|chat' /opt/luxiaocang/static/index.html | head -10")

# 2. 确认app.py有 /api/chat/sync 路由
print("\n=== 2. 检查app.py路由 ===")
run("grep -n 'chat/sync\|@app.post\|@app.get' /opt/luxiaocang/app.py")

# 3. 从公网测试同步接口
print("\n=== 3. 公网测试 /api/chat/sync ===")
run("""curl -s -X POST http://120.26.176.215/api/chat/sync -H 'Content-Type: application/json' -d '{"message":"测试","session_id":"pub_test"}' --max-time 20""", timeout=25)

# 4. Nginx是否代理了 /api/chat/sync
print("\n=== 4. Nginx配置 ===")
run("cat /etc/nginx/sites-available/luxiaocang")

# 5. 最近日志
print("\n=== 5. 最近请求日志 ===")
run("journalctl -u luxiaocang --no-pager -n 10")
run("tail -5 /var/log/nginx/access.log")

ssh.close()
