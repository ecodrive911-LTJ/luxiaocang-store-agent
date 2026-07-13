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
    return code

# 更新Nginx：对static文件和首页禁止缓存
nginx_conf = """server {
    listen 80;
    server_name _;
    client_max_body_size 50M;

    gzip off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # 首页和静态文件禁止缓存
    location / {
        proxy_pass http://127.0.0.1:8420;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
    }

    # API接口
    location /api/ {
        proxy_pass http://127.0.0.1:8420;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
"""

run(f"cat > /etc/nginx/sites-available/luxiaocang << 'NGINXEOF'\n{nginx_conf}\nNGINXEOF")
run("nginx -t 2>&1")
run("systemctl restart nginx")
run("systemctl is-active nginx")

# 重启app
run("systemctl restart luxiaocang")
import time; time.sleep(2)
run("systemctl is-active luxiaocang")

# 验证前端文件内容
print("\n=== 服务器前端内容确认 ===")
run("grep 'chat/sync\|chat' /opt/luxiaocang/static/index.html | head -5")

# 公网测试首页是否能拿到新文件
print("\n=== 公网获取首页 ===")
run("curl -s http://120.26.176.215/ | grep -o 'v0.3.1\\|chat/sync\\|api/chat' | head -5")

# 公网测试sync接口
print("\n=== 公网sync接口测试 ===")
run("""curl -s -X POST http://120.26.176.215/api/chat/sync -H 'Content-Type: application/json' -d '{"message":"你好","session_id":"final_test"}' --max-time 20""", timeout=25)

ssh.close()
print("\n完成")
