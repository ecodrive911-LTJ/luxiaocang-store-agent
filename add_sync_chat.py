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
    app_code = f.read().decode('utf-8')

# 在chat接口前添加一个非流式chat接口 /api/chat/sync
# 找到 @app.post("/api/chat") 的位置
insert_marker = '@app.post("/api/chat")'
new_endpoint = '''@app.post("/api/chat/sync")
async def chat_sync(req: ChatRequest):
    """非流式聊天接口 - 一次性返回完整回复，兼容所有浏览器"""
    save_message("user", req.message, req.session_id)
    history = get_conversation_history(req.session_id, limit=10)
    
    full_reply = ""
    async for chunk in agent_loop(req.message, history, config):
        full_reply += chunk
    
    save_message("assistant", full_reply, req.session_id)
    return {"reply": full_reply, "session_id": req.session_id}

'''

if '/api/chat/sync' not in app_code:
    app_code = app_code.replace(insert_marker, new_endpoint + insert_marker)
    with sftp.open('/opt/luxiaocang/app.py', 'w') as f:
        f.write(app_code.encode('utf-8'))
    print("已添加 /api/chat/sync 接口")
else:
    print("/api/chat/sync 已存在")

sftp.close()

# 重启服务
stdin, stdout, stderr = ssh.exec_command("systemctl restart luxiaocang && sleep 2 && systemctl is-active luxiaocang")
print("服务状态:", stdout.read().decode().strip())

# 测试非流式接口
stdin, stdout, stderr = ssh.exec_command(
    '''curl -s -X POST http://127.0.0.1:8420/api/chat/sync -H 'Content-Type: application/json' -d '{"message":"你好","session_id":"sync_test"}' --max-time 30'''
)
out = stdout.read().decode().strip()
print("测试结果:", out[:200])

ssh.close()
