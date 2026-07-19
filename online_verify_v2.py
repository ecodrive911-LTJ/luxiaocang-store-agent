"""线上验证盈利引擎 - 排查门店关联"""
import requests

BASE = "http://120.26.176.215"

# 1. 用 admin 登录
print("=== admin 登录 ===")
r = requests.post(f"{BASE}/api/auth/login", json={"username": "luxiaocang", "password": "LXC2025"})
token = r.json()["token"]
admin_h = {"Authorization": f"Bearer {token}"}

# 2. 查所有门店
print("\n=== 查所有门店 ===")
r = requests.get(f"{BASE}/api/stores", headers=admin_h)
print(f"Status: {r.status_code}")
stores = r.json()
print(f"Stores: {stores}")

# 3. 查 guangan 用户信息
print("\n=== 查用户列表 ===")
r = requests.get(f"{BASE}/api/users", headers=admin_h)
print(f"Status: {r.status_code}")
users = r.json()
for u in users:
    if "guangan" in u.get("username", ""):
        print(f"guangan user: {u}")

# 4. 查 guangan 的 user_stores 关联
print("\n=== 查 user_stores ===")
r = requests.get(f"{BASE}/api/user_stores", headers=admin_h)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    print(f"user_stores: {r.json()}")
else:
    print(r.text[:300])

# 5. 用 guangan 登录看 /api/auth/me 返回什么
print("\n=== guangan 登录 ===")
r = requests.post(f"{BASE}/api/auth/login", json={"username": "guangan", "password": "guangan123"})
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")
