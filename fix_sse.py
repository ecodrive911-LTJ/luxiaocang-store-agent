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

# 修复Nginx配置：添加 proxy_request_buffering off 和 gzip off
nginx_conf = """server {
    listen 80;
    server_name _;
    client_max_body_size 50M;

    # 全局关闭gzip和缓冲
    gzip off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    location / {
        proxy_pass http://127.0.0.1:8420;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # SSE专用配置
    location /api/chat {
        proxy_pass http://127.0.0.1:8420;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_cache off;
        proxy_request_buffering off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        chunked_transfer_encoding on;
        add_header X-Accel-Buffering no always;
        add_header Cache-Control no-cache always;
        # 关键：强制每1秒flush一次
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }
}
"""

run(f"cat > /etc/nginx/sites-available/luxiaocang << 'NGINXEOF'\n{nginx_conf}\nNGINXEOF")
run("nginx -t 2>&1")
run("systemctl restart nginx")
run("systemctl is-active nginx")

# 同时修改app.py，在SSE response中添加header
# 直接用sed在StreamingResponse后面加header
run("""python3 -c "
import re
with open('/opt/luxiaocang/app.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 在StreamingResponse里加headers
old = 'return StreamingResponse(stream_response(), media_type=\"text/event-stream\")'
new = '''return StreamingResponse(
        stream_response(),
        media_type=\"text/event-stream\",
        headers={
            \"Cache-Control\": \"no-cache\",
            \"X-Accel-Buffering\": \"no\",
            \"Connection\": \"keep-alive\",
        }
    )'''
code = code.replace(old, new)

with open('/opt/luxiaocang/app.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('app.py updated with SSE headers')
'""")

# 重启服务
run("systemctl restart luxiaocang")
import time; time.sleep(2)
run("systemctl is-active luxiaocang")

# 验证
print("\n=== 验证 ===")
run("curl -s -o /dev/null -w 'HTTP %{http_code} size=%{size_download}' http://127.0.0.1:8420/api/status")
print()
run("curl -s -N -X POST http://120.26.176.215/api/chat -H 'Content-Type: application/json' -d '{\"message\":\"test\",\"session_id\":\"final\"}' --max-time 15 2>&1 | head -10", timeout=20)

ssh.close()
print("\n完成")
