"""
D1+D2 自主验证脚本
- 登录 admin (luxiaocang) + 登录 store_owner (guangan)
- 截图保存
- 抽取关键UI元素，输出对比报告
"""
import os
import time
import json
import subprocess
import sys

BASE = "http://120.26.176.215"
SHOTS_DIR = r"C:\Users\13522\diancanmou\verification_shots"
os.makedirs(SHOTS_DIR, exist_ok=True)

# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Step 1: API层验证 - 登录admin / 登录store_owner
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

def api_login(username, password):
    """通过API登录，返回token + cookies"""
    data = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if "token" in result:
            return result["token"], result.get("user", {})
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()}"
    return None, "no token"

def api_get(path, token):
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()}

def api_post(path, token, data):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()}

print("=" * 60)
print("D1 + D2 自主验证报告")
print("=" * 60)

# === Test 1: admin login ===
print("\n[Test 1] admin (luxiaocang) 登录")
admin_token, admin_info = api_login("luxiaocang", "LXC2025")
if admin_token:
    print(f"  ✓ 登录成功, role={admin_info.get('role')}, user_id={admin_info.get('id')[:8]}...")
else:
    print(f"  ✗ 失败: {admin_info}")
    sys.exit(1)

# === Test 2: store_owner login ===
print("\n[Test 2] store_owner (guangan) 登录")
owner_token, owner_info = api_login("guangan", "guangan123")
if owner_token:
    print(f"  ✓ 登录成功, role={owner_info.get('role')}, user_id={owner_info.get('id')[:8]}...")
else:
    print(f"  ✗ 失败: {owner_info}")
    sys.exit(1)

# === Test 3: D1-2 数据资产 API 隔离验证 ===
print("\n[Test 3] /api/data/assets 角色隔离")
admin_assets = api_get("/api/data/assets", admin_token)
owner_assets = api_get("/api/data/assets", owner_token)
print(f"  admin assets keys: {list(admin_assets.keys()) if isinstance(admin_assets, dict) else admin_assets}")
print(f"  owner assets keys: {list(owner_assets.keys()) if isinstance(owner_assets, dict) else owner_assets}")
if isinstance(admin_assets, dict) and isinstance(owner_assets, dict):
    # 检查数据是否不同
    admin_json = json.dumps(admin_assets, sort_keys=True, ensure_ascii=False)
    owner_json = json.dumps(owner_assets, sort_keys=True, ensure_ascii=False)
    if admin_json != owner_json:
        print(f"  ✓ 数据已隔离（admin vs owner 响应不同）")
    else:
        print(f"  ✗ 数据相同，未隔离")

# === Test 4: D1-4 store_owner 强制 store_id 绑定 ===
print("\n[Test 4] /api/chat 强制 store_id 绑定（store_owner尝试访问别的门店）")
# 财富店 id 是 2d8d867e-57b0-4389-a103-0083990b002f
caifu_id = "2d8d867e-57b0-4389-a103-0083990b002f"
guangan_id = "f67b4c21-2529-4d96-a2e8-0749451e5295"
# owner尝试传财富店id
result = api_post("/api/chat", owner_token, {
    "message": "这个店有什么商品？",
    "store_id": caifu_id  # owner实际绑定的是广安店
})
print(f"  owner请求 (传caifu_id) 响应: {json.dumps(result, ensure_ascii=False)[:300]}")
# owner应该被强制覆写为广安店；如果错误码是403说明隔离生效；成功则说明覆写生效
if "error" in result:
    if "403" in str(result):
        print(f"  ✓ 拒绝越权访问（403）")
    else:
        print(f"  ⚠️ 错误: {result.get('body', result)[:200]}")
else:
    # 成功 - 验证store_id是否被覆写
    print(f"  → 请求通过，store_id 应被强制覆写为广安店")
    if "store_id" in str(result):
        if guangan_id in str(result) and caifu_id not in str(result):
            print(f"  ✓ store_id 已强制覆写为广安店")

# === Test 5: 数据权限越权（store_owner访问竞品数据）===
print("\n[Test 5] store_owner 访问竞品数据应该受限")
# 试试访问竞品数据接口（如果有）
result = api_get("/api/data/assets?type=competitors", owner_token)
print(f"  owner访问竞品数据: {str(result)[:200]}")

# === Test 6: D2-3 上传后触发AI分析 (无文件，跳过实际文件上传，验证API) ===
print("\n[Test 6] D2 视频上传接口存在性")
# 看下是否需要先有 task
# 假设有 task
# 先创建测试 task
print(f"  (需配合任务系统，单独验证)")

# === 总结 ===
print("\n" + "=" * 60)
print("API层验证完毕")
print("=" * 60)

# 保存 token 给浏览器验证用
with open(r"C:\Users\13522\diancanmou\verification_tokens.json", "w") as f:
    json.dump({
        "admin_token": admin_token,
        "admin_user": admin_info,
        "owner_token": owner_token,
        "owner_user": owner_info
    }, f, indent=2, ensure_ascii=False)

print(f"\nTokens saved for browser verification.")
