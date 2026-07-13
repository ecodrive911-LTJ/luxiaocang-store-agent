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

# 读取服务器上的index.html
with sftp.open('/opt/luxiaocang/static/index.html', 'r') as f:
    content = f.read().decode('utf-8')

# 检查关键行
for i, line in enumerate(content.split('\n'), 1):
    if 'chat/sync' in line or 'api/chat' in line:
        print(f"Line {i}: {line.strip()}")

print(f"\n总长度: {len(content)} 字符")
print(f"包含 chat/sync: {'chat/sync' in content}")
print(f"包含 v0.3.1: {'v0.3.1' in content}")

# 如果不对，直接重新上传
if 'chat/sync' not in content:
    print("\n服务器文件不正确，重新上传...")
    sftp.put(r'C:\Users\13522\diancanmou\static\index.html', '/opt/luxiaocang/static/index.html')
    
    with sftp.open('/opt/luxiaocang/static/index.html', 'r') as f:
        content2 = f.read().decode('utf-8')
    print(f"重新上传后包含 chat/sync: {'chat/sync' in content2}")
    print(f"包含 v0.3.1: {'v0.3.1' in content2}")

sftp.close()
ssh.close()
