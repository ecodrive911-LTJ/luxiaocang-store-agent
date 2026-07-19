"""
动态盈利决策引擎核心逻辑
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json


@dataclass
class OrderItem:
    name: str
    quantity: int
    price: float
    cost: float


@dataclass
class Order:
    order_id: str
    items: List[OrderItem]
    distance_km: float
    platform_commission_rate: float
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    @property
    def total_revenue(self) -> float:
        return sum(item.price * item.quantity for item in self.items)
    
    @property
    def total_cost(self) -> float:
        return sum(item.cost * item.quantity for item in self.items)
    
    @property
    def platform_commission(self) -> float:
        return self.total_revenue * self.platform_commission_rate


class DynamicProfitEngine:
    """
    动态盈利决策引擎
    
    核心功能：
    1. 评估单笔订单利润
    2. 查询门店3天累计经营大盘
    3. 模拟调价影响
    4. 模拟配送策略
    """
    
    # 红线阈值
    RED_LINE_PROFIT = 0  # 单笔订单利润低于此值视为红线
    RED_LINE_RATE = 0.15  # 红线订单占比超过15%触发预警
    
    # 保本参数（可通过外部数据覆盖）
    DAILY_FIXED_COST = 1000.0  # 每日固定成本（元）
    
    def __init__(self, order_history: List[Order] = None):
        self.order_history = order_history or []
    
    def evaluate_order(self, order_id: str, items: List[Dict], 
                      distance_km: float, platform_commission_rate: float) -> Dict[str, Any]:
        """
        评估单笔订单的真实利润
        
        Returns:
            {
                "order_id": str,
                "revenue": float,
                "cost": float,
                "platform_commission": float,
                "delivery_fee": float,
                "net_profit": float,
                "profit_margin": float,
                "is_loss": bool,
                "break_even_distance_km": float,
                "suggestions": List[str]
            }
        """
        # 解析商品列表
        order_items = [
            OrderItem(
                name=item.get("name", "未知商品"),
                quantity=item.get("quantity", 1),
                price=item.get("price", 0),
                cost=item.get("cost", 0)
            )
            for item in items
        ]
        
        order = Order(
            order_id=order_id,
            items=order_items,
            distance_km=distance_km,
            platform_commission_rate=platform_commission_rate
        )
        
        revenue = order.total_revenue
        cost = order.total_cost
        platform_commission = order.platform_commission
        
        # 配送费计算（简化模型）
        # 基础配送费5元（3公里内），超出部分每公里1.5元
        if distance_km <= 3:
            delivery_fee = 5.0
        else:
            delivery_fee = 5.0 + (distance_km - 3) * 1.5
        
        # 真实利润
        net_profit = revenue - cost - platform_commission - delivery_fee
        
        # 利润率
        profit_margin = net_profit / revenue if revenue > 0 else 0
        
        # 是否亏损
        is_loss = net_profit < self.RED_LINE_PROFIT
        
        # 盈亏临界距离
        # 反推：在多远的距离下，利润刚好为0
        # revenue - cost - platform_commission - delivery_fee = 0
        # delivery_fee = revenue - cost - platform_commission
        # 如果距离<=3km，delivery_fee=5，临界利润=revenue-cost-platform_commission-5
        # 如果距离>3km，delivery_fee=5+(d-3)*1.5，临界距离=3+(临界利润-5)/1.5
        
        contribution_margin = revenue - cost - platform_commission
        if contribution_margin <= 5:
            break_even_distance_km = 0  # 连3公里内的基础配送费都覆盖不了
        else:
            break_even_distance_km = 3 + (contribution_margin - 5) / 1.5
        
        # 建议
        suggestions = []
        if is_loss:
            suggestions.append(f"⚠️ 这笔订单亏损{abs(net_profit):.2f}元，必须立即处理！")
            
            if distance_km > break_even_distance_km:
                suggestions.append(f"配送距离过远（{distance_km}km > 临界{break_even_distance_km:.1f}km），建议：")
                suggestions.append(f"  1. 提高起送价到{revenue * 1.2:.0f}元")
                suggestions.append(f"  2. 加收远距离配送费{delivery_fee * 0.3:.0f}元")
                suggestions.append(f"  3. 缩小配送范围到{break_even_distance_km:.1f}km以内")
            
            if profit_margin < -0.1:
                suggestions.append(f"利润率严重异常（{profit_margin:.1%}），检查是否有成本录入错误或定价过低")
        
        return {
            "order_id": order_id,
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "platform_commission": round(platform_commission, 2),
            "delivery_fee": round(delivery_fee, 2),
            "net_profit": round(net_profit, 2),
            "profit_margin": round(profit_margin, 4),
            "is_loss": is_loss,
            "break_even_distance_km": round(break_even_distance_km, 2),
            "suggestions": suggestions
        }
    
    def get_store_dashboard(self, store_id: str = "default") -> Dict[str, Any]:
        """
        获取门店经营大盘数据（3天累计）
        
        Returns:
            {
                "store_id": str,
                "period_days": 3,
                "total_orders_3d": int,
                "total_revenue_3d": float,
                "total_cost_3d": float,
                "total_profit_3d": float,
                "profit_per_order": float,
                "profit_margin": float,
                "break_even_orders_3d": float,
                "remaining_orders_to_break_even": int,
                "red_line_count": int,
                "red_line_rate": float,
                "warning": str
            }
        """
        # 筛选3天内的订单
        cutoff_date = datetime.now() - timedelta(days=3)
        recent_orders = [o for o in self.order_history if o.created_at >= cutoff_date]
        
        if not recent_orders:
            return {
                "store_id": store_id,
                "period_days": 3,
                "total_orders_3d": 0,
                "warning": "最近3天没有订单数据，请检查数据输入是否正常"
            }
        
        total_orders = len(recent_orders)
        total_revenue = sum(o.total_revenue for o in recent_orders)
        total_cost = sum(o.total_cost for o in recent_orders)
        total_commission = sum(o.platform_commission for o in recent_orders)
        
        # 配送费总和（简化计算）
        total_delivery = sum(
            5.0 if o.distance_km <= 3 else 5.0 + (o.distance_km - 3) * 1.5
            for o in recent_orders
        )
        
        total_profit = total_revenue - total_cost - total_commission - total_delivery
        profit_per_order = total_profit / total_orders if total_orders > 0 else 0
        profit_margin = total_profit / total_revenue if total_revenue > 0 else 0
        
        # 保本订单数（3天）
        daily_fixed_cost = self.DAILY_FIXED_COST
        period_fixed_cost = daily_fixed_cost * 3
        break_even_orders_3d = period_fixed_cost / profit_per_order if profit_per_order > 0 else float('inf')
        remaining_orders = max(0, break_even_orders_3d - total_orders)
        
        # 红线订单统计
        red_line_count = sum(1 for o in recent_orders 
                           if (o.total_revenue - o.total_cost - o.platform_commission - 
                               (5.0 if o.distance_km <= 3 else 5.0 + (o.distance_km - 3) * 1.5)) < self.RED_LINE_PROFIT)
        red_line_rate = red_line_count / total_orders if total_orders > 0 else 0
        
        # 预警
        warning = None
        if red_line_rate > self.RED_LINE_RATE:
            warning = f"⚠️ 红线订单占比{red_line_rate:.1%}超过{self.RED_LINE_RATE:.0%}，必须立即调整策略！"
        elif remaining_orders > 0:
            warning = f"距离保本还差{remaining_orders:.0f}单，建议提升单量或优化利润结构"
        
        return {
            "store_id": store_id,
            "period_days": 3,
            "total_orders_3d": total_orders,
            "total_revenue_3d": round(total_revenue, 2),
            "total_cost_3d": round(total_cost, 2),
            "total_profit_3d": round(total_profit, 2),
            "profit_per_order": round(profit_per_order, 2),
            "profit_margin": round(profit_margin, 4),
            "break_even_orders_3d": round(break_even_orders_3d, 1),
            "remaining_orders_to_break_even": int(remaining_orders),
            "red_line_count": red_line_count,
            "red_line_rate": round(red_line_rate, 4),
            "warning": warning
        }
    
    def simulate_price_change(self, product_name: str, current_price: float, 
                             new_price: float, cost: float, daily_volume: int) -> Dict[str, Any]:
        """
        模拟商品调价对利润的影响
        
        Returns:
            {
                "product_name": str,
                "price_change": float,
                "price_change_rate": float,
                "profit_before": float,
                "profit_after": float,
                "profit_change_3d": float,
                "break_even_change": float,
                "recommendation": str
            }
        """
        price_change = new_price - current_price
        price_change_rate = price_change / current_price if current_price > 0 else 0
        
        # 调价前利润（3天）
        profit_per_unit_before = current_price - cost
        profit_before_3d = profit_per_unit_before * daily_volume * 3
        
        # 调价后利润（3天）
        profit_per_unit_after = new_price - cost
        profit_after_3d = profit_per_unit_after * daily_volume * 3
        
        # 利润变化
        profit_change_3d = profit_after_3d - profit_before_3d
        
        # 保本订单数变化
        break_even_before = (self.DAILY_FIXED_COST * 3) / profit_per_unit_before if profit_per_unit_before > 0 else float('inf')
        break_even_after = (self.DAILY_FIXED_COST * 3) / profit_per_unit_after if profit_per_unit_after > 0 else float('inf')
        break_even_change = break_even_after - break_even_before
        
        # 建议
        if profit_change_3d > 0:
            recommendation = f"✅ 建议执行：3天利润增加{profit_change_3d:.0f}元，保本难度降低"
        elif profit_change_3d < 0:
            if abs(profit_change_3d) > profit_before_3d * 0.2:
                recommendation = f"❌ 不建议执行：3天利润减少{abs(profit_change_3d):.0f}元（降幅{abs(profit_change_3d)/profit_before_3d:.1%}），影响过大"
            else:
                recommendation = f"⚠️ 谨慎执行：3天利润减少{abs(profit_change_3d):.0f}元，需要通过提升单量弥补"
        else:
            recommendation = "➖ 利润无变化"
        
        return {
            "product_name": product_name,
            "price_change": round(price_change, 2),
            "price_change_rate": round(price_change_rate, 4),
            "profit_before": round(profit_before_3d, 2),
            "profit_after": round(profit_after_3d, 2),
            "profit_change_3d": round(profit_change_3d, 2),
            "break_even_change": round(break_even_change, 1),
            "recommendation": recommendation
        }
    
    def simulate_delivery_strategy(self, distances: List[float] = None) -> Dict[str, Any]:
        """
        模拟不同配送距离的起送价和利润结构
        
        Returns:
            {
                "distance_breakdown": List[Dict],
                "suggestions": List[str]
            }
        """
        if distances is None:
            distances = [1, 2, 3, 4, 5, 6, 7, 8]
        
        breakdown = []
        for dist in distances:
            # 配送费
            if dist <= 3:
                delivery_fee = 5.0
            else:
                delivery_fee = 5.0 + (dist - 3) * 1.5
            
            # 假设平均客单价50元，毛利率25%，平台佣金18%
            avg_revenue = 50
            avg_cost = 37.5  # 毛利率25%
            avg_commission = 50 * 0.18
            
            # 真实利润
            profit = avg_revenue - avg_cost - avg_commission - delivery_fee
            
            # 盈亏临界起送价
            # revenue - cost - commission - delivery_fee = 0
            # revenue - 0.75*revenue - 0.18*revenue = delivery_fee
            # 0.07 * revenue = delivery_fee
            # revenue = delivery_fee / 0.07
            break_even_revenue = delivery_fee / 0.07
            
            breakdown.append({
                "distance_km": dist,
                "delivery_fee": round(delivery_fee, 2),
                "avg_profit": round(profit, 2),
                "break_even_revenue": round(break_even_revenue, 0)
            })
        
        # 建议
        suggestions = []
        for item in breakdown:
            if item["avg_profit"] < 0:
                suggestions.append(f"⚠️ {item['distance_km']}km距离：平均每单亏损{abs(item['avg_profit']):.1f}元，起送价必须提高到{item['break_even_revenue']:.0f}元以上")
        
        if not suggestions:
            suggestions.append("✅ 当前所有距离区间均有利润")
        
        return {
            "distance_breakdown": breakdown,
            "suggestions": suggestions
        }
