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
    return out

print("=== 1. 服务状态 ===")
run("systemctl is-active luxiaocang")

print("\n=== 2. App日志(最近30行) ===")
run("journalctl -u luxiaocang --no-pager -n 30")

print("\n=== 3. config.ini 内容 ===")
run("cat /opt/luxiaocang/config.ini")

print("\n=== 4. 直接测试LLM API连通性 ===")
# 从config.ini读取API配置，直接curl测试火山引擎
run("""python3 -c "
import configparser, json, urllib.request
c = configparser.ConfigParser()
c.read('/opt/luxiaocang/config.ini', encoding='utf-8')
key = c['llm']['api_key']
url = c['llm']['base_url'] + '/chat/completions'
model = c['llm']['model']
print(f'URL: {url}')
print(f'Model: {model}')
print(f'Key: {key[:10]}...{key[-5:]}')

payload = json.dumps({
    'model': model,
    'messages': [{'role':'user','content':'你好'}],
    'stream': False,
    'max_tokens': 50
}).encode()
req = urllib.request.Request(url, data=payload, headers={
    'Authorization': f'Bearer {key}',
    'Content-Type': 'application/json'
})
try:
    import urllib.error
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    print('LLM回复:', data['choices'][0]['message']['content'][:100])
    print('LLM状态: OK')
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f'HTTP错误 {e.code}: {body[:300]}')
except Exception as e:
    print(f'请求失败: {e}')
'""", timeout=20)

print("\n=== 5. 测试 /api/chat/sync ===")
run("""curl -s -X POST http://127.0.0.1:8420/api/chat/sync -H 'Content-Type: application/json' -d '{"message":"你好","session_id":"diag"}' --max-time 20""", timeout=25)

print("\n=== 6. 测试 /api/chat (流式) ===")
run("""curl -s -N -X POST http://127.0.0.1:8420/api/chat -H 'Content-Type: application/json' -d '{"message":"hi","session_id":"diag2"}' --max-time 20 2>&1 | head -5""", timeout=25)

ssh.close()
