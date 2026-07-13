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

# 上传更新后的index.html
sftp = ssh.open_sftp()
sftp.put(r"C:\Users\13522\diancanmou\static\index.html", "/opt/luxiaocang/static/index.html")
sftp.close()
print("index.html 已更新")

# 重启服务
stdin, stdout, stderr = ssh.exec_command("systemctl restart luxiaocang && sleep 1 && systemctl is-active luxiaocang")
print("服务状态:", stdout.read().decode().strip())

# 验证
stdin, stdout, stderr = ssh.exec_command("curl -s http://127.0.0.1:8420/api/status")
print("API:", stdout.read().decode().strip())

ssh.close()
print("完成")
