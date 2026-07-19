"""动态盈利引擎集成测试"""
import sqlite3
import time
import os
import sys
from pathlib import Path

# 确保可以导入项目文件
sys.path.insert(0, str(Path(__file__).parent))

from profit_tools import evaluate_order, get_store_dashboard, simulate_price_change, simulate_delivery_strategy, set_current_store

# 测试门店
TEST_STORE_ID = "test_store_profit_engine"

def test_evaluate_order():
    """测试工具 1：evaluate_order"""
    print("\n=== 测试 evaluate_order ===")
    
    # 设置测试门店
    set_current_store(TEST_STORE_ID)
    
    # 场景 1：正常订单（合理客单价 50 元左右，近距离）
    result = evaluate_order(
        order_id="TEST001",
        items=[
            {"sku_name": "牛奶箱装", "sell_price": 28.0, "purchase_cost": 18.0, "quantity": 1},
            {"sku_name": "零食大礼包", "sell_price": 22.0, "purchase_cost": 12.0, "quantity": 1},
        ],
        delivery_distance_km=2.5,
        platform_commission_rate=0.18
    )
    print(f"正常订单 2.5km: {result}")
    assert result['status'] == '盈利', f"Expected 盈利, got {result['status']}"

    # 场景 2：远距离高配送费订单（同样商品但 6km，配送费 9.5 元）
    result = evaluate_order(
        order_id="TEST002",
        items=[
            {"sku_name": "矿泉水", "sell_price": 3.0, "purchase_cost": 1.2, "quantity": 2},
        ],
        delivery_distance_km=6.0,
        platform_commission_rate=0.18
    )
    print(f"远距离小单 6km: {result}")
    assert result['status'] == '亏损', f"Expected 亏损, got {result['status']}"
    
    print("✓ evaluate_order 测试通过（数据在 main 结束后统一清理）")


def test_get_store_dashboard():
    """测试工具 2：get_store_dashboard"""
    print("\n=== 测试 get_store_dashboard ===")
    
    # 设置测试门店
    set_current_store(TEST_STORE_ID)
    
    # 先插入一些测试数据（使用正确的列名）
    conn = sqlite3.connect("database.db", timeout=10)
    c = conn.cursor()
    
    now = time.time()
    for i in range(10):
        c.execute(
            """INSERT INTO profit_order_feed 
               (store_id, order_id, total_revenue, total_cost, gross_profit,
                platform_commission, delivery_cost, fulfillment_cost, net_profit,
                distance_km, commission_rate, items_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (TEST_STORE_ID, f"DASH_TEST_{i}", 50, 30, 20, 9, 5, 1.5, 4.5, 2.5, 0.18, "[]", now - i * 3600)
        )
    
    conn.commit()
    conn.close()
    
    # 等 evaluate_order 的连接完全释放（Windows SQLite 锁延迟）
    time.sleep(1)

    # 查询 dashboard
    result = get_store_dashboard(daily_profit_target=100)
    print(f"Dashboard: {result}")
    assert result['period_days'] == 3
    assert result['total_orders_3d'] >= 10, f"Expected at least 10 orders, got {result['total_orders_3d']}"
    
    print("✓ get_store_dashboard 测试通过")

def _cleanup_all_test_data():
    """测试结束后统一清理所有测试数据"""
    import time as _time
    # 给 SQLite 一点时间释放锁
    _time.sleep(0.2)
    conn = sqlite3.connect("database.db", timeout=10)
    c = conn.cursor()
    try:
        c.execute("DELETE FROM profit_order_feed WHERE order_id LIKE 'TEST%'")
        c.execute("DELETE FROM profit_order_feed WHERE order_id LIKE 'DASH_TEST_%'")
        conn.commit()
        print("\n✓ 测试数据已清理")
    finally:
        conn.close()


def test_simulate_price_change():
    """测试工具 3：simulate_price_change"""
    print("\n=== 测试 simulate_price_change ===")
    
    result = simulate_price_change(
        sku_name="矿泉水",
        current_price=3.0,
        purchase_cost=1.2,
        price_delta=0.5,
        estimated_volume_change_pct=-5
    )
    print(f"涨价 0.5 元: {result}")
    assert 'profit_change_3d' in result
    assert 'break_even_orders_change' in result
    
    print("✓ simulate_price_change 测试通过")

def test_simulate_delivery_strategy():
    """测试工具 4：simulate_delivery_strategy"""
    print("\n=== 测试 simulate_delivery_strategy ===")
    
    result = simulate_delivery_strategy(
        avg_gross_margin=0.25,
        platform_commission_rate=0.18
    )
    print(f"配送策略: {result}")
    assert 'strategies' in result
    assert len(result['strategies']) == 5  # 2km, 3km, 4km, 5km, 6km
    
    print("✓ simulate_delivery_strategy 测试通过")

def main():
    print("=" * 60)
    print("动态盈利引擎集成测试")
    print("=" * 60)
    
    # 检查数据库
    db_path = Path("database.db")
    if not db_path.exists():
        print("❌ database.db 不存在，请先启动一次 app.py 初始化数据库")
        return
    
    # 开启 WAL 模式（解决 Windows 下 SQLite 文件锁问题）
    conn = sqlite3.connect("database.db", timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM profit_order_feed LIMIT 1")
        print("✓ profit_order_feed 表存在")
    except sqlite3.OperationalError:
        print("→ profit_order_feed 表不存在，测试脚本自行创建...")
        c.execute("""CREATE TABLE IF NOT EXISTS profit_order_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT NOT NULL, order_id TEXT NOT NULL,
            total_revenue REAL NOT NULL, total_cost REAL NOT NULL,
            gross_profit REAL NOT NULL, platform_commission REAL NOT NULL,
            delivery_cost REAL NOT NULL, fulfillment_cost REAL NOT NULL,
            net_profit REAL NOT NULL, distance_km REAL NOT NULL,
            commission_rate REAL NOT NULL, items_json TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pof_store_time ON profit_order_feed(store_id, created_at)")
        conn.commit()
        print("✓ profit_order_feed 表已创建")
    conn.close()
    
    # 运行测试
    test_evaluate_order()
    test_get_store_dashboard()
    test_simulate_price_change()
    test_simulate_delivery_strategy()
    
    # 统一清理测试数据
    _cleanup_all_test_data()
    
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)

if __name__ == "__main__":
    main()
