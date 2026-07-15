"""
鹿小仓 — 数据看板可视化聚合引擎 (D2-07)

功能：
1. 单店看板：品类结构 / 价格带分布 / 毛利分布 / 商品分层 / 品类健康度雷达 / KPI
2. 总部看板：多店汇总 / 门店排行（SKU数·理论毛利额·异常数）/ 全局品类结构

数据来源：
- 库存 Excel（经由 product_analysis.load_store_inventory）
- message_queue 表（异常消息数）
- stores 表（门店列表）

注意：当前无真实销售流水，看板基于"库存画像"构建（理论毛利额=Σ毛利，
假设全部售罄）。接入 POS 交易数据后可替换为真实销售额/动销率。
"""

import os
import sqlite3
import time
from collections import defaultdict
from typing import Optional

from product_analysis import load_store_inventory, classify_products, _get_store_name

# ===== 内存缓存（避免每次请求重读Excel）=====
_CACHE = {}
_CACHE_TTL = 300  # 5分钟


def _cache_get(key):
    if key in _CACHE:
        ts, val = _CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None


def _cache_set(key, val):
    _CACHE[key] = (time.time(), val)


# ===== 价格带 / 毛利带 分箱 =====
PRICE_BANDS = [(0, 5), (5, 10), (10, 20), (20, 50), (50, 100), (100, float("inf"))]
PRICE_BAND_LABELS = ["0-5", "5-10", "10-20", "20-50", "50-100", "100+"]

MARGIN_BANDS = [(-float("inf"), 0), (0, 2), (2, 5), (5, 10), (10, float("inf"))]
MARGIN_BAND_LABELS = ["亏损", "0-2", "2-5", "5-10", "10+"]


def _safe_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_alert_count(db_path: str, store_id: str) -> int:
    """未读异常消息数"""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM message_queue WHERE store_id=? AND is_read=0",
            (store_id,),
        )
        n = c.fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def compute_store_dashboard(db_path: str, store_id: str) -> dict:
    """单店看板数据"""
    cache_key = f"store_dash:{store_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    store_name = _get_store_name(db_path, store_id)
    if not store_name:
        return {"error": f"未找到门店: {store_id}"}

    try:
        items = load_store_inventory(db_path, store_id)
    except Exception as e:
        return {"error": f"库存数据加载失败: {str(e)}"}

    if not items:
        return {"error": "无库存数据"}

    # ---- KPI ----
    prices = [i["price"] for i in items if i["price"] is not None]
    markups = [i["markup_rate"] for i in items if i["markup_rate"] is not None]
    margins = [i["gross_profit"] for i in items if i["gross_profit"] is not None]
    total_gp = sum(m for m in margins if m is not None)
    traffic_flag_count = sum(1 for i in items if i["traffic_flag"])

    kpi = {
        "sku_total": len(items),
        "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
        "avg_markup": round(sum(markups) / len(markups), 1) if markups else 0,
        "avg_gross_profit": round(sum(margins) / len(margins), 2) if margins else 0,
        "theoretical_gross_profit_total": round(total_gp, 2),
        "traffic_count": traffic_flag_count,
        "alert_count": _get_alert_count(db_path, store_id),
    }

    # ---- 品类结构 ----
    cat_counts = defaultdict(int)
    cat_margin_sum = defaultdict(float)
    cat_markup_sum = defaultdict(float)
    cat_traffic = defaultdict(int)
    cat_price_sum = defaultdict(float)
    for it in items:
        cat = it["category"] or "未分类"
        cat_counts[cat] += 1
        if it["gross_profit"] is not None:
            cat_margin_sum[cat] += it["gross_profit"]
        if it["markup_rate"] is not None:
            cat_markup_sum[cat] += it["markup_rate"]
        if it["traffic_flag"]:
            cat_traffic[cat] += 1
        if it["price"] is not None:
            cat_price_sum[cat] += it["price"]

    category_pie = [
        {"name": k, "value": v}
        for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])
    ]

    # ---- 价格带分布 ----
    price_band_counts = [0] * len(PRICE_BANDS)
    for p in prices:
        for idx, (lo, hi) in enumerate(PRICE_BANDS):
            if lo <= p < hi:
                price_band_counts[idx] += 1
                break

    # ---- 毛利带分布 ----
    margin_band_counts = [0] * len(MARGIN_BANDS)
    for m in margins:
        if m is None:
            continue
        for idx, (lo, hi) in enumerate(MARGIN_BANDS):
            if lo <= m < hi:
                margin_band_counts[idx] += 1
                break

    # ---- 商品分层（复用 D2-06）----
    tier_result = classify_products(db_path, store_id)
    tiers = tier_result.get("summary", {})

    # ---- 品类健康度雷达 ----
    cats = list(cat_counts.keys())
    max_sku = max(cat_counts.values()) if cat_counts else 1
    radar = {
        "categories": cats,
        "sku": [round(cat_counts[c] / max_sku * 100, 1) for c in cats],
        "margin": [
            round(cat_margin_sum[c] / cat_counts[c], 2) if cat_counts[c] else 0
            for c in cats
        ],
        "markup": [
            round(cat_markup_sum[c] / cat_counts[c], 1) if cat_counts[c] else 0
            for c in cats
        ],
        "traffic_ratio": [
            round(cat_traffic[c] / cat_counts[c] * 100, 1) for c in cats
        ],
        "price": [
            round(cat_price_sum[c] / cat_counts[c], 2) if cat_counts[c] else 0
            for c in cats
        ],
    }

    result = {
        "store_id": store_id,
        "store_name": store_name,
        "kpi": kpi,
        "charts": {
            "category_pie": category_pie,
            "price_band": {
                "labels": PRICE_BAND_LABELS,
                "counts": price_band_counts,
            },
            "margin_band": {
                "labels": MARGIN_BAND_LABELS,
                "counts": margin_band_counts,
            },
            "product_tiers": {
                "traffic": tiers.get("traffic", 0),
                "profit": tiers.get("profit", 0),
                "regular": tiers.get("regular", 0),
                "long_tail": tiers.get("long_tail", 0),
            },
            "category_health_radar": radar,
        },
    }
    _cache_set(cache_key, result)
    return result


def compute_hq_dashboard(db_path: str) -> dict:
    """总部看板：所有门店汇总 + 排行"""
    cache_key = "hq_dash"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT id, name FROM stores")
        stores = c.fetchall()
        conn.close()
    except Exception as e:
        return {"error": f"门店列表加载失败: {str(e)}"}

    if not stores:
        return {"error": "无门店数据"}

    store_list = []
    global_cat = defaultdict(int)
    for sid, sname in stores:
        try:
            dash = compute_store_dashboard(db_path, sid)
        except Exception:
            continue
        if "error" in dash:
            continue
        store_list.append(
            {
                "store_id": sid,
                "store_name": sname,
                "sku_total": dash["kpi"]["sku_total"],
                "avg_price": dash["kpi"]["avg_price"],
                "avg_markup": dash["kpi"]["avg_markup"],
                "theoretical_gross_profit_total": dash["kpi"][
                    "theoretical_gross_profit_total"
                ],
                "alert_count": dash["kpi"]["alert_count"],
            }
        )
        for item in dash["charts"]["category_pie"]:
            global_cat[item["name"]] += item["value"]

    # 排行
    store_list_sorted_sku = sorted(
        store_list, key=lambda x: -x["sku_total"]
    )
    store_list_sorted_profit = sorted(
        store_list, key=lambda x: -x["theoretical_gross_profit_total"]
    )
    store_list_sorted_alert = sorted(
        store_list, key=lambda x: -x["alert_count"]
    )

    rank_sku = {
        "names": [s["store_name"] for s in store_list_sorted_sku],
        "values": [s["sku_total"] for s in store_list_sorted_sku],
    }
    rank_profit = {
        "names": [s["store_name"] for s in store_list_sorted_profit],
        "values": [
            s["theoretical_gross_profit_total"] for s in store_list_sorted_profit
        ],
    }
    rank_alert = {
        "names": [s["store_name"] for s in store_list_sorted_alert],
        "values": [s["alert_count"] for s in store_list_sorted_alert],
    }
    category_total_pie = [
        {"name": k, "value": v}
        for k, v in sorted(global_cat.items(), key=lambda x: -x[1])
    ]

    result = {
        "store_count": len(store_list),
        "stores": store_list,
        "charts": {
            "rank_sku": rank_sku,
            "rank_profit": rank_profit,
            "rank_alert": rank_alert,
            "category_total_pie": category_total_pie,
        },
    }
    _cache_set(cache_key, result)
    return result


if __name__ == "__main__":
    import json

    DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
    # 测试单店
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id FROM stores LIMIT 1")
    sid = c.fetchone()[0]
    conn.close()
    print("=== 单店看板 ===")
    print(json.dumps(compute_store_dashboard(DB, sid), ensure_ascii=False, indent=2, default=str))
    print("\n=== 总部看板 ===")
    print(json.dumps(compute_hq_dashboard(DB), ensure_ascii=False, indent=2, default=str))
