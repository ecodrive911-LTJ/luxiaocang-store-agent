"""
竞品情报分析引擎 - 工具注册模块
注册5个工具到agent_loop，供LLM调用
数据源：competitor_stores / competitor_skus / competitor_promotions / sku_mappings 表
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

from agent_loop import register_tool
from competitor_intelligence_skill.core_logic import (
    SKUFeatureExtractor,
    SKUMappingEngine,
    StrategyReverseEngine,
    CounterStrategyGenerator,
    CompetitorSKU,
    OurSKU
)


# ---------- DB连接 ----------
_DB_PATH = Path(__file__).parent / "database.db"


def _db_conn():
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def _db_query(sql: str, params: tuple = (), fetch: str = "all"):
    conn = _db_conn()
    try:
        cur = conn.execute(sql, params)
        if fetch == "all":
            return [dict(r) for r in cur.fetchall()]
        elif fetch == "one":
            row = cur.fetchone()
            return dict(row) if row else None
        elif fetch == "commit":
            conn.commit()
            return None
        return None
    finally:
        conn.close()


# ---------- 当前门店上下文（由agent_loop注入）----------
_current_store_id: Optional[str] = None


def set_current_store(store_id: Optional[str]):
    """由agent_loop在每次请求开始时调用"""
    global _current_store_id
    _current_store_id = store_id


def _get_store_id() -> str:
    return _current_store_id or "default"


# ========== 工具1：map_competitor_sku ==========
@register_tool(
    name="map_competitor_sku",
    description="建立我方SKU与竞品SKU的映射关系。录入竞品商品数据，自动通过四维特征（品牌/品类/规格/包装）匹配我方商品，输出置信度。置信度>0.85自动映射，0.6-0.85待人工确认，<0.6标记为我方独有。",
    parameters={
        "type": "object",
        "properties": {
            "competitor_name": {"type": "string", "description": "竞品店铺名称"},
            "competitor_skus": {
                "type": "array",
                "description": "竞品SKU列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku_name": {"type": "string"},
                        "sell_price": {"type": "number"},
                        "category": {"type": "string"},
                        "brand": {"type": "string"},
                        "spec": {"type": "string"},
                        "package": {"type": "string"}
                    },
                    "required": ["sku_name"]
                }
            },
            "store_id": {"type": "string", "description": "我方门店ID"}
        },
        "required": ["competitor_name", "competitor_skus", "store_id"]
    }
)
def map_competitor_sku(competitor_name: str, competitor_skus: list, store_id: str = None) -> dict:
    """建立竞品SKU映射关系"""
    store_id = store_id or _get_store_id()
    
    # 1. 创建或获取竞品店铺记录
    competitor = _db_query(
        "SELECT id FROM competitor_stores WHERE store_id=? AND competitor_name=?",
        (store_id, competitor_name),
        fetch="one"
    )
    
    if not competitor:
        comp_id = str(uuid.uuid4())
        _db_query(
            """INSERT INTO competitor_stores 
               (id, store_id, competitor_name, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (comp_id, store_id, competitor_name, time.time(), time.time()),
            fetch="commit"
        )
    else:
        comp_id = competitor["id"]
        _db_query(
            "UPDATE competitor_stores SET updated_at=? WHERE id=?",
            (time.time(), comp_id),
            fetch="commit"
        )
    
    # 2. 清空该竞品的旧SKU数据（重新录入）
    _db_query(
        "DELETE FROM competitor_skus WHERE competitor_store_id=?",
        (comp_id,),
        fetch="commit"
    )
    
    # 3. 插入新SKU数据
    comp_sku_objs = []
    for sku in competitor_skus:
        sku_id = str(uuid.uuid4())
        _db_query(
            """INSERT INTO competitor_skus
               (id, competitor_store_id, sku_name, category, brand, spec, package_type,
                sell_price, monthly_sales, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sku_id, comp_id, sku.get("sku_name"), sku.get("category"), sku.get("brand"),
             sku.get("spec"), sku.get("package"), sku.get("sell_price", 0),
             sku.get("monthly_sales", 0), time.time(), time.time()),
            fetch="commit"
        )
        comp_sku_objs.append(CompetitorSKU(
            sku_name=sku.get("sku_name"),
            sell_price=sku.get("sell_price", 0),
            category=sku.get("category", ""),
            brand=sku.get("brand", ""),
            spec=sku.get("spec", ""),
            package=sku.get("package", "")
        ))
    
    # 4. 获取我方SKU（从profit_order_feed历史订单中提取）
    our_orders = _db_query(
        """SELECT DISTINCT items_json FROM profit_order_feed 
           WHERE store_id=? AND created_at > ?""",
        (store_id, time.time() - 30 * 86400),  # 最近30天
        fetch="all"
    )
    
    our_skus = []
    seen = set()
    for order in our_orders:
        items = json.loads(order.get("items_json", "[]"))
        for it in items:
            name = it.get("sku_name")
            if name and name not in seen:
                seen.add(name)
                our_skus.append(OurSKU(
                    sku_name=name,
                    sell_price=it.get("sell_price", 0),
                    purchase_cost=it.get("purchase_cost", 0)
                ))
    
    # 5. 执行映射
    engine = SKUMappingEngine()
    mappings = engine.map_skus(our_skus, comp_sku_objs)
    
    # 6. 保存映射结果到数据库
    _db_query(
        "DELETE FROM sku_mappings WHERE store_id=? AND competitor_store_id=?",
        (store_id, comp_id),
        fetch="commit"
    )
    
    results = []
    for m in mappings:
        map_id = str(uuid.uuid4())
        _db_query(
            """INSERT INTO sku_mappings
               (id, store_id, competitor_store_id, our_sku_name, competitor_sku_name,
                confidence, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (map_id, store_id, comp_id, m.our_sku, m.competitor_sku,
             m.confidence, m.status, time.time(), time.time()),
            fetch="commit"
        )
        results.append({
            "competitor_sku": m.competitor_sku,
            "our_sku": m.our_sku if m.our_sku else "(我方独有)",
            "confidence": m.confidence,
            "status": m.status
        })
    
    return {
        "competitor_id": comp_id,
        "competitor_name": competitor_name,
        "total_competitor_skus": len(competitor_skus),
        "mappings": results,
        "summary": {
            "auto_mapped": sum(1 for r in results if r["status"] == "mapped"),
            "pending_review": sum(1 for r in results if r["status"] == "pending_review"),
            "our_unique": sum(1 for r in results if r["status"] == "unique")
        }
    }


# ========== 工具2：compare_price_matrix ==========
@register_tool(
    name="compare_price_matrix",
    description="生成我方与竞品的价格全景对比矩阵。显示每个已映射商品的价差百分比、整体价格指数，并标记显著差异项。",
    parameters={
        "type": "object",
        "properties": {
            "competitor_id": {"type": "string", "description": "竞品ID（map_competitor_sku返回的competitor_id）"},
            "store_id": {"type": "string", "description": "我方门店ID"},
            "category_filter": {"type": "string", "description": "按品类筛选（可选）"}
        },
        "required": ["competitor_id", "store_id"]
    }
)
def compare_price_matrix(competitor_id: str, store_id: str = None, category_filter: str = None) -> dict:
    """价格全景对比矩阵"""
    store_id = store_id or _get_store_id()
    
    # 1. 获取映射关系
    mappings = _db_query(
        """SELECT m.our_sku_name, m.competitor_sku_name, m.confidence, m.status
           FROM sku_mappings m
           WHERE m.store_id=? AND m.competitor_store_id=? AND m.status IN ('mapped', 'pending_review')""",
        (store_id, competitor_id),
        fetch="all"
    )
    
    if not mappings:
        return {"error": "无映射数据，请先执行map_competitor_sku建立映射关系"}
    
    # 2. 获取竞品SKU价格
    comp_prices = {}
    for m in mappings:
        row = _db_query(
            "SELECT sell_price, category FROM competitor_skus WHERE competitor_store_id=? AND sku_name=?",
            (competitor_id, m["competitor_sku_name"]),
            fetch="one"
        )
        if row:
            comp_prices[m["competitor_sku_name"]] = {
                "price": row["sell_price"],
                "category": row["category"]
            }
    
    # 3. 获取我方SKU价格（从最近订单中提取）
    our_prices = {}
    our_orders = _db_query(
        """SELECT items_json FROM profit_order_feed 
           WHERE store_id=? AND created_at > ?""",
        (store_id, time.time() - 7 * 86400),  # 最近7天
        fetch="all"
    )
    for order in our_orders:
        items = json.loads(order.get("items_json", "[]"))
        for it in items:
            name = it.get("sku_name")
            if name and name not in our_prices:
                our_prices[name] = it.get("sell_price", 0)
    
    # 4. 构建对比矩阵
    matrix = []
    total_index = 0
    count = 0
    
    for m in mappings:
        comp_sku = m["competitor_sku_name"]
        our_sku = m["our_sku_name"]
        
        if comp_sku not in comp_prices or our_sku not in our_prices:
            continue
        
        comp_price = comp_prices[comp_sku]["price"]
        our_price = our_prices[our_sku]
        
        if comp_price > 0:
            price_diff_pct = ((our_price - comp_price) / comp_price) * 100
        else:
            price_diff_pct = 0
        
        total_index += (our_price / comp_price) if comp_price > 0 else 1
        count += 1
        
        matrix.append({
            "our_sku": our_sku,
            "competitor_sku": comp_sku,
            "our_price": round(our_price, 2),
            "competitor_price": round(comp_price, 2),
            "price_diff_pct": round(price_diff_pct, 1),
            "category": comp_prices[comp_sku]["category"],
            "is_significant": abs(price_diff_pct) > 15  # 价差>15%为显著差异
        })
    
    avg_price_index = (total_index / count * 100) if count > 0 else 100
    
    # 5. 分类汇总
    categories = {}
    for item in matrix:
        cat = item["category"] or "未分类"
        if cat not in categories:
            categories[cat] = {"count": 0, "total_diff": 0}
        categories[cat]["count"] += 1
        categories[cat]["total_diff"] += item["price_diff_pct"]
    
    for cat in categories:
        categories[cat]["avg_diff_pct"] = round(
            categories[cat]["total_diff"] / categories[cat]["count"], 1
        )
    
    return {
        "competitor_id": competitor_id,
        "store_id": store_id,
        "total_items_compared": len(matrix),
        "avg_price_index": round(avg_price_index, 1),  # >100我方偏贵，<100我方便宜
        "matrix": matrix,
        "category_summary": categories,
        "significant_items": [m for m in matrix if m["is_significant"]]
    }


# ========== 工具3：reverse_engineer_strategy ==========
@register_tool(
    name="reverse_engineer_strategy",
    description="反推竞品的经营策略。识别每个SKU的角色（引流款/利润款/凑单款），判断满减/折扣的真实意图（拉新/提客单/清库存），输出整体策略判断。",
    parameters={
        "type": "object",
        "properties": {
            "competitor_id": {"type": "string", "description": "竞品ID"},
            "store_id": {"type": "string", "description": "我方门店ID"},
            "promotions": {
                "type": "array",
                "description": "竞品当前活动列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["满减", "折扣", "第N件优惠", "秒杀", "新客", "运费减免", "赠品"]},
                        "detail": {"type": "string", "description": "活动详情，如'满39减5'"}
                    },
                    "required": ["type", "detail"]
                }
            }
        },
        "required": ["competitor_id", "store_id"]
    }
)
def reverse_engineer_strategy(competitor_id: str, store_id: str = None, promotions: list = None) -> dict:
    """反推竞品策略"""
    store_id = store_id or _get_store_id()
    promotions = promotions or []
    
    # 1. 获取竞品SKU数据
    comp_skus = _db_query(
        "SELECT sku_name, sell_price, category, monthly_sales FROM competitor_skus WHERE competitor_store_id=?",
        (competitor_id,),
        fetch="all"
    )
    
    if not comp_skus:
        return {"error": "无竞品SKU数据，请先录入竞品商品"}
    
    # 2. 转换为CompetitorSKU对象
    sku_objs = [
        CompetitorSKU(
            sku_name=s["sku_name"],
            sell_price=s["sell_price"],
            category=s["category"] or "",
            monthly_sales=s["monthly_sales"] or 0
        )
        for s in comp_skus
    ]
    
    # 3. 分析每个SKU的角色
    engine = StrategyReverseEngine()
    sku_roles = [engine.analyze_sku_role(sku) for sku in sku_objs]
    
    # 4. 反推活动意图
    promo_intents = engine.reverse_promotion_intent(promotions)
    
    # 5. 综合判断整体策略
    overall = engine.overall_strategy_judgment(sku_roles, promo_intents)
    
    # 6. 保存分析结果
    analysis_id = str(uuid.uuid4())
    result_json = json.dumps({
        "sku_roles": sku_roles,
        "promo_intents": promo_intents,
        "overall": overall
    }, ensure_ascii=False)
    
    _db_query(
        """INSERT INTO strategy_analyses
           (id, store_id, competitor_store_id, analysis_type, result_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (analysis_id, store_id, competitor_id, "reverse_engineer", result_json, time.time()),
        fetch="commit"
    )
    
    return {
        "analysis_id": analysis_id,
        "competitor_id": competitor_id,
        "sku_role_analysis": sku_roles,
        "promotion_intent_analysis": promo_intents,
        "overall_strategy": overall
    }


# ========== 工具4：generate_counter_strategy ==========
@register_tool(
    name="generate_counter_strategy",
    description="基于竞品策略和我方底线，生成攻/守/避三套应对方案。每套方案包含具体操作、预期效果和风险提示。",
    parameters={
        "type": "object",
        "properties": {
            "competitor_id": {"type": "string", "description": "竞品ID"},
            "store_id": {"type": "string", "description": "我方门店ID"},
            "my_cost_data": {
                "type": "array",
                "description": "我方商品成本数据",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku_name": {"type": "string"},
                        "purchase_cost": {"type": "number"},
                        "current_price": {"type": "number"}
                    },
                    "required": ["sku_name", "purchase_cost", "current_price"]
                }
            }
        },
        "required": ["competitor_id", "store_id", "my_cost_data"]
    }
)
def generate_counter_strategy(competitor_id: str, store_id: str = None, my_cost_data: list = None) -> dict:
    """生成应对方案"""
    store_id = store_id or _get_store_id()
    my_cost_data = my_cost_data or []
    
    # 1. 获取最新的竞品策略分析
    latest_analysis = _db_query(
        """SELECT result_json FROM strategy_analyses
           WHERE store_id=? AND competitor_store_id=? AND analysis_type='reverse_engineer'
           ORDER BY created_at DESC LIMIT 1""",
        (store_id, competitor_id),
        fetch="one"
    )
    
    if not latest_analysis:
        return {"error": "无竞品策略分析数据，请先执行reverse_engineer_strategy"}
    
    competitor_analysis = json.loads(latest_analysis["result_json"])
    
    # 2. 构建我方SKU数据（含竞品映射价格）
    my_skus = []
    for cost_item in my_cost_data:
        sku_name = cost_item["sku_name"]
        
        # 查找该SKU对应的竞品价格
        mapping = _db_query(
            """SELECT competitor_sku_name FROM sku_mappings
               WHERE store_id=? AND competitor_store_id=? AND our_sku_name=?""",
            (store_id, competitor_id, sku_name),
            fetch="one"
        )
        
        comp_price = None
        if mapping:
            comp_sku_row = _db_query(
                "SELECT sell_price FROM competitor_skus WHERE competitor_store_id=? AND sku_name=?",
                (competitor_id, mapping["competitor_sku_name"]),
                fetch="one"
            )
            if comp_sku_row:
                comp_price = comp_sku_row["sell_price"]
        
        my_skus.append({
            "sku_name": sku_name,
            "purchase_cost": cost_item["purchase_cost"],
            "current_price": cost_item["current_price"],
            "mapped_competitor_price": comp_price
        })
    
    # 3. 生成三套方案
    generator = CounterStrategyGenerator()
    strategies = generator.generate(competitor_analysis, my_skus)
    
    # 4. 保存方案
    analysis_id = str(uuid.uuid4())
    result_json = json.dumps(strategies, ensure_ascii=False)
    
    _db_query(
        """INSERT INTO strategy_analyses
           (id, store_id, competitor_store_id, analysis_type, result_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (analysis_id, store_id, competitor_id, "counter_strategy", result_json, time.time()),
        fetch="commit"
    )
    
    return {
        "analysis_id": analysis_id,
        "competitor_id": competitor_id,
        "attack_plan": strategies["attack_plan"],
        "defend_plan": strategies["defend_plan"],
        "avoid_plan": strategies["avoid_plan"]
    }


# ========== 工具5：detect_market_gap ==========
@register_tool(
    name="detect_market_gap",
    description="在竞品未覆盖或覆盖弱的品类/价格带中发现市场机会。输出机会列表和评分。",
    parameters={
        "type": "object",
        "properties": {
            "competitor_id": {"type": "string", "description": "竞品ID"},
            "store_id": {"type": "string", "description": "我方门店ID"}
        },
        "required": ["competitor_id", "store_id"]
    }
)
def detect_market_gap(competitor_id: str, store_id: str = None) -> dict:
    """检测市场空白"""
    store_id = store_id or _get_store_id()
    
    # 1. 获取竞品SKU品类分布
    comp_skus = _db_query(
        "SELECT category, COUNT(*) as count FROM competitor_skus WHERE competitor_store_id=? GROUP BY category",
        (competitor_id,),
        fetch="all"
    )
    comp_categories = {s["category"]: s["count"] for s in comp_skus}
    
    # 2. 获取我方SKU品类分布
    our_orders = _db_query(
        """SELECT items_json FROM profit_order_feed 
           WHERE store_id=? AND created_at > ?""",
        (store_id, time.time() - 30 * 86400),
        fetch="all"
    )
    
    our_categories = {}
    seen = set()
    for order in our_orders:
        items = json.loads(order.get("items_json", "[]"))
        for it in items:
            name = it.get("sku_name", "")
            if name not in seen:
                seen.add(name)
                # 简单推断品类（实际应该用SKUFeatureExtractor）
                cat = _infer_category(name)
                our_categories[cat] = our_categories.get(cat, 0) + 1
    
    # 3. 识别机会
    gaps = []
    
    # 机会1：我方有但竞品没有的品类
    for cat in our_categories:
        if cat not in comp_categories:
            gaps.append({
                "gap_type": "品类空白",
                "category": cat,
                "our_sku_count": our_categories[cat],
                "competitor_sku_count": 0,
                "opportunity_score": 85,
                "explanation": f"竞品在{cat}品类完全空白，我方可重点发力"
            })
    
    # 机会2：竞品有但我方覆盖弱的品类
    for cat in comp_categories:
        our_count = our_categories.get(cat, 0)
        comp_count = comp_categories[cat]
        if our_count < comp_count * 0.3:  # 我方SKU数<竞品30%
            gaps.append({
                "gap_type": "覆盖不足",
                "category": cat,
                "our_sku_count": our_count,
                "competitor_sku_count": comp_count,
                "opportunity_score": 70,
                "explanation": f"竞品在{cat}品类有{comp_count}个SKU，我方仅{our_count}个，可扩充SKU深度"
            })
    
    # 机会3：高频需求品类（基于我方订单数据推断）
    sorted_cats = sorted(our_categories.items(), key=lambda x: x[1], reverse=True)
    for cat, count in sorted_cats[:3]:
        if cat not in gaps and cat not in comp_categories:
            gaps.append({
                "gap_type": "高频需求",
                "category": cat,
                "our_sku_count": count,
                "competitor_sku_count": 0,
                "opportunity_score": 80,
                "explanation": f"{cat}是我方高频品类（近30天{count}次），竞品未覆盖，可重点推广"
            })
    
    # 按机会评分排序
    gaps.sort(key=lambda x: x["opportunity_score"], reverse=True)
    
    return {
        "competitor_id": competitor_id,
        "store_id": store_id,
        "total_gaps_found": len(gaps),
        "gaps": gaps,
        "category_comparison": {
            "our_categories": our_categories,
            "competitor_categories": comp_categories
        }
    }


def _infer_category(sku_name: str) -> str:
    """简单推断商品品类（临时方案，应该用SKUFeatureExtractor）"""
    name_lower = sku_name.lower()
    if any(kw in name_lower for kw in ["可乐", "雪碧", "芬达"]):
        return "碳酸饮料"
    elif any(kw in name_lower for kw in ["矿泉水", "纯净水", "天然水"]):
        return "矿泉水"
    elif any(kw in name_lower for kw in ["茶", "绿茶", "红茶"]):
        return "茶饮料"
    elif any(kw in name_lower for kw in ["牛奶", "酸奶"]):
        return "乳制品"
    elif any(kw in name_lower for kw in ["薯片", "膨化"]):
        return "膨化食品"
    elif any(kw in name_lower for kw in ["方便面", "泡面"]):
        return "方便食品"
    else:
        return "其他"
