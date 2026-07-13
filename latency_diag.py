# -*- coding: utf-8 -*-
"""全面延迟诊断：LLM响应速度 + 网络延迟 + 服务器性能"""
import time
import httpx
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("=" * 50)
print("鹿小仓延迟诊断")
print("=" * 50)

# 1. 服务器API状态响应速度（不涉及LLM）
t0 = time.time()
resp = httpx.get("http://120.26.176.215/api/status", timeout=10)
t1 = time.time()
print(f"\n1. /api/status (无LLM): {(t1-t0)*1000:.0f}ms — HTTP {resp.status_code}")

# 2. 同步聊天响应速度（涉及LLM）
t0 = time.time()
resp = httpx.post(
    "http://120.26.176.215/api/chat/sync",
    json={"message": "你好", "session_id": "latency_test"},
    timeout=60
)
t1 = time.time()
data = resp.json()
reply_len = len(data.get("reply", ""))
print(f"2. /api/chat/sync (含LLM): {(t1-t0)*1000:.0f}ms — 回复{reply_len}字")
print(f"   回复内容: {data.get('reply', '')[:80]}...")

# 3. 第二次测试（看是否有缓存/预热效果）
t0 = time.time()
resp = httpx.post(
    "http://120.26.176.215/api/chat/sync",
    json={"message": "门店有哪些", "session_id": "latency_test"},
    timeout=60
)
t1 = time.time()
data = resp.json()
reply_len = len(data.get("reply", ""))
print(f"3. /api/chat/sync 第2次: {(t1-t0)*1000:.0f}ms — 回复{reply_len}字")

# 4. 第三次（更长的问题）
t0 = time.time()
resp = httpx.post(
    "http://120.26.176.215/api/chat/sync",
    json={"message": "帮我分析一下广安店的运营情况", "session_id": "latency_test"},
    timeout=120
)
t1 = time.time()
data = resp.json()
reply_len = len(data.get("reply", ""))
print(f"4. /api/chat/sync 复杂问题: {(t1-t0)*1000:.0f}ms — 回复{reply_len}字")

# 5. 纯LLM延迟（直连火山引擎，不经服务器）
import configparser
config = configparser.ConfigParser()
config.read(r'C:\Users\13522\diancanmou\config.ini', encoding='utf-8')
api_key = config['llm']['api_key']
base_url = config['llm']['base_url']
model = config['llm']['model']

t0 = time.time()
resp = httpx.post(
    f"{base_url}/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={"model": model, "messages": [{"role": "user", "content": "你好"}], "stream": False, "max_tokens": 100},
    timeout=30
)
t1 = time.time()
print(f"\n5. 直连火山引擎LLM (本地PC→北京): {(t1-t0)*1000:.0f}ms — HTTP {resp.status_code}")

# 6. 从服务器中转到LLM的延迟
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", port=22, username="root", password="DOWson1108", timeout=15)

stdin, stdout, stderr = ssh.exec_command(
    f"""python3 -c "
import time, httpx
t0 = time.time()
resp = httpx.post(
    '{base_url}/chat/completions',
    headers={{'Authorization': 'Bearer {api_key}', 'Content-Type': 'application/json'}},
    json={{'model': '{model}', 'messages': [{{'role': 'user', 'content': '你好'}}], 'stream': False, 'max_tokens': 100}},
    timeout=30
)
t1 = time.time()
print(f'服务器→LLM: {{(t1-t0)*1000:.0f}}ms — HTTP {{resp.status_code}}')
" """,
    timeout=35
)
out = stdout.read().decode().strip()
err = stderr.read().decode().strip()
print(f"6. {out}")
if err:
    print(f"   STDERR: {err[:200]}")

# 7. 服务器资源状态
stdin, stdout, stderr = ssh.exec_command("free -m && echo '---' && df -h / && echo '---' && uptime")
print(f"\n7. 服务器资源:\n{stdout.read().decode().strip()}")

ssh.close()
print("\n" + "=" * 50)
print("诊断完成")
