# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import json, requests
BASE = "http://120.26.176.215"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p}, timeout=10)
    return r.json().get("token")

print("=" * 50)
print("D3-2 比价矩阵端点验证")
print("=" * 50)

admin = login("luxiaocang", "LXC2025")
print(f"[login admin] token={'OK' if admin else 'FAIL'}")

# 查门店列表拿 store_id
r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {admin}"}, timeout=10)
stores = r.json().get("user", {}).get("stores", [])
print(f"[me] stores={[s.get('name') for s in stores]}")

# 测 /api/price/matrix (不指定 store，取第一个)
r = requests.get(f"{BASE}/api/price/matrix", headers={"Authorization": f"Bearer {admin}"}, timeout=15)
print(f"\n[1] admin /api/price/matrix -> HTTP {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"    store_id={d.get('store_id')} store_name={d.get('store_name')}")
    m = d.get("matrix", [])
    print(f"    matrix 商品数: {len(m)}")
    for item in m[:3]:
        print(f"    - {item['product_name']}: 低¥{item['tier_low']} 中¥{item['tier_mid']} 高¥{item['tier_high']} (竞品{item['competitor_count']}个)")
    if not m:
        print("    (price_data 表为空，端点正常返回空矩阵)")
else:
    print(f"    [FAIL] {r.text[:200]}")

# store_owner 隔离测试
owner = login("guangan", "guangan123")
# 拿 guangan 的 store_id
r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {owner}"}, timeout=10)
owner_stores = r.json().get("user", {}).get("stores", [])
owner_sid = owner_stores[0]["id"] if owner_stores else ""
r = requests.get(f"{BASE}/api/price/matrix?store_id={owner_sid}", headers={"Authorization": f"Bearer {owner}"}, timeout=15)
print(f"\n[2] owner /api/price/matrix (自身门店) -> HTTP {r.status_code}")
print(f"    {'[OK] 正常返回' if r.status_code==200 else '[FAIL] '+r.text[:100]}")

print("\n" + "=" * 50)
print("D3-2 验证完毕")
print("=" * 50)
