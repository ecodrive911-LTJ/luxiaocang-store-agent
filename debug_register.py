import requests
BASE = "http://120.26.176.215"
t = requests.post(f"{BASE}/api/auth/login", json={"username": "luxiaocang", "password": "LXC2025"}).json()["token"]
print("admin token:", t[:20])
h = {"Authorization": f"Bearer {t}"}
print("me:", requests.get(f"{BASE}/api/auth/me", headers=h).text[:300])
r = requests.post(f"{BASE}/api/auth/register", json={"username": "manager_e2e2", "password": "MgrE2E2025", "role": "manager", "display_name": "测试经理"}, headers=h)
print("register manager:", r.status_code, r.text[:300])
r2 = requests.post(f"{BASE}/api/auth/register", json={"username": "owner_e2e2", "password": "OwnerE2E2025", "role": "store_owner", "display_name": "测试店主"}, headers=h)
print("register owner:", r2.status_code, r2.text[:300])
