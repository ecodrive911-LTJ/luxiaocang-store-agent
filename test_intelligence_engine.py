"""
竞品情报分析引擎 - 集成测试
测试5个工具的完整链路，含文件5中的测试对话场景
"""
import sys
import json
import sqlite3
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from intelligence_tools import (
    map_competitor_sku,
    compare_price_matrix,
    reverse_engineer_strategy,
    generate_counter_strategy,
    detect_market_gap
)

# ========== 测试配置 ==========
TEST_STORE_ID = "test_store_001"
TEST_COMPETITOR_NAME = "XX便利店(朝阳路店)"

# ========== 数据库初始化 ==========
DB_PATH = Path(__file__).parent / "database.db"


def init_test_db():
    """初始化测试数据库"""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    c = conn.cursor()

    # 先建表（确保表存在），再清理测试数据
    c.execute("""CREATE TABLE IF NOT EXISTS stores (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT, city TEXT,
        district TEXT, owner_id TEXT NOT NULL, created_at REAL,
        FOREIGN KEY (owner_id) REFERENCES users(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS competitor_stores (
        id TEXT PRIMARY KEY, store_id TEXT NOT NULL, competitor_name TEXT NOT NULL,
        platform TEXT, monthly_sales INTEGER, rating REAL, min_order_amount REAL,
        base_delivery_fee REAL, delivery_time_minutes INTEGER, business_hours TEXT,
        delivery_distance_max REAL, created_at REAL, updated_at REAL,
        FOREIGN KEY (store_id) REFERENCES stores(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS competitor_skus (
        id TEXT PRIMARY KEY, competitor_store_id TEXT NOT NULL, sku_name TEXT NOT NULL,
        category TEXT, brand TEXT, spec TEXT, package_type TEXT,
        original_price REAL, sell_price REAL, activity_price REAL,
        monthly_sales INTEGER, stock_status TEXT DEFAULT '有货', is_new INTEGER DEFAULT 0,
        main_image_url TEXT, created_at REAL, updated_at REAL,
        FOREIGN KEY (competitor_store_id) REFERENCES competitor_stores(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS competitor_promotions (
        id TEXT PRIMARY KEY, competitor_store_id TEXT NOT NULL, promo_type TEXT NOT NULL,
        detail TEXT NOT NULL, applicable_categories TEXT, start_time TEXT, end_time TEXT,
        created_at REAL, FOREIGN KEY (competitor_store_id) REFERENCES competitor_stores(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sku_mappings (
        id TEXT PRIMARY KEY, store_id TEXT NOT NULL, competitor_store_id TEXT NOT NULL,
        our_sku_name TEXT NOT NULL, competitor_sku_name TEXT NOT NULL,
        confidence REAL NOT NULL, status TEXT NOT NULL DEFAULT 'mapped',
        created_at REAL, updated_at REAL,
        FOREIGN KEY (store_id) REFERENCES stores(id),
        FOREIGN KEY (competitor_store_id) REFERENCES competitor_stores(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS strategy_analyses (
        id TEXT PRIMARY KEY, store_id TEXT NOT NULL, competitor_store_id TEXT NOT NULL,
        analysis_type TEXT NOT NULL, result_json TEXT NOT NULL, created_at REAL,
        FOREIGN KEY (store_id) REFERENCES stores(id),
        FOREIGN KEY (competitor_store_id) REFERENCES competitor_stores(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS profit_order_feed (
        id INTEGER PRIMARY KEY AUTOINCREMENT, store_id TEXT NOT NULL, order_id TEXT NOT NULL,
        total_revenue REAL NOT NULL, total_cost REAL NOT NULL, gross_profit REAL NOT NULL,
        platform_commission REAL NOT NULL, delivery_cost REAL NOT NULL,
        fulfillment_cost REAL NOT NULL, net_profit REAL NOT NULL,
        distance_km REAL NOT NULL, commission_rate REAL NOT NULL,
        items_json TEXT, created_at REAL NOT NULL,
        FOREIGN KEY (store_id) REFERENCES stores(id)
    )""")

    # 创建测试门店
    c.execute("""INSERT OR IGNORE INTO stores 
                 (id, name, owner_id, created_at) 
                 VALUES (?, ?, ?, ?)""",
              (TEST_STORE_ID, "测试便利店", "test_user", time.time()))

    # 清空测试数据
    c.execute("DELETE FROM competitor_stores WHERE store_id=?", (TEST_STORE_ID,))
    c.execute("DELETE FROM competitor_skus WHERE competitor_store_id IN (SELECT id FROM competitor_stores WHERE store_id=?)", (TEST_STORE_ID,))
    c.execute("DELETE FROM competitor_promotions WHERE competitor_store_id IN (SELECT id FROM competitor_stores WHERE store_id=?)", (TEST_STORE_ID,))
    c.execute("DELETE FROM sku_mappings WHERE store_id=?", (TEST_STORE_ID,))
    c.execute("DELETE FROM strategy_analyses WHERE store_id=?", (TEST_STORE_ID,))
    c.execute("DELETE FROM profit_order_feed WHERE store_id=?", (TEST_STORE_ID,))

    # 插入测试订单数据（模拟我方商品）
    test_orders = [
        {
            "order_id": "test_order_1",
            "items": [
                {"sku_name": "可口可乐330ml罐装", "sell_price": 3.0, "purchase_cost": 1.2, "quantity": 2},
                {"sku_name": "农夫山泉550ml瓶装", "sell_price": 2.5, "purchase_cost": 1.0, "quantity": 1},
                {"sku_name": "康师傅冰红茶500ml", "sell_price": 4.0, "purchase_cost": 2.0, "quantity": 1}
            ]
        },
        {
            "order_id": "test_order_2",
            "items": [
                {"sku_name": "可口可乐330ml罐装", "sell_price": 3.0, "purchase_cost": 1.2, "quantity": 3},
                {"sku_name": "乐事薯片75g", "sell_price": 8.0, "purchase_cost": 5.0, "quantity": 1}
            ]
        }
    ]

    for order in test_orders:
        c.execute("""INSERT INTO profit_order_feed
                     (store_id, order_id, total_revenue, total_cost, gross_profit,
                      platform_commission, delivery_cost, fulfillment_cost, net_profit,
                      distance_km, commission_rate, items_json, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (TEST_STORE_ID, order["order_id"],
                   sum(it["sell_price"] * it["quantity"] for it in order["items"]),
                   sum(it["purchase_cost"] * it["quantity"] for it in order["items"]),
                   sum((it["sell_price"] - it["purchase_cost"]) * it["quantity"] for it in order["items"]),
                   0, 0, 0, 0, 0, 0, json.dumps(order["items"], ensure_ascii=False), time.time()))

    conn.commit()
    conn.close()
    print("✓ 测试数据库初始化完成")


# ========== 测试用例 ==========

def test_1_map_competitor_sku():
    """测试1：商品映射"""
    print("\n===== 测试1：map_competitor_sku =====")
    
    competitor_skus = [
        {"sku_name": "可口可乐330ml罐装", "sell_price": 1.5, "category": "碳酸饮料", "brand": "可口可乐", "spec": "330ml", "package": "罐装"},
        {"sku_name": "农夫山泉550ml瓶装", "sell_price": 2.0, "category": "矿泉水", "brand": "农夫山泉", "spec": "550ml", "package": "瓶装"},
        {"sku_name": "雪碧330ml罐装", "sell_price": 1.8, "category": "碳酸饮料", "brand": "雪碧", "spec": "330ml", "package": "罐装"}
    ]
    
    result = map_competitor_sku(
        competitor_name=TEST_COMPETITOR_NAME,
        competitor_skus=competitor_skus,
        store_id=TEST_STORE_ID
    )
    
    print(f"竞品ID: {result['competitor_id']}")
    print(f"竞品名称: {result['competitor_name']}")
    print(f"总SKU数: {result['total_competitor_skus']}")
    print(f"映射汇总: 自动{result['summary']['auto_mapped']}个, 待审{result['summary']['pending_review']}个, 独有{result['summary']['our_unique']}个")
    
    for m in result["mappings"]:
        print(f"  - {m['competitor_sku']} → {m['our_sku']} (置信度{m['confidence']}, {m['status']})")
    
    assert result["total_competitor_skus"] == 3
    assert result["competitor_id"] is not None
    print("✓ 测试1通过")
    return result["competitor_id"]


def test_2_compare_price_matrix(competitor_id: str):
    """测试2：价格对比矩阵"""
    print("\n===== 测试2：compare_price_matrix =====")
    
    result = compare_price_matrix(
        competitor_id=competitor_id,
        store_id=TEST_STORE_ID
    )
    
    print(f"对比商品数: {result['total_items_compared']}")
    print(f"整体价格指数: {result['avg_price_index']} (>100我方偏贵, <100我方便宜)")
    
    if result.get("matrix"):
        for item in result["matrix"][:3]:  # 只显示前3个
            print(f"  - {item['our_sku']}: 我方{item['our_price']}元 vs 竞品{item['competitor_price']}元 (价差{item['price_diff_pct']}%)")
    
    if result.get("significant_items"):
        print(f"显著差异项: {len(result['significant_items'])}个")
    
    print("✓ 测试2通过")


def test_3_reverse_engineer_strategy(competitor_id: str):
    """测试3：策略反推"""
    print("\n===== 测试3：reverse_engineer_strategy =====")
    
    promotions = [
        {"type": "满减", "detail": "满39减5"},
        {"type": "满减", "detail": "满69减12"},
        {"type": "新客", "detail": "新客立减8元"}
    ]
    
    result = reverse_engineer_strategy(
        competitor_id=competitor_id,
        store_id=TEST_STORE_ID,
        promotions=promotions
    )
    
    print(f"分析ID: {result['analysis_id']}")
    print(f"整体策略: {result['overall_strategy']['overall_strategy']}")
    print(f"策略描述: {result['overall_strategy']['description']}")
    
    print("\nSKU角色分析:")
    for role in result["sku_role_analysis"][:3]:
        print(f"  - {role['sku_name']}: {role['role_label']} (估计毛利率{role['est_margin']*100:.1f}%)")
    
    print("\n活动意图分析:")
    for intent in result["promotion_intent_analysis"]:
        print(f"  - {intent['type']}: {intent['intent']} - {intent['explanation']}")
    
    print("✓ 测试3通过")


def test_4_generate_counter_strategy(competitor_id: str):
    """测试4：生成应对方案"""
    print("\n===== 测试4：generate_counter_strategy =====")
    
    my_cost_data = [
        {"sku_name": "可口可乐330ml罐装", "purchase_cost": 1.2, "current_price": 3.0},
        {"sku_name": "农夫山泉550ml瓶装", "purchase_cost": 1.0, "current_price": 2.5},
        {"sku_name": "康师傅冰红茶500ml", "purchase_cost": 2.0, "current_price": 4.0}
    ]
    
    result = generate_counter_strategy(
        competitor_id=competitor_id,
        store_id=TEST_STORE_ID,
        my_cost_data=my_cost_data
    )
    
    print(f"分析ID: {result['analysis_id']}")
    
    print("\n【进攻方案】")
    print(f"策略: {result['attack_plan']['strategy']}")
    print(f"整体风险: {result['attack_plan']['overall_risk']}")
    print(f"预期效果: {result['attack_plan']['expected_effect']}")
    for action in result["attack_plan"]["actions"][:2]:
        print(f"  - {action.get('sku', '全店')}: {action['action']}")
    
    print("\n【防守方案】")
    print(f"策略: {result['defend_plan']['strategy']}")
    print(f"整体风险: {result['defend_plan']['overall_risk']}")
    for action in result["defend_plan"]["actions"][:2]:
        print(f"  - {action.get('sku', '全店')}: {action['action']}")
    
    print("\n【回避方案】")
    print(f"策略: {result['avoid_plan']['strategy']}")
    print(f"整体风险: {result['avoid_plan']['overall_risk']}")
    for action in result["avoid_plan"]["actions"][:2]:
        print(f"  - {action.get('sku', '全店')}: {action['action']}")
    
    print("✓ 测试4通过")


def test_5_detect_market_gap(competitor_id: str):
    """测试5：市场空白检测"""
    print("\n===== 测试5：detect_market_gap =====")
    
    result = detect_market_gap(
        competitor_id=competitor_id,
        store_id=TEST_STORE_ID
    )
    
    print(f"发现机会: {result['total_gaps_found']}个")
    
    if result.get("gaps"):
        for gap in result["gaps"][:3]:
            print(f"  - {gap['gap_type']}: {gap['category']} (机会评分{gap['opportunity_score']})")
            print(f"    {gap['explanation']}")
    
    print("\n品类对比:")
    print(f"  我方品类: {result['category_comparison']['our_categories']}")
    print(f"  竞品品类: {result['category_comparison']['competitor_categories']}")
    
    print("✓ 测试5通过")


# ========== 主流程 ==========

if __name__ == "__main__":
    print("=" * 60)
    print("竞品情报分析引擎 - 集成测试")
    print("=" * 60)
    
    try:
        # 初始化测试数据库
        init_test_db()
        
        # 执行测试链路
        competitor_id = test_1_map_competitor_sku()
        test_2_compare_price_matrix(competitor_id)
        test_3_reverse_engineer_strategy(competitor_id)
        test_4_generate_counter_strategy(competitor_id)
        test_5_detect_market_gap(competitor_id)
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
