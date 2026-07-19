"""鹿小仓对话链路集成：store-pricing-calculator skill

意图路由 + 参数解析 + 硬数据读写 + 标准处方渲染。
命中定价意图时直接走 calculator 出冷酷精准处方，不调 LLM、不抽记忆。

设计铁律（见 skill SKILL.md）：
- 三层数据隔离：硬数据(静默底座) / 软数据(触发开关) / 固定结论(标准模板)
- 防御：综合毛利率<15% 红色拦截；门槛/客单价向上取整到5倍数；缺失硬数据行业均值兜底
"""
import os
import re
import sqlite3

from calculator import StorePricingCalculator, MarginTooLowError

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")

# 硬数据字段（与 calculator.INDUSTRY_DEFAULTS 键一致）
HARD_FIELDS = [
    "gross_margin_rate", "delivery_cost_per_order", "packaging_cost_per_order",
    "daily_traffic_avg", "total_fixed_cost", "target_net_profit",
]


def db_query(sql, params=(), fetch="all"):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ────────────────── 意图识别 ──────────────────
def detect_pricing_intent(message: str):
    """返回 (intent_type, params) 或 None。"""
    t = message
    # 1) 满减：满X减Y
    m = re.search(r"满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)", t)
    if m:
        return ("campaign", {"threshold": float(m.group(1)), "discount": float(m.group(2))})
    # 2) 免运费门槛
    if re.search(r"免\s*运\s*费", t):
        tm = re.search(r"门槛\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*元", t)
        thr = float(tm.group(1) or tm.group(2)) if tm else None
        return ("free_delivery", {"threshold": thr})
    # 3) 盈亏平衡 / 保本
    if "盈亏平衡" in t or "保本" in t:
        return ("breakeven", {})
    # 4) 设置硬数据
    if any(k in t for k in ["毛利率", "配送", "包装", "来客", "固定成本", "客单价"]):
        pars = parse_hard_data(t)
        if pars:
            return ("set_hard", pars)
    return None


def parse_hard_data(text: str):
    pars = {}
    # 毛利率 30% 或 0.3
    m = re.search(r"毛利率\s*(\d+(?:\.\d+)?)\s*%?", text)
    if m:
        v = float(m.group(1))
        pars["gross_margin_rate"] = v / 100.0 if v > 1 else v
    # 配送成本：每单配送3.5元
    m = re.search(r"配送[^\d\n]*?(\d+(?:\.\d+)?)\s*元", text)
    if m:
        pars["delivery_cost_per_order"] = float(m.group(1))
    # 包装成本：包装0.5元
    m = re.search(r"包装[^\d\n]*?(\d+(?:\.\d+)?)\s*元", text)
    if m:
        pars["packaging_cost_per_order"] = float(m.group(1))
    # 日均来客：日均来客250
    m = re.search(r"日均[^\d\n]*?(\d+(?:\.\d+)?)", text)
    if m:
        pars["daily_traffic_avg"] = float(m.group(1))
    # 月固定成本：月固定成本30000
    m = re.search(r"固定成本[^\d\n]*?(\d+(?:\.\d+)?)", text)
    if m:
        pars["total_fixed_cost"] = float(m.group(1))
    # 目标净利润
    m = re.search(r"目标[^\d\n]*?利润[^\d\n]*?(\d+(?:\.\d+)?)", text)
    if m:
        pars["target_net_profit"] = float(m.group(1))
    # 客单价
    m = re.search(r"客单价[^\d\n]*?(\d+(?:\.\d+)?)", text)
    if m:
        pars["avg_ticket_size"] = float(m.group(1))
    return pars


# ────────────────── 硬数据读写（变量池，跨轮持久化）──────────────────
def get_hard_data(store_id):
    if not store_id:
        return {}
    row = db_query(
        "SELECT * FROM store_variable_cost WHERE store_id=? ORDER BY param_id DESC LIMIT 1",
        (store_id,), fetch="one")
    if not row:
        return {}
    return {k: row[k] for k in HARD_FIELDS if row[k] is not None}


def save_hard_data(store_id, pars):
    if not store_id:
        return
    existing = get_hard_data(store_id)
    merged = {**existing, **pars}
    gm = merged.get("gross_margin_rate")
    db_query("DELETE FROM store_variable_cost WHERE store_id=?", (store_id,))
    db_query(
        """INSERT INTO store_variable_cost
           (store_id, effective_date, gross_margin_rate, target_gross_margin,
            delivery_cost_per_order, packaging_cost_per_order, daily_traffic_avg,
            total_fixed_cost, target_net_profit)
           VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)""",
        (store_id, gm, gm,
         merged.get("delivery_cost_per_order"), merged.get("packaging_cost_per_order"),
         merged.get("daily_traffic_avg"), merged.get("total_fixed_cost"),
         merged.get("target_net_profit")),
        fetch="commit")


# ────────────────── 处方渲染（固定结论层，套 SKILL.md 模板）──────────────────
def render_campaign(r):
    if r["decision"].startswith("❌"):
        advice = (f"建议将门槛提至 {r['recommended_threshold']:.0f} 元，"
                  f"单笔方可转正（当前净利 {r['net_profit_per_order']} 元）。")
    else:
        advice = (f"该活动可做，单笔净利约 {r['net_profit_per_order']} 元，"
                  f"建议门槛 {r['recommended_threshold']:.0f} 元。")
    return (
        "📊 【盈利测算处方】\n"
        f"活动：{r['campaign']}\n"
        "──────────────────\n"
        f"• 单笔毛利（满减后）：{r['gross_after_discount']} 元\n"
        f"• 扣变动成本后净利：{r['net_profit_per_order']} 元\n"
        f"• 判定：{r['decision']}\n"
        f"• 建议门槛（取整5倍数）：{r['recommended_threshold']:.0f} 元\n"
        f"• 数据来源：{r['source_note']}\n"
        "──────────────────\n"
        f"💡 处方：{advice}"
    )


def render_free_delivery(r):
    lines = [
        "🚚 【免运费门槛测算】",
        "──────────────────",
        f"• 每单配送成本：{r['delivery_cost_per_order']} 元",
        f"• 综合毛利率：{r['gross_margin_rate']*100:.1f}%",
        f"• 安全最低门槛（裸值）：{r['safe_threshold_raw']} 元",
        f"• 建议免运费门槛（取整5倍数）：{r['recommended_threshold']:.0f} 元",
        f"• 数据来源：{r['source_note']}",
    ]
    if "proposed_threshold" in r:
        lines.append(f"• 你给的门槛 {r['proposed_threshold']:.0f} 元 → {r['verdict']}")
        if r["is_loss"]:
            lines.append(f"💡 处方：该门槛会亏，请把免运费门槛提到 {r['recommended_threshold']:.0f} 元及以上。")
        else:
            lines.append("💡 处方：该门槛可覆盖配送成本，可做。")
    else:
        lines.append(f"💡 处方：免运费门槛建议设在 {r['recommended_threshold']:.0f} 元及以上，避免每单贴钱。")
    return "\n".join(lines)


def render_breakeven(r):
    return (
        "📉 【盈亏平衡点】\n"
        "──────────────────\n"
        f"• 月固定成本：{r['total_fixed_cost']} 元\n"
        f"• 综合毛利率：{r['gross_margin_rate']*100:.1f}%\n"
        f"• 每单变动成本：{r['variable_per_order']} 元\n"
        f"• 盈亏平衡客单价：{r['breakeven_ticket']:.0f} 元（已含变动成本）\n"
        f"• 盈亏平衡日均单量：{r['breakeven_daily_orders']} 单\n"
        f"• 数据来源：{r['source_note']}\n"
        "──────────────────\n"
        "💡 处方：客单价/单量低于上述平衡点即亏损，定价与活动需守住此线。"
    )


def render_set_hard(pars):
    label = {
        "gross_margin_rate": "综合毛利率",
        "delivery_cost_per_order": "每单配送成本",
        "packaging_cost_per_order": "每单包装成本",
        "daily_traffic_avg": "日均来客数",
        "total_fixed_cost": "月固定成本",
        "target_net_profit": "目标月净利润",
        "avg_ticket_size": "客单价",
    }
    items = []
    for k, v in pars.items():
        if k == "gross_margin_rate":
            items.append(f"{label.get(k, k)}：{v*100:.1f}%")
        else:
            unit = " 元" if any(x in k for x in ("cost", "fixed", "profit", "ticket")) else ""
            items.append(f"{label.get(k, k)}：{v}{unit}")
    return ("✅ 已记录门店硬数据（后续测算自动调用，不再追问）：\n• "
            + "\n• ".join(items)
            + "\n⚠️ 缺项将用行业均值兜底并在结论中标注。")


# ────────────────── 主入口 ──────────────────
def handle_pricing(message: str, store_id=None):
    """返回 (reply_text, is_pricing)。非定价意图返回 (None, False)。"""
    intent = detect_pricing_intent(message)
    if not intent:
        return None, False
    itype, params = intent

    if itype == "set_hard":
        save_hard_data(store_id, params)
        return render_set_hard(params), True

    calc = StorePricingCalculator()
    hard = get_hard_data(store_id)
    if hard:
        calc.set_hard(hard)
    try:
        if itype == "campaign":
            return render_campaign(calc.evaluate_campaign(params["threshold"], params["discount"])), True
        if itype == "free_delivery":
            return render_free_delivery(calc.recommend_free_delivery(params.get("threshold"))), True
        if itype == "breakeven":
            return render_breakeven(calc.breakeven()), True
    except MarginTooLowError as e:
        return str(e), True
    return None, False


# ────────────────── 核心支点：财务底座锚点（注入 LLM 上下文）──────────────────
def build_pricing_anchor(store_id=None) -> str:
    """构建门店"财务底座"文本块，注入每一轮对话的 LLM 上下文。

    这是 store-pricing-calculator 作为「核心支点」的体现：
    - 显式定价问题仍由 handle_pricing 走精确处方（不调 LLM）；
    - 其余所有经营/策略/营销对话，都先把这本财务账摆到 LLM 面前，
      让大模型的一切建议都踩在真实盈亏数字上，不脱离底线、不拍脑袋。

    返回一段可直接拼进 system prompt 的 markdown；无 store_id 时返回空串。
    """
    if not store_id:
        return ""
    calc = StorePricingCalculator()
    hard = get_hard_data(store_id)
    if hard:
        calc.set_hard(hard)

    lines = ["\n\n## 门店财务底座（定价/策略测算的唯一依据，务必遵守）"]
    try:
        be = calc.breakeven()
        fd = calc.recommend_free_delivery()
        lines.append(f"- 综合毛利率：{be['gross_margin_rate']*100:.1f}%")
        lines.append(f"- 盈亏平衡客单价：¥{be['breakeven_ticket']:.0f}（客单价低于此值即亏损）")
        lines.append(f"- 盈亏平衡日均单量：{be['breakeven_daily_orders']:.0f} 单")
        lines.append(f"- 每单变动成本（配送+包装）：¥{be['variable_per_order']:.1f}")
        lines.append(f"- 安全免运费门槛：¥{fd['recommended_threshold']:.0f} 及以上（低于此值每单贴钱）")
        lines.append(f"- 数据来源：{be['source_note']}")
    except MarginTooLowError:
        lines.append("- 🔴 综合毛利率已低于 15% 红线，当前无法安全支撑任何满减/折扣/免运费活动。")
        lines.append("- 首要任务：先优化商品结构、提升毛利，再谈任何营销活动。")
        lines.append(f"- 数据来源：{'真实门店输入' if hard else '⚠️ 缺硬数据，建议先录入毛利率/配送成本/日均来客/固定成本'}")

    lines.append("\n### 定价策略铁律（回答任何经营/营销/定价问题时必须遵守）")
    lines.append("1. 凡涉及价格、满减、折扣、免运费、客单价、促销活动的建议，必须以上述财务底座为准；"
                 "不得建议低于盈亏平衡客单价的定价，不得突破 15% 毛利红线。")
    lines.append("2. 老板提出具体活动（如\"满X减Y\"\"免运费门槛N元\"\"盈亏平衡\"）时，系统会自动用计算器出精确处方；"
                 "你不要口算或凭感觉给数字，引导老板直接说出具体活动即可获得精确测算。")
    lines.append("3. 若财务底座标注为「行业均值兜底」，说明门店真实硬数据缺失——回答时提醒老板补录"
                 "（毛利率/每单配送成本/日均来客/月固定成本），以便后续测算更精准。")
    return "\n".join(lines)
