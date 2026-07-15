# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json, requests
BASE = "http://120.26.176.215"

def login(u, p):
    return requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p}, timeout=10).json().get("token")

admin = login("luxiaocang", "LXC2025")
owner = login("guangan", "guangan123")

print("=" * 50)
print("D3-1 上传复核接口验证")
print("=" * 50)

# [1] owner 越权访问复核 (应该被 403)
r = requests.get(f"{BASE}/api/uploads/pending", headers={"Authorization": f"Bearer {owner}"}, timeout=10)
print(f"[1] owner /uploads/pending -> HTTP {r.status_code}")
print(f"    {'[OK] 被拒绝' if r.status_code==403 else '[FAIL] 未拒绝: '+r.text[:100]}")

# [2] admin 查待复核 (应该返回空列表, 因为没有上传)
r = requests.get(f"{BASE}/api/uploads/pending", headers={"Authorization": f"Bearer {admin}"}, timeout=10)
print(f"[2] admin /uploads/pending -> HTTP {r.status_code}")
d = r.json()
print(f"    待复核条数: {d.get('count', 0)}")

# [3] admin 查不存在的上传复查 (应该 404)
r = requests.get(f"{BASE}/api/uploads/nonexistent/review", headers={"Authorization": f"Bearer {admin}"}, timeout=10)
print(f"[3] admin /uploads/nonexistent/review -> HTTP {r.status_code}")
print(f"    {'[OK] 404' if r.status_code==404 else '[FAIL] '+str(r.status_code)}")

# [4] owner 尝试确认 (应该 403)
r = requests.post(f"{BASE}/api/uploads/fake/confirm", headers={"Authorization": f"Bearer {owner}"}, json={"confirm": True, "correction": {}}, timeout=10)
print(f"[4] owner /uploads/fake/confirm -> HTTP {r.status_code}")
print(f"    {'[OK] 被拒绝' if r.status_code==403 else '[FAIL] 未拒绝'}")

# [5] owner 尝试重分析 (应该 403)
r = requests.post(f"{BASE}/api/uploads/fake/reprocess", headers={"Authorization": f"Bearer {owner}"}, json={}, timeout=10)
print(f"[5] owner /uploads/fake/reprocess -> HTTP {r.status_code}")
print(f"    {'[OK] 被拒绝' if r.status_code==403 else '[FAIL] 未拒绝'}")

print("\n" + "=" * 50)
print("D3-1 后端验证完毕")
print("=" * 50)
