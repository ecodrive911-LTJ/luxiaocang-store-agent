"""
动态盈利决策引擎 — 工具注册模块
注册 4 个工具到 agent_loop，供 LLM 调用
数据源：profit_order_feed 表（3天滚动累计），由外部通过 /api/profit_engine/ingest 被动喂入
"""
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from agent_loop import register_tool
from dynamic_profit_engine import (
    BASE_DISTANCE, BASE_FEE, EXTRA_PER_KM, FULFILLMENT_COST,
    DAILY_FIXED_COST, RED_LINE_PROFIT, RED_LINE_RATE, DASHBOARD_PERIOD_DAYS,
    calc_delivery_cost, calc_break_even_distance, calc_min_order_amount, calc_break_even_orders
)


# ---------- DB 连接 ----------
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


# ---------- 当前门店上下文（由 agent_loop 注入）----------
# 用模块级变量保存当前请求的 store_id，在 agent_loop 入口设置
_current_store_id: Optional[str] = None


def set_current_store(store_id: Optional[str]):
    """由 agent_loop 在每次请求开始时调用"""
    global _current_store_id
    _current_store_id = store_id


def _get_store_id() -> str:
    return _current_store_id or "default"


# ========== 工具 1：evaluate_order ==========
@register_tool(
    name="evaluate_order",
    description="实时评估单笔订单的盈利能力。计算扣除商品成本、平台抽佣、动态配送费和履约成本后的真实净利，并计算盈亏临界距离。当老板问'这单赚不赚''能不能接'时必须调用。",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "订单唯一ID"},
            "items": {
                "type": "array",
                "description": "订单商品列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku_name": {"type": "string", "description": "商品名"},
                        "sell_price": {"type": "number", "description": "售价"},
                        "purchase_cost": {"type": "number", "description": "进货成本"},
                        "quantity": {"type": "integer", "description": "数量"}
                    },
                    "required": ["sku_name", "sell_price", "purchase_cost", "quantity"]
                }
            },
            "delivery_distance_km": {"type": "number", "description": "配送距离(公里)"},
            "platform_commission_rate": {"type": "number", "description": "平台抽佣比例(如0.18代表18%)"}
        },
        "required": ["order_id", "items", "delivery_distance_km", "platform_commission_rate"]
    }
)
def evaluate_order(order_id: str, items: list, delivery_distance_km: float, platform_commission_rate: float) -> dict:
    """评估单笔订单盈利能力"""
    store_id = _get_store_id()

    # 计算营收/成本
    total_revenue = sum(it.get("sell_price", 0) * it.get("quantity", 1) for it in items)
    total_cost = sum(it.get("purchase_cost", 0) * it.get("quantity", 1) for it in items)
    gross_profit = total_revenue - total_cost

    commission = total_revenue * platform_commission_rate
    delivery_cost = calc_delivery_cost(delivery_distance_km)
    net_profit = gross_profit - commission - delivery_cost - FULFILLMENT_COST

    # 盈亏临界距离
    break_even_distance = calc_break_even_distance(gross_profit, commission)

    status = "盈利" if net_profit > 0.5 else ("保本" if net_profit >= -0.5 else "亏损")
    suggestions = []
    if net_profit < 0:
        if delivery_distance_km > break_even_distance:
            suggestions.append(f"距离超标（{delivery_distance_km}km > 临界{break_even_distance:.1f}km），建议加收 {abs(net_profit):.1f} 元远程运费或拒单。")
        if total_revenue > 0 and gross_profit / total_revenue < 0.25:
            suggestions.append("毛利率过低（<25%），建议引导凑单提升客单价。")
    elif net_profit < 2:
        suggestions.append(f"利润偏薄（净利{net_profit:.1f}元），关注距离和凑单。")

    # 写入 profit_order_feed（持久化到3天累计）
    try:
        _db_query(
            """INSERT INTO profit_order_feed
               (store_id, order_id, total_revenue, total_cost, gross_profit,
                platform_commission, delivery_cost, fulfillment_cost, net_profit,
                distance_km, commission_rate, items_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (store_id, order_id, round(total_revenue, 2), round(total_cost, 2),
             round(gross_profit, 2), round(commission, 4), round(delivery_cost, 2),
             FULFILLMENT_COST, round(net_profit, 2), delivery_distance_km,
             platform_commission_rate, json.dumps(items, ensure_ascii=False), time.time()),
            fetch="commit"
        )
    except Exception:
        pass  # 写入失败不影响评估结果返回

    return {
        "order_id": order_id,
        "status": status,
        "net_profit": round(net_profit, 2),
        "gross_profit": round(gross_profit, 2),
        "commission": round(commission, 2),
        "delivery_cost": round(delivery_cost, 2),
        "break_even_distance_km": round(break_even_distance, 1),
        "suggestions": suggestions
    }


# ========== 工具 2：get_store_dashboard ==========
@register_tool(
    name="get_store_dashboard",
    description="获取门店最近3天的实时财务大盘数据，包括累计净利、平均每单净利、保本单量、距保本还差多少单。当老板问'今天怎么样''保本了吗''赚了多少'时必须调用。",
    parameters={
        "type": "object",
        "properties": {
            "daily_profit_target": {"type": "number", "description": "每日目标净利润(元)，用于计算达成进度，默认0"}
        }
    }
)
def get_store_dashboard(daily_profit_target: float = 0) -> dict:
    """获取门店3天滚动大盘"""
    store_id = _get_store_id()
    cutoff_ts = time.time() - 3 * 86400  # 3天前

    rows = _db_query(
        """SELECT COUNT(*) as cnt,
                  COALESCE(SUM(net_profit),0) as total_net,
                  COALESCE(SUM(total_revenue),0) as total_rev,
                  COALESCE(SUM(gross_profit),0) as total_gp
           FROM profit_order_feed
           WHERE store_id=? AND created_at>=?""",
        (store_id, cutoff_ts),
        fetch="one"
    )

    total_orders = rows["cnt"] or 0
    total_net = rows["total_net"] or 0
    total_rev = rows["total_rev"] or 0
    total_gp = rows["total_gp"] or 0

    avg_net = total_net / total_orders if total_orders > 0 else 0
    blended_margin = total_gp / total_rev if total_rev > 0 else 0

    # 保本单量（3天）
    break_even_orders = calc_break_even_orders(avg_net, period_days=3)
    remaining = max(0, break_even_orders - total_orders) if break_even_orders < 9999 else 9999

    # 目标达成进度
    target_progress = None
    if daily_profit_target > 0:
        target_3d = daily_profit_target * 3
        target_progress = min(1.0, total_net / target_3d) if target_3d > 0 else 0

    suggestions = []
    if total_orders == 0:
        suggestions.append("最近3天无订单数据，请确认数据是否已录入。")
    elif avg_net < 2:
        suggestions.append(f"平均每单净利仅{avg_net:.1f}元，建议提升高毛利商品曝光或优化配送范围。")
    else:
        suggestions.append("保持当前节奏，关注亏损距离订单。")

    if remaining > 0 and remaining < 9999:
        suggestions.append(f"距3天保本还差约{remaining}单，可考虑引导凑单或推出高毛利组合。")

    result = {
        "store_id": store_id,
        "period_days": 3,
        "total_orders_3d": total_orders,
        "total_net_profit_3d": round(total_net, 2),
        "avg_order_net_profit": round(avg_net, 2),
        "blended_gross_margin": round(blended_margin, 4),
        "break_even_orders_3d": break_even_orders,
        "remaining_orders_to_break_even": remaining,
    }
    if target_progress is not None:
        result["target_progress"] = round(target_progress, 4)
        result["daily_profit_target"] = daily_profit_target
    result["suggestions"] = suggestions
    return result


# ========== 工具 3：simulate_price_change ==========
@register_tool(
    name="simulate_price_change",
    description="总军师功能：模拟单品调价对整体利润和保本单量的影响(What-if分析)。当老板问'涨价X元会怎样''降价值不值'时必须调用。",
    parameters={
        "type": "object",
        "properties": {
            "sku_name": {"type": "string", "description": "商品名称"},
            "current_price": {"type": "number", "description": "当前售价"},
            "purchase_cost": {"type": "number", "description": "进货成本"},
            "price_delta": {"type": "number", "description": "价格变化量(正数=涨价，负数=降价)"},
            "estimated_volume_change_pct": {"type": "number", "description": "预估销量变化百分比(如涨价导致销量降5%填-5，默认-5)"}
        },
        "required": ["sku_name", "current_price", "purchase_cost", "price_delta"]
    }
)
def simulate_price_change(sku_name: str, current_price: float, purchase_cost: float,
                          price_delta: float, estimated_volume_change_pct: float = -5.0) -> dict:
    """模拟调价影响"""
    old_unit_profit = current_price - purchase_cost
    new_price = current_price + price_delta
    new_unit_profit = new_price - purchase_cost

    # 基准日销50件
    base_volume = 50
    old_daily_contrib = old_unit_profit * base_volume
    new_volume = base_volume * (1 + estimated_volume_change_pct / 100)
    new_daily_contrib = new_unit_profit * new_volume

    delta_3d = (new_daily_contrib - old_daily_contrib) * 3

    # 保本单量变化（日均固定成本）
    if old_unit_profit > 0 and new_unit_profit > 0:
        be_before = math.ceil(DAILY_FIXED_COST / old_unit_profit)
        be_after = math.ceil(DAILY_FIXED_COST / new_unit_profit)
        be_change = be_after - be_before
    else:
        be_before = 9999
        be_after = 9999
        be_change = 0

    recommendation = "建议执行" if new_daily_contrib > old_daily_contrib else "不建议执行"
    if abs(new_daily_contrib - old_daily_contrib) / max(old_daily_contrib, 0.01) < 0.05:
        recommendation = "影响有限，可执行可不执行"

    return {
        "sku_name": sku_name,
        "price_change": f"{current_price} -> {new_price}",
        "old_unit_profit": round(old_unit_profit, 2),
        "new_unit_profit": round(new_unit_profit, 2),
        "daily_contribution_change": round(new_daily_contrib - old_daily_contrib, 2),
        "profit_change_3d": round(delta_3d, 2),
        "break_even_orders_before": be_before,
        "break_even_orders_after": be_after,
        "break_even_orders_change": be_change,
        "recommendation": recommendation
    }


# ========== 工具 4：simulate_delivery_strategy ==========
@register_tool(
    name="simulate_delivery_strategy",
    description="总军师功能：模拟不同配送距离下的最低起送价建议，用于制定阶梯配送策略。当老板问'配送费太贵怎么办''各距离起送价怎么设'时必须调用。",
    parameters={
        "type": "object",
        "properties": {
            "avg_gross_margin": {"type": "number", "description": "门店平均商品毛利率(如0.25代表25%)"},
            "platform_commission_rate": {"type": "number", "description": "平台抽佣比例(如0.18代表18%)"}
        },
        "required": ["avg_gross_margin", "platform_commission_rate"]
    }
)
def simulate_delivery_strategy(avg_gross_margin: float, platform_commission_rate: float) -> dict:
    """模拟配送策略：距离-起送价阶梯"""
    strategies = []
    for dist in [2, 3, 4, 5, 6]:
        del_cost = calc_delivery_cost(dist)
        # 反推保本起送价: 起送价 × (毛利率 - 抽佣率) = 运费 + 履约费
        margin_after_commission = avg_gross_margin - platform_commission_rate
        if margin_after_commission > 0:
            min_amount = (del_cost + FULFILLMENT_COST) / margin_after_commission
        else:
            min_amount = 9999
        strategies.append({
            "distance_km": dist,
            "delivery_cost": round(del_cost, 2),
            "min_order_amount": round(min_amount, 0),
            "status": "可行" if min_amount < 200 else "风险高"
        })

    suggestions = []
    for s in strategies:
        if s["min_order_amount"] > 100:
            suggestions.append(f"⚠️ {s['distance_km']}km 起送价需{int(s['min_order_amount'])}元才保本，建议收缩配送范围或加收运费。")
    if not suggestions:
        suggestions.append("✅ 当前毛利率下各距离区间均可覆盖成本。")

    return {"strategies": strategies, "suggestions": suggestions}
