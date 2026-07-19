"""线上验证盈利引擎 - 5步链路步骤4"""
import requests

BASE = "http://120.26.176.215"

# 登录 store_owner（guangan）
print("=== 登录 guangan ===")
r = requests.post(f"{BASE}/api/auth/login", json={"username": "guangan", "password": "guangan123"})
print(f"Status: {r.status_code}")
data = r.json()
token = data.get("token")
print(f"Token: {token[:20]}...")
headers = {"Authorization": f"Bearer {token}"}

# 获取门店ID
r = requests.get(f"{BASE}/api/auth/me", headers=headers)
user_data = r.json()
store_id = user_data.get("store_id")
print(f"Store ID: {store_id}")

# 场景1：2km 正常订单
print("\n=== 场景1：2km正常订单 ingest ===")
r = requests.post(f"{BASE}/api/profit_engine/ingest", headers=headers, json={
    "store_id": store_id,
    "order_id": "ONLINE_TEST_001",
    "items": [{"name": "可口可乐330ml", "quantity": 6, "price": 3.5, "cost": 1.8}],
    "distance_km": 2.0,
    "platform_commission_rate": 0.18
})
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# 场景2：6km 远距离订单
print("\n=== 场景2：6km远距离订单 ingest ===")
r = requests.post(f"{BASE}/api/profit_engine/ingest", headers=headers, json={
    "store_id": store_id,
    "order_id": "ONLINE_TEST_002",
    "items": [{"name": "矿泉水", "quantity": 2, "price": 3.0, "cost": 1.2}],
    "distance_km": 6.0,
    "platform_commission_rate": 0.18
})
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# 场景3：聊天 - 让AI评估一笔订单
print("\n=== 场景3：对话测试 - 盈利评估 ===")
r = requests.post(f"{BASE}/api/chat", headers=headers, json={
    "store_id": store_id,
    "message": "有一单可口可乐330ml，6瓶，3.5元一瓶，进价1.8元，配送距离2公里，美团抽佣18%，帮我算算这笔单赚不赚？",
})
print(f"Status: {r.status_code}")
# 提取AI回复（SSE格式，取最后一条）
content = r.text
for line in content.split('\n'):
    if line.startswith('data: ') and '"type":"final"' in line:
        print(f"AI回复: {line[:500]}")
        break
else:
    # 如果没找到final，打印最后500字符
    print(f"Response (last 500): {content[-500:]}")

print("\n✅ 线上验证完成")
