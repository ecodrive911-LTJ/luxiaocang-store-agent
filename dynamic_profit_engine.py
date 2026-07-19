"""
动态盈利决策引擎 — 核心算法与常量
供 profit_tools.py 和外部系统共享的底层计算逻辑

数据来源：profit_order_feed 表（外部通过 /api/profit_engine/ingest 被动喂入）
累计周期：3天滚动窗口
"""
import math

# ========== 配送费模型 ==========
BASE_DISTANCE = 3.0      # 基础配送距离（公里）
BASE_FEE = 5.0           # 基础配送费（元）
EXTRA_PER_KM = 1.5       # 超出部分每公里加价（元）
FULFILLMENT_COST = 1.5   # 固定拣货打包费（元/单）
DASHBOARD_PERIOD_DAYS = 3  # 大盘统计周期（天）

# ========== 保本参数 ==========
DAILY_FIXED_COST = 1333.0  # 日均固定成本（月4万 ÷ 30）

# ========== 红线阈值 ==========
RED_LINE_PROFIT = 0       # 单笔净利低于此值视为红线
RED_LINE_RATE = 0.15      # 红线订单占比超过15%触发预警


def calc_delivery_cost(distance_km: float) -> float:
    """计算配送费：3km内5元，超出每公里+1.5元"""
    extra = max(0, distance_km - BASE_DISTANCE)
    return BASE_FEE + extra * EXTRA_PER_KM


def calc_break_even_distance(gross_profit: float, commission: float) -> float:
    """计算盈亏临界距离：在多远距离下，净利刚好为0"""
    max_affordable = gross_profit - commission - FULFILLMENT_COST
    if max_affordable <= BASE_FEE:
        return 0.0
    return BASE_DISTANCE + (max_affordable - BASE_FEE) / EXTRA_PER_KM


def calc_min_order_amount(delivery_cost: float, margin_after_commission: float) -> float:
    """反推保本起送价：起送价 × (毛利率 - 抽佣率) = 运费 + 履约费"""
    if margin_after_commission <= 0:
        return 9999
    return (delivery_cost + FULFILLMENT_COST) / margin_after_commission


def calc_break_even_orders(avg_net_profit: float, period_days: int = 3) -> int:
    """计算保本单量：固定成本 ÷ 平均每单净利"""
    if avg_net_profit <= 0:
        return 9999
    return math.ceil(DAILY_FIXED_COST * period_days / avg_net_profit)
