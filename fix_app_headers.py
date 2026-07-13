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

sftp = ssh.open_sftp()

# 读取远程app.py
with sftp.open('/opt/luxiaocang/app.py', 'r') as f:
    code = f.read().decode('utf-8')

# 替换StreamingResponse
old = 'return StreamingResponse(stream_response(), media_type="text/event-stream")'
new = '''return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )'''

if old in code:
    code = code.replace(old, new)
    with sftp.open('/opt/luxiaocang/app.py', 'w') as f:
        f.write(code.encode('utf-8'))
    print("app.py SSE headers 已添加")
else:
    print("未找到目标字符串，可能已修改过")
    # 检查是否已有
    if 'X-Accel-Buffering' in code:
        print("已有X-Accel-Buffering header")

sftp.close()

# 重启
stdin, stdout, stderr = ssh.exec_command("systemctl restart luxiaocang && sleep 2 && systemctl is-active luxiaocang")
print("服务状态:", stdout.read().decode().strip())

ssh.close()
