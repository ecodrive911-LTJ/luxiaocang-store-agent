# -*- coding: utf-8 -*-
"""Test 4 单独验证 - /api/chat 流式响应的 store_id 强制覆写"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json
import urllib.request
import urllib.error

BASE = "http://120.26.176.215"

def api_login(username, password):
    data = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(f"{BASE}/api/auth/login", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if "token" in result:
            return result["token"]
    except urllib.error.HTTPError as e:
        print(f"  login fail: {e.code} {e.read().decode()[:200]}")
    return None

def api_post_stream(path, token, data, timeout=30):
    """发流式请求，读取完整响应（不解析流）"""
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    full = b""
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        full += chunk
        if len(full) > 30000:
            break
    return full.decode("utf-8", errors="replace")

def api_post_json(path, token, data, timeout=15):
    """非流式（关闭streaming）"""
    if isinstance(data, dict):
        data = {**data, "stream": False}
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}

print("=" * 60)
print("Test 4: store_id 强制绑定")
print("=" * 60)

owner_token = api_login("guangan", "guangan123")
admin_token = api_login("luxiaocang", "LXC2025")
print(f"owner_token: {owner_token[:30] if owner_token else 'FAIL'}")
print(f"admin_token: {admin_token[:30] if admin_token else 'FAIL'}")

# 财富店 id
caifu_id = "2d8d867e-57b0-4389-a103-0083990b002f"
guangan_id = "f67b4c21-2529-4d96-a2e8-0749451e5295"

# 1. owner传财富店ID (越权)
print("\n[1] store_owner POST /api/chat, store_id=caifu_id (越权)")
result = api_post_json("/api/chat", owner_token, {
    "message": "这个店有什么商品？",
    "store_id": caifu_id
}, timeout=15)
print(f"  Response: {json.dumps(result, ensure_ascii=False)[:500]}")
if "error" in result:
    if result.get("error") == 403:
        print(f"  [OK] 拒绝越权访问 (403)")
    else:
        print(f"  [WARN] 错误: {result}")
elif "store_id" in str(result):
    body = str(result)
    if guangan_id in body and caifu_id not in body:
        print(f"  [OK] store_id 强制覆写为广安店")
    elif caifu_id in body:
        print(f"  [FAIL] store_id 未覆写，越权通过！")
    else:
        print(f"  [?] 无法判断，body不含store_id")

# 2. owner传正确ID
print("\n[2] store_owner POST /api/chat, store_id=guangan_id (正确)")
result = api_post_json("/api/chat", owner_token, {
    "message": "本店有什么商品？",
    "store_id": guangan_id
}, timeout=15)
print(f"  Response (前200字): {json.dumps(result, ensure_ascii=False)[:200]}")

# 3. owner不传store_id, 应自动绑定
print("\n[3] store_owner POST /api/chat, 不传store_id (自动绑定)")
result = api_post_json("/api/chat", owner_token, {
    "message": "本店有什么商品？"
}, timeout=15)
print(f"  Response (前200字): {json.dumps(result, ensure_ascii=False)[:200]}")

# 4. admin 访问两个门店
print("\n[4] admin POST /api/chat, store_id=caifu_id (任意门店)")
result = api_post_json("/api/chat", admin_token, {
    "message": "本店有什么商品？",
    "store_id": caifu_id
}, timeout=15)
print(f"  Response (前200字): {json.dumps(result, ensure_ascii=False)[:200]}")

print("\n" + "=" * 60)
print("Test 4 完成")
print("=" * 60)
