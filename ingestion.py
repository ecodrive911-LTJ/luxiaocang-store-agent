"""
鹿小仓 — 内部数据采集接入层 (路线A: raw_data 数据湖 + 手动导入)

职责：
1. 接收店主从美团/饿了么/收银后台导出的 Excel/CSV
2. 用「灵活中英文列映射」解析成结构化行，原样存入 raw_data 原始数据湖
   (raw_orders / raw_reviews / raw_items)，不加工、可追溯
3. 提供真实经营聚合：GMV / 真实毛利 / 订单数 / 客单价 / 动销率
   （毛利通过商品名称匹配库存成本 best-effort 计算）
4. 导入批次管理 + 历史查询 + 模板生成

设计原则：
- 零重依赖：xlsx 用 openpyxl，csv 用标准库 csv，不引入 pandas
- 列名容错：支持美团原生中文导出列名，也支持英文/拼音别名
- 原始优先：先原样落库，再聚合，避免解析即丢信息
"""

import csv
import io
import os
import random
import re
import sqlite3
import time
from datetime import datetime


# ===================== 灵活列映射（中英文别名） =====================
# 每个字段对应一组别名；解析时把表头归一化后匹配。
def _norm(s):
    if s is None:
        return ""
    return re.sub(r"\s+", "", str(s)).lower().replace("：", ":").strip()


ORDERS_ALIASES = {
    "order_id": ["订单号", "订单编号", "订单id", "orderid", "order_id", "orderno", "单号", "订单"],
    "order_time": ["下单时间", "下单日期", "下单时刻", "时间", "日期", "ordertime", "created_at", "orderdate", "日期时间"],
    "product_name": ["商品名称", "商品", "菜品", "菜品名称", "产品", "产品名称", "名称", "product", "item", "name", "goods"],
    "quantity": ["数量", "份数", "件数", "购买数量", "qty", "quantity", "count", "num", "个数"],
    "unit_price": ["单价", "价格", "原价", "商品单价", "unitprice", "price", "unit_price"],
    "amount": ["实付金额", "实际支付", "支付金额", "金额", "小计", "实付", "实收", "amount", "pay", "paid", "total", "成交金额"],
    "category": ["品类", "分类", "商品分类", "category", "cat", "类目"],
}

REVIEWS_ALIASES = {
    "review_id": ["评价id", "评价编号", "评价id号", "reviewid", "review_id", "id", "编号"],
    "review_time": ["评价时间", "评论时间", "时间", "日期", "reviewtime", "created_at", "time"],
    "rating": ["评分", "星级", "评分星级", "rating", "score", "star", "星"],
    "content": ["评价内容", "评论内容", "内容", "评价", "评论", "content", "text", "review", "备注"],
}

ITEMS_ALIASES = {
    "item_name": ["商品名称", "商品", "名称", "产品", "item", "name", "goods", "菜品"],
    "on_sale": ["是否上架", "在售", "上架", "售卖状态", "onsale", "online", "status", "状态", "是否在线"],
    "price": ["价格", "售价", "单价", "销售价", "price", "sale_price"],
    "category": ["品类", "分类", "类目", "category", "cat"],
}


def _build_header_map(header, aliases):
    """返回 {规范字段: 表头列索引}"""
    normed = [_norm(h) for h in header]
    mapping = {}
    for field, alias_list in aliases.items():
        for alias in alias_list:
            a = _norm(alias)
            if not a:
                continue
            for idx, h in enumerate(normed):
                if h == a or a in h or h in a:
                    mapping[field] = idx
                    break
            if field in mapping:
                break
    return mapping


def _read_sheet(content: bytes, filename: str):
    """读取 xlsx/csv 内容，返回 (header_list, data_rows)

    header_list: 第一行表头
    data_rows: 后续每行（list，与 header 等长或更长）
    """
    ext = (filename or "").lower()
    if ext.endswith(".csv"):
        # 尝试 utf-8-sig / gbk
        text = None
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = content.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            text = content.decode("utf-8", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        if not reader:
            return [], []
        header = reader[0]
        return header, reader[1:]
    else:
        # xlsx / xls -> openpyxl
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return [], []
        header = [str(c) if c is not None else "" for c in rows[0]]
        data = []
        for r in rows[1:]:
            if r is None:
                continue
            data.append([c for c in r])
        return header, data


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v))
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_rows(header, data_rows, aliases):
    """把原始行按列映射转成规范 dict 列表"""
    hmap = _build_header_map(header, aliases)
    out = []
    for row in data_rows:
        if row is None:
            continue
        # 空行跳过
        if all((c is None or str(c).strip() == "") for c in row):
            continue
        rec = {}
        for field, idx in hmap.items():
            val = row[idx] if idx < len(row) else None
            rec[field] = val
        out.append(rec)
    return out, hmap


# ===================== 入库 =====================
def new_batch_id(prefix: str = "IMP") -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100, 999)}"


def _record_batch(db_path, batch_id, store_id, data_type, filename, row_count, status, imported_by, note=""):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO import_batches (batch_id, store_id, data_type, filename, row_count, status, note, imported_by, imported_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, store_id, data_type, filename, row_count, status, note, imported_by, time.time()),
    )
    conn.commit()
    conn.close()


def import_orders(db_path, store_id, recs, batch_id, filename, imported_by):
    """recs: list of {order_id, order_time, product_name, quantity, unit_price, amount, category}"""
    conn = sqlite3.connect(db_path)
    n = 0
    for r in recs:
        pname = (r.get("product_name") or "").strip()
        if not pname:
            continue
        qty = _to_float(r.get("quantity")) or 1.0
        amount = _to_float(r.get("amount"))
        if amount is None:
            up = _to_float(r.get("unit_price")) or 0
            amount = round(up * qty, 2)
        cat = (r.get("category") or "").strip()
        conn.execute(
            "INSERT INTO raw_orders (store_id, order_id, order_time, product_name, quantity, unit_price, amount, category, batch_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (store_id, str(r.get("order_id") or "")[:64], str(r.get("order_time") or "")[:32],
             pname, qty, _to_float(r.get("unit_price")), amount, cat, batch_id),
        )
        n += 1
    conn.commit()
    conn.close()
    _record_batch(db_path, batch_id, store_id, "orders", filename, n, "done", imported_by)
    return n


def import_reviews(db_path, store_id, recs, batch_id, filename, imported_by):
    conn = sqlite3.connect(db_path)
    n = 0
    for r in recs:
        content = (r.get("content") or "").strip()
        if not content and not r.get("rating"):
            continue
        rating = _to_float(r.get("rating"))
        conn.execute(
            "INSERT INTO raw_reviews (store_id, review_id, review_time, rating, content, batch_id) "
            "VALUES (?,?,?,?,?,?)",
            (store_id, str(r.get("review_id") or "")[:64], str(r.get("review_time") or "")[:32],
             rating, content, batch_id),
        )
        n += 1
    conn.commit()
    conn.close()
    _record_batch(db_path, batch_id, store_id, "reviews", filename, n, "done", imported_by)
    return n


def import_items(db_path, store_id, recs, batch_id, filename, imported_by):
    conn = sqlite3.connect(db_path)
    n = 0
    for r in recs:
        name = (r.get("item_name") or "").strip()
        if not name:
            continue
        on_sale_raw = str(r.get("on_sale") or "").strip().lower()
        on_sale = 1 if on_sale_raw in ("是", "上架", "1", "true", "在线", "on", "yes", "售卖") else 0
        conn.execute(
            "INSERT INTO raw_items (store_id, item_name, on_sale, price, category, batch_id) "
            "VALUES (?,?,?,?,?,?)",
            (store_id, name, on_sale, _to_float(r.get("price")), (r.get("category") or "").strip(), batch_id),
        )
        n += 1
    conn.commit()
    conn.close()
    _record_batch(db_path, batch_id, store_id, "items", filename, n, "done", imported_by)
    return n


# ===================== 解析入口（对外） =====================
def parse_and_import(db_path, store_id, data_type, filename, content, imported_by):
    """统一入口：解析 + 入库，返回 {inserted, batch_id, mapped_fields, sample}"""
    if data_type not in ("orders", "reviews", "items"):
        raise ValueError("data_type 必须是 orders/reviews/items")
    header, data_rows = _read_sheet(content, filename)
    if not header:
        raise ValueError("文件为空或无法读取表头")
    aliases = {"orders": ORDERS_ALIASES, "reviews": REVIEWS_ALIASES, "items": ITEMS_ALIASES}[data_type]
    recs, hmap = _parse_rows(header, data_rows, aliases)
    if not recs:
        raise ValueError("未解析到任何有效数据行（请检查表头列名）")

    batch_id = new_batch_id(data_type.upper()[:3])
    if data_type == "orders":
        inserted = import_orders(db_path, store_id, recs, batch_id, filename, imported_by)
    elif data_type == "reviews":
        inserted = import_reviews(db_path, store_id, recs, batch_id, filename, imported_by)
    else:
        inserted = import_items(db_path, store_id, recs, batch_id, filename, imported_by)

    return {
        "inserted": inserted,
        "batch_id": batch_id,
        "mapped_fields": list(hmap.keys()),
        "total_header": header,
        "sample": recs[:3],
    }


# ===================== 真实经营聚合 =====================
def get_real_sales_summary(db_path, store_id):
    """从 raw_orders 聚合真实经营指标；毛利通过商品名匹配库存成本 best-effort"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(amount),0), COUNT(DISTINCT order_id), COUNT(*) "
        "FROM raw_orders WHERE store_id=?",
        (store_id,),
    )
    gmv, distinct_orders, rows = cur.fetchone()
    gmv = float(gmv or 0)
    order_count = int(distinct_orders or 0)
    if order_count == 0:
        order_count = int(rows or 0)
    aov = round(gmv / order_count, 2) if order_count else 0

    cur.execute("SELECT COUNT(DISTINCT product_name) FROM raw_orders WHERE store_id=?", (store_id,))
    sold_skus = int(cur.fetchone()[0] or 0)

    inv_skus = 0
    name2cost = {}
    try:
        from product_analysis import load_store_inventory
        inv = load_store_inventory(db_path, store_id)
        inv_skus = len(inv)
        for it in inv:
            nm = (it.get("name") or "").strip()
            if nm:
                name2cost[nm] = it.get("cost")
    except Exception:
        inv = []

    sell_through = round(sold_skus / inv_skus * 100, 1) if inv_skus else 0

    real_gp = None
    matched_gmv = 0.0
    if inv and name2cost:
        cur.execute("SELECT product_name, quantity, amount FROM raw_orders WHERE store_id=?", (store_id,))
        for pname, qty, amt in cur.fetchall():
            cost = name2cost.get((pname or "").strip())
            if cost is not None and qty:
                real_gp = (real_gp or 0) + (float(amt or 0) - float(cost) * float(qty))
                matched_gmv += float(amt or 0)

    conn.close()
    return {
        "has_real": rows > 0,
        "real_gmv": round(gmv, 2),
        "order_count": order_count,
        "avg_order_value": aov,
        "sell_through_rate": sell_through,
        "sold_skus": sold_skus,
        "inv_skus": inv_skus,
        "real_gross_profit": round(real_gp, 2) if real_gp is not None else None,
        "matched_gmv": round(matched_gmv, 2),
    }


def get_import_history(db_path, store_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT batch_id, data_type, filename, row_count, status, note, imported_at "
        "FROM import_batches WHERE store_id=? ORDER BY imported_at DESC LIMIT 50",
        (store_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===================== 模板生成 =====================
TEMPLATE_COLUMNS = {
    "orders": ["订单号", "下单时间", "商品名称", "数量", "单价", "实付金额", "品类"],
    "reviews": ["评价编号", "评价时间", "评分", "评价内容"],
    "items": ["商品名称", "是否上架", "价格", "品类"],
}


def make_template_csv(data_type):
    cols = TEMPLATE_COLUMNS.get(data_type, TEMPLATE_COLUMNS["orders"])
    import io as _io
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    # 给一行示例
    if data_type == "orders":
        w.writerow(["M20260716001", "2026-07-16 19:30", "可口可乐330ml", "2", "3.0", "6.0", "饮料"])
    elif data_type == "reviews":
        w.writerow(["R001", "2026-07-16 20:10", "5", "送货快，商品新鲜"])
    else:
        w.writerow(["可口可乐330ml", "是", "3.0", "饮料"])
    return buf.getvalue()
