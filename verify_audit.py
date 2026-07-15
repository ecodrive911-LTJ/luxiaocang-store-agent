# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json, requests

BASE = "http://120.26.176.215"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json().get("token")

print("=" * 60)
print("D1-5 操作审计验证")
print("=" * 60)

admin_token = login("luxiaocang", "LXC2025")
owner_token = login("guangan", "guangan123")
print(f"login ok, admin/owner logged in")

# 触发几个 chat
print("\n[触发操作以生成审计日志]")
def stream_chat(token, message, store_id=None, timeout=60):
    payload = {"message": message, "session_id": f"audit_test_{int(__import__('time').time())}"}
    if store_id: payload["store_id"] = store_id
    r = requests.post(f"{BASE}/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json=payload, timeout=timeout, stream=True)
    txt = ""
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                d = json.loads(line[6:])
                if "content" in d: txt += d["content"]
            except: pass
    return txt

print("  - admin 触发 chat")
stream_chat(admin_token, "请简述门店情况")
print("  - owner 触发 chat")
stream_chat(owner_token, "本店有什么商品")
print("  - admin 越权 (不会被允许,但被记录)")
stream_chat(admin_token, "请扫描商圈", store_id="2d8d867e-57b0-4389-a103-0083990b002f")

# 查询审计
print("\n[1] admin 查询审计日志")
r = requests.get(f"{BASE}/api/audit/logs?limit=10",
    headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
print(f"  HTTP {r.status_code}")
data = r.json()
logs = data.get("logs", [])
print(f"  日志条数: {len(logs)}")
for l in logs[:5]:
    print(f"  - [{l.get('action')}] {l.get('username')}({l.get('role')}) resource={l.get('resource_type')}/{l.get('resource_id', '')[:20]}")

print("\n[2] owner 越权查询审计 (应该被拒绝)")
r = requests.get(f"{BASE}/api/audit/logs?limit=10",
    headers={"Authorization": f"Bearer {owner_token}"}, timeout=10)
print(f"  HTTP {r.status_code}, body: {r.text[:200]}")
if r.status_code == 403:
    print(f"  [OK] owner 被拒绝 (403)")

print("\n[3] admin 查审计统计")
r = requests.get(f"{BASE}/api/audit/stats",
    headers={"Authorization": f"Bearer {admin_token}"}, timeout=10)
print(f"  HTTP {r.status_code}, body: {r.text[:300]}")

print("\n" + "=" * 60)
print("D1-5 验证完毕")
print("=" * 60)
