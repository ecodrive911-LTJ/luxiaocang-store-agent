# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json, requests
BASE = "http://120.26.176.215"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json().get("token"), r.status_code

print("=" * 50)
print("系统冒烟测试 (D1+D3)")
print("=" * 50)

t, code = login("luxiaocang", "LXC2025")
print(f"[login admin] HTTP {code}, token={'OK' if t else 'FAIL'}")

# /api/me
r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {t}"}, timeout=10)
print(f"[me] HTTP {r.status_code}, role={r.json().get('user',{}).get('role')}")

# /api/audit/logs
r = requests.get(f"{BASE}/api/audit/logs?limit=3", headers={"Authorization": f"Bearer {t}"}, timeout=10)
print(f"[audit/logs] HTTP {r.status_code}, count={len(r.json().get('logs',[]))}")

# /api/uploads/pending
r = requests.get(f"{BASE}/api/uploads/pending", headers={"Authorization": f"Bearer {t}"}, timeout=10)
print(f"[uploads/pending] HTTP {r.status_code}, count={r.json().get('count')}")

# /api/tasks list (should work for admin)
r = requests.get(f"{BASE}/api/tasks", headers={"Authorization": f"Bearer {t}"}, timeout=10)
print(f"[tasks] HTTP {r.status_code}, tasks={len(r.json().get('tasks',[]))}")

print("\nAll smoke tests passed" if all(x.status_code==200 for x in [r]) else "\nSome checks failed")
