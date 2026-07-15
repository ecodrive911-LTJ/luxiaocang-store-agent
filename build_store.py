"""
鹿小仓 — 建店规划引擎 (D2-后续 · 建店引擎)

功能：
1. 面积 → 品类权重规划（按便利店标准品类结构推算各品类面积占比）
2. 面积 → SKU 推算（按卖场面积密度估算首批进货 SKU 数）
3. 品类权重 → 货架方案（货架组数 / 冷柜数量 / 动线建议）

说明：
- 本引擎为「规划启发式工具」，品类权重、SKU 密度为行业经验默认值，
  全部以常量形式集中定义，便于后续按门店实际数据校准。
- 非安全关键逻辑，输出为「建议方案」，最终由人工/AI 决策采纳。
- 输入：门店卖场面积(㎡)，可选门店层级(tier)与是否含鲜食/烟证等。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

# ─────────────────────────────────────────────────────────────
# 默认启发式参数（行业经验值，集中管理，便于校准）
# ─────────────────────────────────────────────────────────────

# 便利店标准品类结构（按卖场面积占比估算）
# key: 品类名, value: 默认面积权重(%) —— 合计应为 100
DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "饮料饮品": 22.0,
    "休闲零食": 18.0,
    "方便速食": 16.0,
    "烟酒": 12.0,
    "乳品烘焙": 10.0,
    "日用百货": 10.0,
    "冷藏冷冻": 7.0,
    "文具杂志其他": 5.0,
}

# SKU 密度（每㎡卖场面积承载的 SKU 数）—— 小店密度更高
# 采用分段密度，避免过度线性外推
def _sku_density(area_m2: float) -> float:
    """按面积分段的 SKU 密度(个/㎡)。"""
    if area_m2 <= 60:
        return 22.0      # 微型社区店，高密度
    elif area_m2 <= 120:
        return 19.0      # 标准便利店
    elif area_m2 <= 250:
        return 16.0      # 中型店
    else:
        return 13.0      # 大型店，密度下降


# 单组货架(双面 gondola)约占卖场面积(㎡) —— 用于反推货架组数
SHELF_UNIT_AREA_M2 = 2.6

# 含鲜食/冷柜的门店最低面积阈值
FRESH_MIN_AREA_M2 = 80.0


@dataclass
class CategoryPlan:
    category: str
    weight_pct: float
    area_m2: float
    shelf_units: int
    estimated_sku: int


@dataclass
class BuildStorePlan:
    area_m2: float
    tier: str
    has_fresh: bool
    has_tobacco: bool
    estimated_sku: int
    category_plan: list = field(default_factory=list)
    shelf_layout: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category_plan"] = [asdict(c) for c in self.category_plan]
        return d


def build_store_plan(
    area_m2: float,
    tier: str = "standard",
    has_fresh: Optional[bool] = None,
    has_tobacco: bool = True,
    category_weights: Optional[dict[str, float]] = None,
) -> BuildStorePlan:
    """
    生成建店规划方案。

    :param area_m2: 卖场面积(㎡)，需 > 0
    :param tier: 门店层级(standard/premium/community)，影响 SKU 密度微调
    :param has_fresh: 是否规划鲜食岛/热食；默认按面积自动判定
    :param has_tobacco: 是否含烟证(烟酒品类)，默认 True
    :param category_weights: 自定义品类权重覆盖默认
    :return: BuildStorePlan
    """
    if area_m2 <= 0:
        raise ValueError("门店面积必须为正数")

    weights = dict(category_weights or DEFAULT_CATEGORY_WEIGHTS)
    if not has_tobacco and "烟酒" in weights:
        # 无烟证时，将烟酒权重平摊到其他品类
        removed = weights.pop("烟酒")
        for k in weights:
            weights[k] += removed / len(weights)

    if has_fresh is None:
        has_fresh = area_m2 >= FRESH_MIN_AREA_M2

    # 面积微调系数（premium 密度略高，community 略低）
    tier_factor = {"premium": 1.05, "standard": 1.0, "community": 0.92}.get(tier, 1.0)
    density = _sku_density(area_m2) * tier_factor
    estimated_sku = int(round(area_m2 * density))

    plan: BuildStorePlan = BuildStorePlan(
        area_m2=area_m2,
        tier=tier,
        has_fresh=has_fresh,
        has_tobacco=has_tobacco,
        estimated_sku=estimated_sku,
    )

    total_weight = sum(weights.values()) or 1.0
    category_plan: list[CategoryPlan] = []
    for cat, w in weights.items():
        w_pct = round(w / total_weight * 100, 1)
        cat_area = round(area_m2 * w_pct / 100, 1)
        shelf_units = max(1, int(round(cat_area / SHELF_UNIT_AREA_M2)))
        # 该品类 SKU 数按权重占比估算
        cat_sku = int(round(estimated_sku * w_pct / 100))
        category_plan.append(CategoryPlan(cat, w_pct, cat_area, shelf_units, cat_sku))
    plan.category_plan = category_plan

    # 货架方案（汇总）
    total_shelf_units = sum(c.shelf_units for c in category_plan)
    gondolas = max(1, int(round(total_shelf_units / 2)))  # 每组 gondola 双面计 2 单元
    cold_units = 0
    if has_fresh:
        cold_units = 2 if area_m2 >= 150 else 1
    plan.shelf_layout = {
        "gondolas": gondolas,
        "wall_shelves": max(1, int(round(area_m2 / 30))),
        "cold_chain_units": cold_units,
        "checkout_position": "入口右侧（动线起点）",
        "fresh_island": "门店中部（滞留动线）" if has_fresh else "无",
    }

    notes = [
        f"按卖场面积 {area_m2}㎡ 估算首批 SKU 约 {estimated_sku} 个",
        f"货架总单元 {total_shelf_units} 个，建议双面货架 {gondolas} 组",
    ]
    if has_fresh:
        notes.append(f"建议配置冷柜 {cold_units} 台，中部设鲜食岛提升停留")
    else:
        notes.append("门店面积偏小，未规划鲜食岛；如需鲜食建议面积≥80㎡")
    if not has_tobacco:
        notes.append("无烟证：烟酒品类权重已平摊至其他品类")
    plan.notes = notes
    return plan


def _self_test() -> None:
    """模块自检：覆盖典型门店面积档位。"""
    cases = [
        (50, "community", False, False),   # 微型无烟
        (100, "standard", None, True),      # 标准便利店
        (200, "premium", True, True),       # 中型含鲜食
    ]
    for area, tier, fresh, tob in cases:
        p = build_store_plan(area, tier=tier, has_fresh=fresh, has_tobacco=tob)
        assert p.estimated_sku > 0, f"SKU 应 > 0, got {p.estimated_sku}"
        assert abs(sum(c.weight_pct for c in p.category_plan) - 100.0) < 1.0, "权重和应≈100"
        assert p.shelf_layout["gondolas"] >= 1
        print(f"[OK] {area}㎡/{tier}/fresh={p.has_fresh}: SKU≈{p.estimated_sku}, "
              f"货架{p.shelf_layout['gondolas']}组, 冷柜{p.shelf_layout['cold_chain_units']}台")
    # 异常输入
    try:
        build_store_plan(0)
        raise AssertionError("面积=0 应抛异常")
    except ValueError:
        print("[OK] 面积=0 正确抛 ValueError")
    print("ALL SELF-TESTS PASSED")


if __name__ == "__main__":
    _self_test()
