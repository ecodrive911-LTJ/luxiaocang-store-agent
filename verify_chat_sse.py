# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json
import requests
import re

BASE = "http://120.26.176.215"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json().get("token")

def stream_chat(token, message, store_id=None, timeout=120):
    """读SSE流"""
    payload = {"message": message, "session_id": f"verify_{int(__import__('time').time())}"}
    if store_id:
        payload["store_id"] = store_id
    r = requests.post(f"{BASE}/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=timeout, stream=True)
    full_text = ""
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                d = json.loads(line[6:])
                if "content" in d:
                    full_text += d["content"]
                if "error" in d:
                    full_text += f"\n[ERR] {d['error']}"
            except:
                pass
    return full_text

print("=" * 60)
print("D1 自主验证报告 (含SSE流式)")
print("=" * 60)

admin_token = login("luxiaocang", "LXC2025")
owner_token = login("guangan", "guangan123")
print(f"admin: {admin_token[:20]}")
print(f"owner: {owner_token[:20]}")

caifu_id = "2d8d867e-57b0-4389-a103-0083990b002f"
guangan_id = "f67b4c21-2529-4d96-a2e8-0749451e5295"

# Test 1: owner 越权
print("\n[1] store_owner 越权: store_id=caifu_id (财富店)")
text = stream_chat(owner_token, "本店有什么商品？", store_id=caifu_id, timeout=60)
# 提取关键信息
store_mentioned = []
if "广安" in text: store_mentioned.append("广安")
if "财富" in text: store_mentioned.append("财富")
print(f"  响应包含门店: {store_mentioned}")
print(f"  响应前300字: {text[:300]}")
if "财富" not in text and "广安" in text:
    print(f"  [OK] 越权被阻止，强制覆写为广安店")
elif "财富" in text:
    print(f"  [FAIL] 越权通过")

# Test 2: owner 正确
print("\n[2] store_owner 正确: store_id=guangan_id")
text = stream_chat(owner_token, "本店有什么商品？", store_id=guangan_id, timeout=60)
print(f"  响应前200字: {text[:200]}")
if "广安" in text:
    print(f"  [OK] 正确访问广安店")

# Test 3: owner 不传
print("\n[3] store_owner 不传store_id")
text = stream_chat(owner_token, "本店有什么商品？", timeout=60)
print(f"  响应前200字: {text[:200]}")

# Test 4: admin 越权（应该可以）
print("\n[4] admin: store_id=caifu_id (财富店)")
text = stream_chat(admin_token, "本店有什么商品？", store_id=caifu_id, timeout=60)
print(f"  响应前200字: {text[:200]}")
if "财富" in text:
    print(f"  [OK] admin 任意门店访问")

# Test 5: Path bug
print("\n[5] admin 触发 competitive_analysis 脚本 (Path bug 验证)")
text = stream_chat(admin_token, "请用 competitive_analysis 脚本分析广安店", timeout=120)
print(f"  响应前800字:\n{text[:800]}")
if "Path" in text and "not defined" in text:
    print(f"  [FAIL] Path bug 仍存在")
elif "name 'Path'" in text:
    print(f"  [FAIL] Path bug 仍存在")
elif "执行失败" in text or "失败" in text:
    print(f"  [WARN] 脚本执行失败（但不是Path）: {text[-300:]}")
elif "广安" in text and ("运营" in text or "分析" in text):
    print(f"  [OK] 脚本正常执行")
else:
    print(f"  [?] 响应未明确判断")

print("\n" + "=" * 60)
print("D1 验证完毕")
print("=" * 60)
