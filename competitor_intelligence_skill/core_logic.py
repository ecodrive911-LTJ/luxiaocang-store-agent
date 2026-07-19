"""
竞品情报分析引擎 — 核心算法实现
四个核心类：SKU特征提取、商品映射、策略反推、方案生成
"""
import re
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


# ========== 数据模型 ==========
@dataclass
class SKUFeature:
    brand: str = ""
    category: str = ""
    spec: str = ""       # 规格（如330ml、500ml）
    package: str = ""    # 包装（如罐装、瓶装）


@dataclass
class CompetitorSKU:
    sku_name: str
    sell_price: float = 0
    category: str = ""
    brand: str = ""
    spec: str = ""
    package: str = ""
    monthly_sales: int = 0
    features: SKUFeature = field(default_factory=SKUFeature)


@dataclass
class OurSKU:
    sku_name: str
    sell_price: float = 0
    purchase_cost: float = 0
    category: str = ""
    brand: str = ""
    spec: str = ""
    package: str = ""
    features: SKUFeature = field(default_factory=SKUFeature)


@dataclass
class SKUMapping:
    our_sku: str
    competitor_sku: str
    confidence: float
    status: str  # mapped / pending_review / unique


# ========== 类1：SKU四维特征提取 ==========
class SKUFeatureExtractor:
    """从商品名称中提取品牌/品类/规格/包装四维特征"""

    # 常见品牌词库（可扩展）
    BRANDS = [
        "可口可乐", "百事可乐", "农夫山泉", "怡宝", "娃哈哈",
        "康师傅", "统一", "旺旺", "达利园", "乐事",
        "伊利", "蒙牛", "光明", "三元", "君乐宝",
        "红牛", "脉动", "佳得乐", "宝矿力", "元气森林",
    ]

    # 品类关键词
    CATEGORIES = {
        "碳酸饮料": ["可乐", "雪碧", "芬达", "碳酸"],
        "矿泉水": ["矿泉水", "天然水", "纯净水"],
        "茶饮料": ["绿茶", "红茶", "乌龙茶", "茉莉花茶", "冰红茶"],
        "功能饮料": ["红牛", "脉动", "佳得乐", "宝矿力", "元气森林"],
        "乳制品": ["牛奶", "酸奶", "乳酸菌"],
        "膨化食品": ["薯片", "虾条", "膨化"],
        "方便食品": ["方便面", "泡面", "酸辣粉"],
        "饼干糕点": ["饼干", "蛋糕", "面包", "曲奇"],
    }

    # 规格模式
    SPEC_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|g|kg|毫升|升|克|千克|斤)", re.IGNORECASE)

    # 包装关键词
    PACKAGES = {
        "罐装": ["罐", "易拉罐", "听装"],
        "瓶装": ["瓶", "塑料瓶"],
        "盒装": ["盒", "利乐包", "纸盒"],
        "袋装": ["袋", "软包装"],
        "杯装": ["杯", "桶装"],
    }

    def extract(self, sku_name: str, brand_hint: str = "", category_hint: str = "",
                spec_hint: str = "", package_hint: str = "") -> SKUFeature:
        """从商品名称提取四维特征，优先使用hint"""
        feature = SKUFeature()

        # 品牌
        if brand_hint:
            feature.brand = brand_hint
        else:
            for b in self.BRANDS:
                if b in sku_name:
                    feature.brand = b
                    break

        # 品类
        if category_hint:
            feature.category = category_hint
        else:
            for cat, keywords in self.CATEGORIES.items():
                if any(kw in sku_name for kw in keywords):
                    feature.category = cat
                    break

        # 规格
        if spec_hint:
            feature.spec = spec_hint
        else:
            m = self.SPEC_PATTERN.search(sku_name)
            if m:
                feature.spec = f"{m.group(1)}{m.group(2)}"

        # 包装
        if package_hint:
            feature.package = package_hint
        else:
            for pkg, keywords in self.PACKAGES.items():
                if any(kw in sku_name for kw in keywords):
                    feature.package = pkg
                    break

        return feature


# ========== 类2：商品映射引擎 ==========
class SKUMappingEngine:
    """基于四维特征的SKU映射，输出置信度"""

    def __init__(self):
        self.extractor = SKUFeatureExtractor()
        self.mappings: List[SKUMapping] = []

    def map_skus(self, our_skus: List[OurSKU], competitor_skus: List[CompetitorSKU]) -> List[SKUMapping]:
        """对竞品SKU逐一匹配我方SKU"""
        results = []
        for comp_sku in competitor_skus:
            # 提取竞品特征
            comp_features = self.extractor.extract(
                comp_sku.sku_name, comp_sku.brand, comp_sku.category,
                comp_sku.spec, comp_sku.package
            )

            best_match = None
            best_score = 0

            for our_sku in our_skus:
                our_features = self.extractor.extract(
                    our_sku.sku_name, our_sku.brand, our_sku.category,
                    our_sku.spec, our_sku.package
                )
                score = self._calc_similarity(comp_features, our_features)
                if score > best_score:
                    best_score = score
                    best_match = our_sku

            if best_match and best_score >= 0.6:
                status = "mapped" if best_score >= 0.85 else "pending_review"
                results.append(SKUMapping(
                    our_sku=best_match.sku_name,
                    competitor_sku=comp_sku.sku_name,
                    confidence=round(best_score, 3),
                    status=status
                ))
            else:
                results.append(SKUMapping(
                    our_sku="",
                    competitor_sku=comp_sku.sku_name,
                    confidence=round(best_score, 3) if best_match else 0,
                    status="unique"
                ))

        self.mappings = results
        return results

    def _calc_similarity(self, f1: SKUFeature, f2: SKUFeature) -> float:
        """四维特征加权相似度"""
        weights = {"brand": 0.35, "category": 0.30, "spec": 0.20, "package": 0.15}
        scores = {}

        scores["brand"] = 1.0 if f1.brand and f1.brand == f2.brand else (0.5 if f1.brand and f2.brand else 0.0)
        scores["category"] = 1.0 if f1.category and f1.category == f2.category else 0.0
        scores["spec"] = 1.0 if f1.spec and f1.spec == f2.spec else (0.3 if not f1.spec or not f2.spec else 0.0)
        scores["package"] = 1.0 if f1.package and f1.package == f2.package else (0.3 if not f1.package or not f2.package else 0.0)

        total = sum(weights[k] * scores[k] for k in weights)
        return total


# ========== 类3：策略反推引擎 ==========
class StrategyReverseEngine:
    """通过价格和活动数据反推竞品的策略意图"""

    # 品类平均毛利率参考（便利店行业）
    CATEGORY_MARGIN_BENCHMARK = {
        "碳酸饮料": 0.30,
        "矿泉水": 0.35,
        "茶饮料": 0.30,
        "功能饮料": 0.25,
        "乳制品": 0.20,
        "膨化食品": 0.35,
        "方便食品": 0.30,
        "饼干糕点": 0.40,
        "default": 0.30,
    }

    def analyze_sku_role(self, sku: CompetitorSKU, est_cost: float = None) -> Dict:
        """判断单个SKU的角色"""
        category = sku.category or "default"
        benchmark_margin = self.CATEGORY_MARGIN_BENCHMARK.get(category, 0.30)

        if est_cost is None:
            est_cost = sku.sell_price * (1 - benchmark_margin)

        actual_margin = (sku.sell_price - est_cost) / sku.sell_price if sku.sell_price > 0 else 0

        if actual_margin < 0.05:
            role = "traffic_driver"  # 引流款：极低毛利，目的是拉客
            role_label = "引流款"
        elif actual_margin > benchmark_margin * 1.3:
            role = "profit_maker"  # 利润款：高于品类平均毛利
            role_label = "利润款"
        elif actual_margin < benchmark_margin * 0.5 and sku.sell_price < 10:
            role = "basket_builder"  # 凑单款：低价低毛利，引导凑单
            role_label = "凑单款"
        else:
            role = "standard"
            role_label = "标准款"

        return {
            "sku_name": sku.sku_name,
            "sell_price": sku.sell_price,
            "est_cost": round(est_cost, 2),
            "est_margin": round(actual_margin, 3),
            "benchmark_margin": benchmark_margin,
            "role": role,
            "role_label": role_label,
            "monthly_sales": sku.monthly_sales,
        }

    def reverse_promotion_intent(self, promotions: List[Dict]) -> List[Dict]:
        """反推促销活动的意图"""
        intents = []
        for promo in promotions:
            ptype = promo.get("type", "")
            detail = promo.get("detail", "")

            intent = "unknown"
            explanation = ""

            if ptype == "满减":
                # 解析满减档位
                numbers = re.findall(r"\d+", detail)
                if len(numbers) >= 2:
                    threshold = int(numbers[0])
                    discount = int(numbers[1])
                    rate = discount / threshold
                    if threshold < 30:
                        intent = "拉新获客"
                        explanation = f"低门槛满减（满{threshold}减{discount}），降低首单门槛吸引新客"
                    elif threshold >= 60:
                        intent = "提升客单价"
                        explanation = f"高门槛满减（满{threshold}减{discount}），引导多买凑单拉高客单价"
                    else:
                        intent = "兼顾拉新与提客单"
                        explanation = f"中门槛满减（满{threshold}减{discount}），平衡引流和客单价"
                else:
                    intent = "促销引流"
                    explanation = "满减活动，主要目的是吸引客流"

            elif ptype == "折扣":
                intent = "品类引流"
                explanation = f"品类折扣活动，通过特定品类低价吸引客流"

            elif ptype == "第N件优惠":
                intent = "提升客单价"
                explanation = "第N件优惠，鼓励多买，提升件单价和客单价"

            elif ptype == "秒杀":
                intent = "限时引流"
                explanation = "限时秒杀，制造紧迫感，短时间大量引流"

            elif ptype == "新客":
                intent = "拉新获客"
                explanation = "新客专享优惠，目标明确：吸引新客首单"

            elif ptype == "运费减免":
                intent = "降低决策门槛"
                explanation = "运费减免，降低下单心理门槛，提升转化率"

            elif ptype == "赠品":
                intent = "提升客单价"
                explanation = "赠品活动，设定门槛金额，引导凑单"

            intents.append({
                "type": ptype,
                "detail": detail,
                "intent": intent,
                "explanation": explanation,
            })

        return intents

    def overall_strategy_judgment(self, sku_roles: List[Dict], promo_intents: List[Dict]) -> Dict:
        """综合判断竞品整体策略"""
        traffic_count = sum(1 for r in sku_roles if r["role"] == "traffic_driver")
        profit_count = sum(1 for r in sku_roles if r["role"] == "profit_maker")
        basket_count = sum(1 for r in sku_roles if r["role"] == "basket_builder")

        intent_counts = defaultdict(int)
        for pi in promo_intents:
            intent_counts[pi["intent"]] += 1

        dominant_intent = max(intent_counts, key=intent_counts.get) if intent_counts else "无明显策略"

        if traffic_count > profit_count * 2:
            overall = "激进引流型"
            description = "大量SKU以接近成本价销售，用低价换流量，利润主要靠凑单和利润款回收"
        elif profit_count > traffic_count:
            overall = "利润导向型"
            description = "SKU定价偏保守，不以低价引流，主要靠品类毛利赚钱"
        else:
            overall = "均衡型"
            description = "引流款和利润款搭配，用部分低价品引流，其余SKU保持正常毛利"

        return {
            "overall_strategy": overall,
            "description": description,
            "sku_role_summary": {
                "traffic_drivers": traffic_count,
                "profit_makers": profit_count,
                "basket_builders": basket_count,
            },
            "promotion_intent_summary": dict(intent_counts),
            "dominant_intent": dominant_intent,
        }


# ========== 类4：应对方案生成器 ==========
class CounterStrategyGenerator:
    """基于竞品策略和我方底线，生成攻/守/避三套方案"""

    def generate(self, competitor_analysis: Dict, my_skus: List[Dict],
                 my_avg_margin: float = 0.30) -> Dict:
        """
        my_skus: [{"sku_name": str, "purchase_cost": float, "current_price": float, "mapped_competitor_price": float}]
        """
        attack = self._gen_attack(competitor_analysis, my_skus, my_avg_margin)
        defend = self._gen_defend(competitor_analysis, my_skus, my_avg_margin)
        avoid = self._gen_avoid(competitor_analysis, my_skus, my_avg_margin)

        return {
            "attack_plan": attack,
            "defend_plan": defend,
            "avoid_plan": avoid,
        }

    def _gen_attack(self, analysis: Dict, my_skus: List[Dict], avg_margin: float) -> Dict:
        """进攻方案：针对竞品引流款，精准反击"""
        actions = []
        total_risk = "中"

        # 找竞品的引流款，我们跟价或更低价
        for sku in my_skus:
            comp_price = sku.get("mapped_competitor_price")
            if comp_price and comp_price < sku["current_price"]:
                cost = sku["purchase_cost"]
                # 跟到和竞品同价
                follow_margin = (comp_price - cost) / comp_price if comp_price > cost else 0
                if follow_margin >= 0.05:  # 跟价后还有5%以上毛利
                    actions.append({
                        "sku": sku["sku_name"],
                        "action": f"跟价至{comp_price}元（与竞品持平）",
                        "current_price": sku["current_price"],
                        "new_price": comp_price,
                        "margin_after": round(follow_margin, 3),
                        "expected_effect": "阻止客户流失，维持市场份额",
                    })
                else:
                    actions.append({
                        "sku": sku["sku_name"],
                        "action": "暂不跟价，该品我方成本劣势过大",
                        "current_price": sku["current_price"],
                        "new_price": sku["current_price"],
                        "margin_after": round((sku["current_price"] - cost) / sku["current_price"], 3),
                        "expected_effect": "放弃该品价格战，避免亏损",
                        "risk": "可能流失该品客户",
                    })
                    total_risk = "中高"

        if not actions:
            actions.append({
                "sku": "全品类",
                "action": "当前价格已具竞争力，无需进攻",
                "expected_effect": "维持现状",
            })

        return {
            "strategy": "精准跟价，守住核心引流品",
            "actions": actions,
            "overall_risk": total_risk,
            "expected_effect": "短期内可阻止客户向竞品流失，但会压缩利润空间，需通过提升客单价弥补",
        }

    def _gen_defend(self, analysis: Dict, my_skus: List[Dict], avg_margin: float) -> Dict:
        """防守方案：不直接跟价，通过服务和组合保住客户"""
        actions = []

        # 推荐组合套餐
        high_margin = [s for s in my_skus if (s["current_price"] - s["purchase_cost"]) / s["current_price"] > avg_margin]
        low_margin = [s for s in my_skus if (s["current_price"] - s["purchase_cost"]) / s["current_price"] <= avg_margin]

        if low_margin and high_margin:
            actions.append({
                "sku": f"{low_margin[0]['sku_name']}+{high_margin[0]['sku_name']}",
                "action": f"推出组合套餐，{low_margin[0]['sku_name']}搭{high_margin[0]['sku_name']}，套餐价比竞品单品略高但整体更划算",
                "expected_effect": "用套餐锁定客户，避免单品价格对比",
            })

        actions.extend([
            {
                "sku": "全店",
                "action": "提升配送速度和服务体验，用服务差异化对抗价格战",
                "expected_effect": "客户对配送体验的敏感度往往高于1-2元价差",
            },
            {
                "sku": "全店",
                "action": "推出会员专享价或积分活动，增加客户粘性",
                "expected_effect": "会员客户复购率比非会员高2-3倍",
            },
        ])

        return {
            "strategy": "差异化防守，不打价格战",
            "actions": actions,
            "overall_risk": "低",
            "expected_effect": "短期内可能流失部分价格敏感客户，但通过服务和粘性活动可保住核心客户群",
        }

    def _gen_avoid(self, analysis: Dict, my_skus: List[Dict], avg_margin: float) -> Dict:
        """回避方案：避开竞品强势品类，寻找市场空白"""
        actions = []

        actions.append({
            "sku": "竞品弱势品类",
            "action": "识别竞品覆盖弱的品类（如鲜食、烘焙、进口零食），加大这些品类的SKU深度和促销力度",
            "expected_effect": "在竞品薄弱的领域建立优势，吸引追求差异化的客户",
        })

        actions.append({
            "sku": "时段差异化",
            "action": "延长营业时间（如营业到凌晨2点），覆盖竞品不服务的时段",
            "expected_effect": "夜间订单竞争少，毛利通常高于日间",
        })

        actions.append({
            "sku": "自有品牌",
            "action": "引入或开发自有品牌商品，成本可控，避免直接价格对比",
            "expected_effect": "自有品牌毛利可达40-50%，且不被客户直接比价",
        })

        return {
            "strategy": "错位竞争，寻找蓝海",
            "actions": actions,
            "overall_risk": "低",
            "expected_effect": "需要一定时间培育新品类和时段优势，但长期效果最好，不陷入价格战泥潭",
        }
