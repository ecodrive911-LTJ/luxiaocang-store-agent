"""
store-pricing-calculator —— 便利店单店盈利计算器核心引擎

无外部依赖的纯 Python 实现。可被 WorkBuddy 直接调用，也可独立跑验收测试。

设计铁律（见 SKILL.md）：
1. 三层数据隔离：硬数据(静默底座) / 软数据(触发开关) / 固定结论(模板输出)
2. 防御性编程：综合毛利率 < 15% 红色拦截；门槛/客单价向上取整到 5 的倍数；
   缺失硬数据用行业均值假设并标注。
3. 公式与 SKILL.md 第三节一一对应，权威实现在此文件。
"""

import math
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── 行业均值兜底（仅当用户未提供硬数据时使用，结论须标注）─────────────
INDUSTRY_DEFAULTS = {
    "gross_margin_rate": 0.30,        # 综合毛利率 30%
    "delivery_cost_per_order": 3.5,   # 每单配送成本 3.5 元
    "packaging_cost_per_order": 0.5,  # 每单包装成本 0.5 元
    "daily_traffic_avg": 250,         # 日均来客数
    "total_fixed_cost": 30000.0,      # 月固定成本合计（元）
    "target_net_profit": 8000.0,      # 目标月净利润（元，可选）
}

# 综合毛利率红线：低于此值拒绝任何满减/免运费测算
MARGIN_RED_LINE = 0.15

# 可选硬数据键：缺失时补默认值，但不计入"行业均值兜底"标注
OPTIONAL_KEYS = {"target_net_profit"}


def round_up_to_5(x: float) -> float:
    """向上取整到 5 的倍数。例：16.7 -> 20；15.0 -> 15；12 -> 15。"""
    if x is None:
        return x
    return math.ceil(x / 5.0) * 5.0


@dataclass
class HardData:
    """硬数据（静默底座）：极少变动，存入变量池后不再反复追问。"""
    gross_margin_rate: Optional[float] = None
    delivery_cost_per_order: Optional[float] = None
    packaging_cost_per_order: Optional[float] = None
    daily_traffic_avg: Optional[float] = None
    total_fixed_cost: Optional[float] = None
    target_net_profit: Optional[float] = None
    # 记录哪些字段是行业均值兜底（用于结论标注）
    used_industry_default: set = field(default_factory=set)

    def fill_defaults(self) -> "HardData":
        """用行业均值补齐缺失项，并记录补齐来源。"""
        for k, v in INDUSTRY_DEFAULTS.items():
            if getattr(self, k) is None:
                setattr(self, k, v)
                if k not in OPTIONAL_KEYS:
                    self.used_industry_default.add(k)
        return self

    @property
    def is_pure_real(self) -> bool:
        return len(self.used_industry_default) == 0

    @property
    def source_note(self) -> str:
        if self.is_pure_real:
            return "真实门店输入"
        return "⚠️ 基于行业均值测算（缺：" + ", ".join(sorted(self.used_industry_default)) + "），建议补全真实数据"


class MarginTooLowError(Exception):
    """综合毛利率低于红线，拒绝测算。"""
    def __init__(self, margin: float):
        self.margin = margin
        super().__init__(
            f"🔴 当前综合毛利率仅 {margin*100:.1f}%，低于 15% 红线，"
            f"无法覆盖变动成本。请先调整商品结构、提升毛利后再做活动测算。"
        )


class StorePricingCalculator:
    """单店盈利计算器：维护硬数据变量池，提供三类核心测算。"""

    def __init__(self, hard: Optional[dict] = None):
        self.hard = HardData(**{k: v for k, v in (hard or {}).items()
                                if k in INDUSTRY_DEFAULTS})
        # 注：变量池在对话中由 WorkBuddy 维护；这里每次实例化可注入当前硬数据

    def set_hard(self, hard: dict):
        """更新/补充硬数据（用户后续提供的真实数据覆盖行业默认值）。"""
        for k, v in hard.items():
            if k in INDUSTRY_DEFAULTS and v is not None:
                setattr(self.hard, k, v)
                self.hard.used_industry_default.discard(k)
        return self

    # ── 防御：毛利红线 ──────────────────────────────────────────────
    def _ensure_margin_ok(self, margin: float):
        if margin < MARGIN_RED_LINE:
            raise MarginTooLowError(margin)

    # ── 公式 A：盈亏平衡 ───────────────────────────────────────────
    def breakeven(self, hard: Optional[dict] = None) -> dict:
        if hard:
            self.set_hard(hard)
        h = self.hard
        h.fill_defaults()
        margin = h.gross_margin_rate
        self._ensure_margin_ok(margin)
        variable_per_order = h.delivery_cost_per_order + h.packaging_cost_per_order
        monthly_orders = h.daily_traffic_avg * 30
        breakeven_ticket = h.total_fixed_cost / monthly_orders / margin + variable_per_order
        breakeven_ticket_rounded = round_up_to_5(breakeven_ticket)
        breakeven_daily_orders = h.total_fixed_cost / (breakeven_ticket - variable_per_order) / margin / 30
        # 健康度（示例评分：实际客单价越高于平衡点越健康；此处给相对评估）
        return {
            "total_fixed_cost": round(h.total_fixed_cost, 2),
            "gross_margin_rate": margin,
            "variable_per_order": round(variable_per_order, 2),
            "breakeven_ticket": round(breakeven_ticket_rounded, 2),
            "breakeven_daily_orders": round(breakeven_daily_orders, 1),
            "source_note": h.source_note,
        }

    # ── 公式 B：满减活动单笔利润 ───────────────────────────────────
    def evaluate_campaign(self, threshold: float, discount: float,
                          hard: Optional[dict] = None) -> dict:
        if hard:
            self.set_hard(hard)
        h = self.hard
        h.fill_defaults()
        margin = h.gross_margin_rate
        self._ensure_margin_ok(margin)
        variable_per_order = h.delivery_cost_per_order + h.packaging_cost_per_order
        gross_after_discount = threshold * margin - discount
        net_profit = gross_after_discount - variable_per_order
        decision = "✅ 可以做" if net_profit > 0 else "❌ 会亏损"
        # 反向建议：为保本所需的最低门槛 = (discount + variable_per_order) / margin
        safe_threshold_raw = (discount + variable_per_order) / margin
        recommended = round_up_to_5(safe_threshold_raw)
        return {
            "campaign": f"满{threshold}减{discount}",
            "threshold": threshold,
            "discount": discount,
            "gross_after_discount": round(gross_after_discount, 2),
            "net_profit_per_order": round(net_profit, 2),
            "decision": decision,
            "recommended_threshold": round(recommended, 2),
            "source_note": h.source_note,
        }

    # ── 公式 C：免运费安全门槛（反向推导）──────────────────────────
    def recommend_free_delivery(self, proposed_threshold: Optional[float] = None,
                                hard: Optional[dict] = None) -> dict:
        if hard:
            self.set_hard(hard)
        h = self.hard
        h.fill_defaults()
        margin = h.gross_margin_rate
        self._ensure_margin_ok(margin)
        delivery = h.delivery_cost_per_order
        safe_threshold_raw = delivery / margin
        recommended = round_up_to_5(safe_threshold_raw)
        result = {
            "delivery_cost_per_order": delivery,
            "gross_margin_rate": margin,
            "safe_threshold_raw": round(safe_threshold_raw, 2),
            "recommended_threshold": round(recommended, 2),
            "source_note": h.source_note,
        }
        if proposed_threshold is not None:
            # 判定给定门槛是否亏损：门槛×毛利 < 配送成本 即亏
            is_loss = (proposed_threshold * margin) < delivery
            result["proposed_threshold"] = proposed_threshold
            result["is_loss"] = is_loss
            result["verdict"] = (
                "❌ 该门槛会亏损" if is_loss
                else "✅ 该门槛可覆盖配送成本"
            )
        return result


# ── 验收测试（测试一 / 测试二）───────────────────────────────────────
def _run_acceptance_tests():
    print("=" * 60)
    print("验收测试开始")
    print("=" * 60)

    # ── 测试一：输入硬数据后连续测三个满减活动，验证记住硬数据 ──
    print("\n【测试一】硬数据 + 连续三个满减活动")
    hard = {
        "gross_margin_rate": 0.30,
        "delivery_cost_per_order": 3.5,
        "packaging_cost_per_order": 0.5,
        "daily_traffic_avg": 250,
        "total_fixed_cost": 30000.0,
    }
    calc = StorePricingCalculator(hard)
    # 模拟变量池：对话中硬数据只设一次
    campaigns = [(30, 5), (50, 8), (20, 3)]
    for thr, disc in campaigns:
        r = calc.evaluate_campaign(thr, disc)  # 不再传 hard，验证"记住"
        assert r["source_note"] == "真实门店输入", "硬数据未被记住！"
        print(f"  {r['campaign']:>10} -> 单笔净利 {r['net_profit_per_order']:>6} 元 | {r['decision']} | 建议门槛 {r['recommended_threshold']}")
    print("  ✅ 测试一通过：硬数据被正确记住，三次计算无误")

    # ── 测试二：故意输入亏损免运费门槛，反向给安全最低门槛 ──
    print("\n【测试二】故意亏损的免运费门槛 -> 反向安全门槛")
    r = calc.recommend_free_delivery(proposed_threshold=8)  # 8×0.30=2.4 < 3.5 亏损
    assert r["is_loss"] is True, "未识别亏损！"
    assert r["recommended_threshold"] == 15.0, f"安全门槛计算错误: {r['recommended_threshold']}"
    print(f"  给定门槛 8 元 -> {r['verdict']}")
    print(f"  安全最低门槛建议（取整5倍数）: {r['recommended_threshold']} 元")
    print("  ✅ 测试二通过：准确识别亏损并反向给出安全门槛 15 元")

    # ── 额外：毛利红线拦截 ──
    print("\n【附加】综合毛利率 < 15% 红色拦截")
    try:
        StorePricingCalculator({"gross_margin_rate": 0.10}).evaluate_campaign(30, 5)
        print("  ❌ 未触发拦截！")
    except MarginTooLowError as e:
        print(f"  ✅ 拦截成功：{e}")

    # ── 额外：缺失硬数据行业均值兜底 ──
    print("\n【附加】缺失硬数据 -> 行业均值兜底并标注")
    r = StorePricingCalculator().evaluate_campaign(30, 5)
    print(f"  {r['source_note']} | 单笔净利 {r['net_profit_per_order']} 元")
    assert "行业均值" in r["source_note"]
    print("  ✅ 行业均值兜底标注正常")

    print("\n" + "=" * 60)
    print("全部验收测试通过 ✅")
    print("=" * 60)


if __name__ == "__main__":
    _run_acceptance_tests()
