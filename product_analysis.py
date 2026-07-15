"""
鹿小仓 — 选品规划+商品分层分析引擎 (D2-06)

功能：
1. 商品自动分层：按品类×价格带×毛利率自动打标签(traffic/profit/regular/long_tail)
2. 品类差异分析：两店SKU对比，找出差异化商品
3. 滞销品识别：基于价格偏离度+加价率+品类占比识别潜在滞销品
4. 购物篮关联：基于品类共现分析给出搭售建议（需POS交易数据完善）
"""

import os
import sqlite3
from collections import defaultdict
from typing import Optional

try:
    import openpyxl
except ImportError:
    openpyxl = None

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "stores")
# Fallback: same dir as app.py
APP_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_DIR = os.path.join(APP_DIR, "knowledge", "stores")

STORE_FILE_MAP = {
    # store_id will be resolved at runtime; this maps store names to files
    "鹿小仓广安店": "鹿小仓广安店_库存合并总表.xlsx",
    "鹿小仓财富店": "鹿小仓财富店_库存合并总表.xlsx",
}


def _load_excel_inventory(file_path: str) -> list[dict]:
    """从Excel文件加载库存数据"""
    if not openpyxl:
        raise RuntimeError("openpyxl未安装，无法读取Excel")
    wb = openpyxl.load_workbook(file_path, read_only=True)
    ws = wb.active
    rows = []
    headers = None
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(c).strip() if c else f"col_{j}" for j, c in enumerate(row)]
            continue
        if not row[0]:
            continue
        item = {}
        for j, val in enumerate(row):
            if j < len(headers):
                item[headers[j]] = val
        # Normalize keys
        rows.append({
            "name": str(item.get("商品名称", "")).strip(),
            "category": str(item.get("一级大类", "未分类")).strip(),
            "spec": str(item.get("规格容量", "") or "").strip(),
            "price": _safe_float(item.get("售价")),
            "cost": _safe_float(item.get("采购价")),
            "gross_profit": _safe_float(item.get("毛利")),
            "markup_rate": _safe_float(item.get("加价率")),
            "barcode": str(item.get("条码", "") or "").strip(),
            "traffic_flag": bool(item.get("引流标识")),
        })
    wb.close()
    return rows


def _safe_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_store_name(db_path: str, store_id: str) -> str:
    """从数据库获取门店名称"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM stores WHERE id=?", (store_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""


def _resolve_excel_path(store_name: str) -> Optional[str]:
    """根据门店名称找到对应的Excel文件"""
    filename = STORE_FILE_MAP.get(store_name)
    if filename:
        path = os.path.join(KNOWLEDGE_DIR, filename)
        if os.path.exists(path):
            return path
    # Fallback: fuzzy match
    if os.path.isdir(KNOWLEDGE_DIR):
        for f in os.listdir(KNOWLEDGE_DIR):
            if store_name in f and f.endswith(".xlsx") and "库存" in f:
                return os.path.join(KNOWLEDGE_DIR, f)
    return None


def load_store_inventory(db_path: str, store_id: str) -> list[dict]:
    """加载门店库存数据（优先Excel，后续可扩展为数据库）"""
    store_name = _get_store_name(db_path, store_id)
    if not store_name:
        raise ValueError(f"未找到门店: {store_id}")
    excel_path = _resolve_excel_path(store_name)
    if not excel_path:
        raise FileNotFoundError(f"未找到门店[{store_name}]的库存Excel文件")
    return _load_excel_inventory(excel_path)


# ============================================================
# 1. 商品自动分层
# ============================================================

def classify_products(db_path: str, store_id: str) -> dict:
    """
    商品自动分层算法：
    - traffic (引流品): 售价低 + 毛利低，或已有引流标识
    - profit (利润品): 毛利率高 + 加价率高
    - long_tail (长尾品): 价格高 + 品类SKU少 + 非引流
    - regular (常规品): 其余
    """
    items = load_store_inventory(db_path, store_id)
    if not items:
        return {"error": "无库存数据"}

    # 计算统计分位数
    prices = [i["price"] for i in items if i["price"] is not None]
    margins = [i["gross_profit"] for i in items if i["gross_profit"] is not None]
    markups = [i["markup_rate"] for i in items if i["markup_rate"] is not None]

    if not prices:
        return {"error": "无有效价格数据"}

    prices_sorted = sorted(prices)
    margins_sorted = sorted(margins) if margins else []
    markups_sorted = sorted(markups) if markups else []

    n = len(prices_sorted)
    price_p20 = prices_sorted[int(n * 0.2)]
    price_p80 = prices_sorted[int(n * 0.8)]

    nm = len(margins_sorted)
    margin_p30 = margins_sorted[int(nm * 0.3)] if nm else 0
    margin_p70 = margins_sorted[int(nm * 0.7)] if nm else 0

    nmu = len(markups_sorted)
    markup_p70 = markups_sorted[int(nmu * 0.7)] if nmu else 0

    # 品类SKU计数
    cat_counts = defaultdict(int)
    for item in items:
        cat_counts[item["category"]] += 1

    # 分类
    result = {"traffic": [], "profit": [], "regular": [], "long_tail": []}
    for item in items:
        role = _classify_single(item, price_p20, price_p80, margin_p70,
                                markup_p70, cat_counts)
        result[role].append({
            "name": item["name"],
            "category": item["category"],
            "spec": item["spec"],
            "price": item["price"],
            "cost": item["cost"],
            "gross_profit": item["gross_profit"],
            "markup_rate": item["markup_rate"],
            "barcode": item["barcode"],
        })

    # 统计摘要
    summary = {
        "total": len(items),
        "traffic": len(result["traffic"]),
        "profit": len(result["profit"]),
        "regular": len(result["regular"]),
        "long_tail": len(result["long_tail"]),
        "traffic_pct": round(len(result["traffic"]) / len(items) * 100, 1),
        "profit_pct": round(len(result["profit"]) / len(items) * 100, 1),
        "regular_pct": round(len(result["regular"]) / len(items) * 100, 1),
        "long_tail_pct": round(len(result["long_tail"]) / len(items) * 100, 1),
    }

    # 每类取Top 10示例
    for role in result:
        result[role] = result[role][:10]

    return {"summary": summary, "samples": result}


def _classify_single(item, price_p20, price_p80, margin_p70,
                     markup_p70, cat_counts) -> str:
    """对单个商品进行分层"""
    price = item["price"] or 0
    margin = item["gross_profit"] or 0
    markup = item["markup_rate"] or 0
    cat = item["category"]

    # 引流品：有引流标识，或售价在底部20%且毛利低
    if item["traffic_flag"]:
        return "traffic"
    if price <= price_p20 and margin <= margin_p70 * 0.5:
        return "traffic"

    # 长尾品：价格在顶部20% + 品类SKU少于10个
    if price >= price_p80 and cat_counts.get(cat, 0) < 10:
        return "long_tail"

    # 利润品：毛利在顶部30% + 加价率在顶部30%
    if margin >= margin_p70 and markup >= markup_p70:
        return "profit"

    # 利润品：加价率>200%
    if markup >= 200:
        return "profit"

    return "regular"


# ============================================================
# 2. 品类差异分析
# ============================================================

def category_gap_analysis(db_path: str, store_id: str) -> dict:
    """
    品类差异分析：对比本店与另一门店的SKU差异
    找出：竞品有、本店无的SKU；本店独有SKU
    """
    store_name = _get_store_name(db_path, store_id)
    items_self = load_store_inventory(db_path, store_id)

    # 找到另一家门店
    other_store_name = None
    other_store_id = None
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    for row in c.execute("SELECT id, name FROM stores WHERE id != ?", (store_id,)):
        other_store_id = row[0]
        other_store_name = row[1]
        break
    conn.close()

    if not other_store_name:
        return {"error": "仅有一家门店，无法做差异分析"}

    other_excel = _resolve_excel_path(other_store_name)
    if not other_excel:
        return {"error": f"未找到门店[{other_store_name}]的库存文件"}
    items_other = _load_excel_inventory(other_excel)

    # 用条码做匹配（优先），无条码用商品名
    self_barcodes = {i["barcode"] for i in items_self if i["barcode"]}
    other_barcodes = {i["barcode"] for i in items_other if i["barcode"]}
    self_names = {i["name"] for i in items_self}
    other_names = {i["name"] for i in items_other}

    # 本店独有
    self_only = []
    for item in items_self:
        is_in_other = (item["barcode"] and item["barcode"] in other_barcodes) or \
                      (item["name"] in other_names and not item["barcode"])
        if not is_in_other:
            self_only.append(item)

    # 对方有、本店没有
    other_only = []
    for item in items_other:
        is_in_self = (item["barcode"] and item["barcode"] in self_barcodes) or \
                     (item["name"] in self_names and not item["barcode"])
        if not is_in_self:
            other_only.append(item)

    # 品类分布对比
    self_cats = defaultdict(int)
    other_cats = defaultdict(int)
    for item in items_self:
        self_cats[item["category"]] += 1
    for item in items_other:
        other_cats[item["category"]] += 1

    all_cats = sorted(set(list(self_cats.keys()) + list(other_cats.keys())))
    cat_compare = []
    for cat in all_cats:
        s = self_cats.get(cat, 0)
        o = other_cats.get(cat, 0)
        cat_compare.append({
            "category": cat,
            "self_count": s,
            "other_count": o,
            "diff": s - o,
        })

    return {
        "self_store": store_name,
        "other_store": other_store_name,
        "self_total": len(items_self),
        "other_total": len(items_other),
        "self_only_count": len(self_only),
        "other_only_count": len(other_only),
        "common_count": len(items_self) - len(self_only),
        "self_only_samples": [{"name": i["name"], "category": i["category"],
                                "price": i["price"]} for i in self_only[:10]],
        "other_only_samples": [{"name": i["name"], "category": i["category"],
                                 "price": i["price"]} for i in other_only[:10]],
        "category_comparison": cat_compare,
    }


# ============================================================
# 3. 滞销品识别
# ============================================================

def identify_slow_moving(db_path: str, store_id: str) -> dict:
    """
    滞销品识别（无销售数据时的启发式算法）：
    - 高价偏离品类均价（>品类均价2倍）
    - 超高加价率（>300%）
    - 长尾品类中高价商品
    - 无条码+无规格+高价（可能是滞销积压品）
    """
    items = load_store_inventory(db_path, store_id)
    if not items:
        return {"error": "无库存数据"}

    # 计算各品类均价
    cat_prices = defaultdict(list)
    for item in items:
        if item["price"] is not None:
            cat_prices[item["category"]].append(item["price"])
    cat_avg = {k: sum(v) / len(v) for k, v in cat_prices.items()}

    cat_counts = defaultdict(int)
    for item in items:
        cat_counts[item["category"]] += 1

    slow_moving = []
    for item in items:
        reasons = []
        price = item["price"] or 0
        markup = item["markup_rate"] or 0
        cat = item["category"]
        avg = cat_avg.get(cat, 0)

        # 规则1: 价格远高于品类均价
        if avg > 0 and price > avg * 2:
            reasons.append(f"售价¥{price:.1f}高于{cat}均价¥{avg:.1f}的{(price/avg-1)*100:.0f}%")

        # 规则2: 超高加价率
        if markup > 300:
            reasons.append(f"加价率{markup:.0f}%过高，可能定价脱离市场")

        # 规则3: 长尾品类+高价
        if cat_counts.get(cat, 0) < 10 and price > 20:
            reasons.append(f"长尾品类[{cat}]仅{cat_counts.get(cat, 0)}个SKU且高价")

        # 规则4: 无条码+无规格+高价
        if not item["barcode"] and not item["spec"] and price > 30:
            reasons.append("无条码无规格且高价，疑似积压品")

        if reasons:
            slow_moving.append({
                "name": item["name"],
                "category": cat,
                "spec": item["spec"],
                "price": price,
                "cost": item["cost"],
                "gross_profit": item["gross_profit"],
                "markup_rate": markup,
                "barcode": item["barcode"],
                "reasons": reasons,
                "suggestion": "建议核查销量，若30天无动销考虑清仓淘汰" if markup > 300 else "建议关注动销情况，适时促销",
            })

    # 按风险排序（reasons数量越多风险越高）
    slow_moving.sort(key=lambda x: -len(x["reasons"]))

    return {
        "total_sku": len(items),
        "slow_moving_count": len(slow_moving),
        "slow_moving_pct": round(len(slow_moving) / len(items) * 100, 1) if items else 0,
        "items": slow_moving[:20],  # Top 20高风险
    }


# ============================================================
# 4. 购物篮关联分析
# ============================================================

def basket_analysis(db_path: str, store_id: str) -> dict:
    """
    购物篮关联分析（基于品类共现的启发式版本）

    注：完整购物篮分析需要POS交易明细数据（每笔交易包含哪些商品）。
    当前版本基于品类互补性给出搭售建议，后续接入POS数据后可升级为
    Apriori/FPGrowth关联规则挖掘。
    """
    items = load_store_inventory(db_path, store_id)
    if not items:
        return {"error": "无库存数据"}

    # 品类互补规则表（便利店场景经验值）
    complementary_rules = [
        {"a": "酒水饮料", "b": "休闲零食", "reason": "饮酒配零食是高频组合"},
        {"a": "酒水饮料", "b": "粮油调味", "reason": "饮料+速食搭配"},
        {"a": "休闲零食", "b": "酒水饮料", "reason": "零食配饮料"},
        {"a": "日化清洁", "b": "日用百货", "reason": "日化+日杂常一起购买"},
        {"a": "母婴用品", "b": "日化清洁", "reason": "宝妈常同时采购洗护用品"},
        {"a": "个护美妆", "b": "日用百货", "reason": "个人护理+日用搭配"},
        {"a": "文具办公", "b": "休闲零食", "reason": "学生文具+零食组合"},
        {"a": "粮油调味", "b": "生鲜果蔬", "reason": "烹饪原料组合"},
        {"a": "速食冷冻", "b": "酒水饮料", "reason": "速食+饮料快餐组合"},
        {"a": "服饰箱包", "b": "日用百货", "reason": "箱包+日用出行搭配"},
    ]

    # 本店品类清单
    cats = defaultdict(int)
    for item in items:
        cats[item["category"]] += 1

    # 匹配本店有效的搭售建议
    suggestions = []
    for rule in complementary_rules:
        if cats.get(rule["a"], 0) > 0 and cats.get(rule["b"], 0) > 0:
            suggestions.append({
                "category_a": rule["a"],
                "category_b": rule["b"],
                "sku_a": cats[rule["a"]],
                "sku_b": cats[rule["b"]],
                "reason": rule["reason"],
                "suggestion": f"建议在{rule['a']}区域附近陈列{rule['b']}，或做组合促销",
            })

    return {
        "total_categories": len(cats),
        "category_distribution": dict(sorted(cats.items(), key=lambda x: -x[1])),
        "cross_sell_suggestions": suggestions,
        "note": "当前为基于品类互补的启发式分析。接入POS交易数据后，可升级为Apriori关联规则挖掘，输出精确的'买A的人也买B'概率和置信度。",
    }


# ============================================================
# 综合分析报告
# ============================================================

def full_analysis(db_path: str, store_id: str) -> dict:
    """一键生成完整选品分析报告"""
    return {
        "classification": classify_products(db_path, store_id),
        "category_gap": category_gap_analysis(db_path, store_id),
        "slow_moving": identify_slow_moving(db_path, store_id),
        "basket": basket_analysis(db_path, store_id),
    }
