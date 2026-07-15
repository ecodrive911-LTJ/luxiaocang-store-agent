# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json
import requests

BASE = "http://120.26.176.215"
TIMEOUT = 60

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json().get("token")

print("=== Test 4 重新测试（使用requests库）===")
admin_token = login("luxiaocang", "LXC2025")
owner_token = login("guangan", "guangan123")
print(f"admin: {admin_token[:20]}...")
print(f"owner: {owner_token[:20]}...")

caifu_id = "2d8d867e-57b0-4389-a103-0083990b002f"
guangan_id = "f67b4c21-2529-4d96-a2e8-0749451e5295"

# 关键测试: owner 传财富店id (越权)
print("\n[1] store_owner 越权 - store_id=caifu_id")
r = requests.post(f"{BASE}/api/chat",
    headers={"Authorization": f"Bearer {owner_token}"},
    json={"message": "这个店有什么商品？", "store_id": caifu_id, "stream": False},
    timeout=TIMEOUT)
print(f"  HTTP {r.status_code}")
print(f"  Body (前500字): {r.text[:500]}")
if r.status_code == 403:
    print(f"  [OK] 拒绝越权")
elif r.status_code == 200:
    body = r.text
    if guangan_id in body and caifu_id not in body:
        print(f"  [OK] store_id 已强制覆写为广安店")
    elif caifu_id in body and "filter" not in body.lower():
        print(f"  [FAIL] 越权通过！")
    else:
        print(f"  [?] 响应不明确")

# store_owner 传正确ID
print("\n[2] store_owner 正确 - store_id=guangan_id")
r = requests.post(f"{BASE}/api/chat",
    headers={"Authorization": f"Bearer {owner_token}"},
    json={"message": "本店有什么商品？", "store_id": guangan_id, "stream": False},
    timeout=TIMEOUT)
print(f"  HTTP {r.status_code}, body: {r.text[:200]}")

# store_owner 不传store_id
print("\n[3] store_owner 不传store_id")
r = requests.post(f"{BASE}/api/chat",
    headers={"Authorization": f"Bearer {owner_token}"},
    json={"message": "本店有什么商品？", "stream": False},
    timeout=TIMEOUT)
print(f"  HTTP {r.status_code}, body: {r.text[:200]}")

# admin 访问任意
print("\n[4] admin - store_id=caifu_id")
r = requests.post(f"{BASE}/api/chat",
    headers={"Authorization": f"Bearer {admin_token}"},
    json={"message": "本店有什么商品？", "store_id": caifu_id, "stream": False},
    timeout=TIMEOUT)
print(f"  HTTP {r.status_code}, body: {r.text[:200]}")

# 看看 admin 调 run_script 还会不会失败 (Path bug验证)
print("\n[5] admin 触发 run_script（验证Path bug是否彻底修好）")
r = requests.post(f"{BASE}/api/chat",
    headers={"Authorization": f"Bearer {admin_token}"},
    json={"message": "用competitive_analysis脚本分析广安店", "stream": False},
    timeout=TIMEOUT)
print(f"  HTTP {r.status_code}")
print(f"  body (前1000字): {r.text[:1000]}")
if "Path is not defined" in r.text:
    print(f"  [FAIL] Path bug 还在")
elif "Path" in r.text and "error" in r.text.lower():
    print(f"  [WARN] 还有其他Path问题")
else:
    print(f"  [OK] Path bug 已修复或该路径未触发")
