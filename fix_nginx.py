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

# 更新Nginx配置 - 增加SSE支持
nginx_conf = """server {
    listen 80;
    server_name _;
    client_max_body_size 50M;

    # 关键：SSE需要的设置
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
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        chunked_transfer_encoding on;
        add_header X-Accel-Buffering no;
    }
}
"""

# 写入新配置
run(f"cat > /etc/nginx/sites-available/luxiaocang << 'NGINXEOF'\n{nginx_conf}\nNGINXEOF")
run("nginx -t 2>&1")
run("systemctl restart nginx")
run("systemctl is-active nginx")

# 同时检查一下agent_loop.py的LLM调用是否有问题
print("\n=== 检查agent_loop.py ===")
run("head -5 /opt/luxiaocang/agent_loop.py")
run("grep -n 'call_llm_raw\|call_llm_stream' /opt/luxiaocang/agent_loop.py | head -10")

# 重启应用确保干净状态
run("systemctl restart luxiaocang")
import time; time.sleep(2)
run("systemctl is-active luxiaocang")

# 再测一次
print("\n=== 本地测试聊天 ===")
run("""curl -s -N -X POST http://127.0.0.1:8420/api/chat -H 'Content-Type: application/json' -d '{"message":"你好","session_id":"nginx_test"}' --max-time 30 2>&1 | head -20""", timeout=35)

ssh.close()
print("\n完成")
