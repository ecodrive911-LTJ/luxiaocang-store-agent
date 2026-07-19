"""
P0 线上验证 - 盈利引擎修复验证
1. guangan 用户门店关联验证
2. OrderFeedItem 字段名修复验证（/api/profit_engine/ingest）
"""
import requests
import time

BASE = "http://120.26.176.215"

# ===== Test 1: guangan 用户门店关联 =====
print("=" * 50)
print("Test 1: guangan 用户门店关联")
print("=" * 50)

r = requests.post(f"{BASE}/api/auth/login", json={"username": "guangan", "password": "guangan123"})
print(f"  登录状态: {r.status_code}")
if r.status_code != 200:
    print(f"  [FAIL] 登录失败: {r.text[:200]}")
    exit(1)

data = r.json()
token = data.get("token")
user_info = data.get("user", {})
print(f"  用户: {user_info.get('username')}, 角色: {user_info.get('role')}, ID: {user_info.get('id', '')[:8]}...")

# 检查 /api/auth/me
r2 = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
print(f"  /api/auth/me 状态: {r2.status_code}")
me_data = r2.json()
stores = me_data.get("stores", [])
print(f"  关联门店数: {len(stores)}")
if stores:
    for s in stores:
        print(f"    - {s.get('name')} (id: {s.get('id', '')[:8]}...)")
    store_id = stores[0]["id"]
    print(f"  [OK] guangan 已关联门店: {stores[0].get('name')}")
else:
    print(f"  [FAIL] guangan 未关联任何门店")
    store_id = None

# ===== Test 2: /api/profit_engine/ingest 字段名修复 =====
print()
print("=" * 50)
print("Test 2: /api/profit_engine/ingest 字段名修复")
print("=" * 50)

if not store_id:
    print("  [SKIP] 无 store_id，跳过")
else:
    payload = {
        "store_id": store_id,
        "order_id": f"test_fix_{int(time.time())}",
        "items": [
            {"sku_name": "可口可乐330ml", "sell_price": 3.0, "purchase_cost": 1.2, "quantity": 6},
            {"sku_name": "乐事薯片原味", "sell_price": 7.5, "purchase_cost": 4.0, "quantity": 2}
        ],
        "distance_km": 2.5,
        "platform_commission_rate": 0.18
    }
    
    r3 = requests.post(
        f"{BASE}/api/profit_engine/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {token}"}
    )
    print(f"  ingest 状态: {r3.status_code}")
    if r3.status_code == 200:
        result = r3.json()
        print(f"  结果: ok={result.get('ok')}, order_id={result.get('order_id')}")
        eval_result = result.get("result", {})
        print(f"  净利: {eval_result.get('net_profit')}元, 状态: {eval_result.get('status')}")
        print(f"  [OK] ingest 接口正常，字段名匹配成功")
    else:
        print(f"  [FAIL] {r3.text[:300]}")

# ===== Test 3: dashboard 验证数据已写入 =====
print()
print("=" * 50)
print("Test 3: dashboard 验证数据已写入")
print("=" * 50)

r4 = requests.post(
    f"{BASE}/api/chat",
    json={"message": "最近3天盈利情况怎么样", "store_id": store_id, "session_id": "p0_verify"},
    headers={"Authorization": f"Bearer {token}"},
    stream=True
)
print(f"  chat 状态: {r4.status_code}")
full_text = ""
if r4.status_code == 200:
    for chunk in r4.iter_content(chunk_size=None, decode_unicode=True):
        if chunk:
            full_text += chunk
    # 检查是否提到盈利数据
    if "净利" in full_text or "盈利" in full_text or "亏损" in full_text or "保本" in full_text:
        print(f"  [OK] Agent 返回了盈利相关数据")
    else:
        print(f"  [WARN] Agent 响应未包含盈利关键词")
    print(f"  响应前200字: {full_text[:200]}")
else:
    print(f"  [FAIL] {r4.text[:200]}")

print()
print("=" * 50)
print("验证完成")
print("=" * 50)
