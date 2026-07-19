"""
鹿小仓 Agent Loop 引擎 v1.0
自写的轻量级 Agentic Loop —— 约150行核心逻辑

五步循环：
1. 意图理解 → LLM
2. 任务拆解 → LLM 输出 JSON 工具调用计划
3. 工具执行 → Python 函数
4. 结果整合 → LLM 汇总
5. 输出交付 → 返回给用户

支持：工具调用、多轮循环、重试降级、超时控制
"""

import json
import os
import asyncio
import httpx
import time
import traceback
from pathlib import Path
from typing import AsyncGenerator, Optional


# ===== 工具注册表 =====
TOOLS = {}

def register_tool(name: str, description: str, parameters: dict):
    """装饰器：注册一个工具"""
    def decorator(func):
        TOOLS[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }
        return func
    return decorator


# ===== LLM 调用（带重试降级）=====
async def call_llm_raw(messages: list, config: dict, stream: bool = False, timeout: int = 60) -> dict:
    """调用LLM，返回完整响应（非流式）。带重试和降级。"""
    llm = config.get("llm", {})
    primary_key = llm.get("api_key", "")
    primary_url = llm.get("base_url", "")
    primary_model = llm.get("model", "")

    # 备用模型（DeepSeek）
    fallback_key = config.get("llm_fallback", {}).get("api_key", "")
    fallback_url = config.get("llm_fallback", {}).get("base_url", "https://api.deepseek.com/v1")
    fallback_model = config.get("llm_fallback", {}).get("model", "deepseek-chat")

    providers = [
        (primary_key, primary_url, primary_model),
        (fallback_key, fallback_url, fallback_model) if fallback_key else None,
    ]
    providers = [p for p in providers if p is not None]

    last_error = None
    for attempt in range(3):
        provider_idx = attempt % len(providers)
        key, base_url, model = providers[provider_idx]
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 2048,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            last_error = str(e)

        if attempt < 2:
            await asyncio.sleep(1 * (attempt + 1))  # 递增等待

    return f"⚠️ 大模型服务暂时不可用: {last_error}"


async def call_llm_stream(messages: list, config: dict, timeout: int = 120) -> AsyncGenerator[str, None]:
    """流式调用LLM，带重试。"""
    llm = config.get("llm", {})
    key = llm.get("api_key", "")
    base_url = llm.get("base_url", "")
    model = llm.get("model", "")

    if not key:
        yield "⚠️ 未配置API Key。"
        return

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        last_error = f"HTTP {resp.status_code}: {body.decode()[:200]}"
                        if attempt < 2:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        yield f"⚠️ API错误: {last_error}"
                        return
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
            return  # 成功完成，退出重试循环
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1 * (attempt + 1))
                continue
            yield f"⚠️ 请求失败: {str(e)}"
            return


# ===== Agent Loop 核心 =====
async def agent_loop(user_message: str, history: list, config: dict, max_iterations: int = 5, store_context: str = "") -> AsyncGenerator[str, None]:
    """
    Agent Loop 主循环。
    1. 把用户消息+历史发给LLM，要求它决定是否需要调用工具
    2. 如果需要工具，执行工具，把结果拼回上下文
    3. 再次调用LLM，直到它给出最终回答或达到最大迭代次数
    """
    tools_desc = "\n".join([
        f"- {t['name']}: {t['description']}\n  参数: {json.dumps(t['parameters'], ensure_ascii=False)}"
        for t in TOOLS.values()
    ]) or "（暂无注册工具）"

    system_prompt = f"""你是「鹿小仓」，一个便利店经营决策Agent。
同时你也是老板的「总会计师 / 总风控官 / 总军师」三合一财务管家。
{store_context}

你可以使用以下工具来完成任务：

{tools_desc}

## 工具调用规则
当你需要使用工具时，输出以下JSON格式（独占一行，不要包裹在markdown代码块中）：
{{"tool": "工具名", "args": {{"参数名": "参数值"}}}}

你可以连续调用多个工具（每次一个），每次调用后会收到工具返回的结果。
当你有了足够的信息可以回答用户时，直接用自然语言回答，不要输出JSON。

## 财务决策工具使用指南（动态盈利引擎）
你拥有4个核心财务工具，当用户提出相关问题时必须调用，严禁自行编造财务数据：

### 1. evaluate_order（评估单笔订单）
- 触发场景：老板问"这笔订单赚不赚钱？""这个5公里的单子能不能接？""这单利润多少？"
- 思考逻辑：获取订单商品、距离、平台费率 → 调用工具 → 重点关注 net_profit(净利) 和 break_even_distance_km(盈亏临界距离)
- 回复策略：如果亏损，必须用警告语气告知老板，并直接给出 suggestions（如加收运费或拒单）

### 2. get_store_dashboard（获取门店经营大盘）
- 触发场景：老板问"今天店里情况怎么样？""我们保本了吗？""还差多少单回本？""最近赚了多少？"
- 思考逻辑：调用工具获取最近3天累计数据 → 重点关注 break_even_orders_3d(保本单量) 和 remaining_orders_to_break_even(距保本还需单量)
- 回复策略：用"总会计师"的口吻汇报进度。如果进度落后，需结合 suggestions 给出冲刺建议

### 3. simulate_price_change（模拟调价影响）
- 触发场景：老板想调整某商品售价，问"把XX涨价/降价2块钱会有什么影响？""这个调价值不值？"
- 思考逻辑：提取商品名和调价幅度 → 调用工具 → 关注 profit_change_3d(3天利润变化) 和 break_even_orders_change(保本单量变化)
- 回复策略：明确告诉老板"建议执行"还是"不建议执行"，并用通俗语言解释毛利贡献和保本单量的变化

### 4. simulate_delivery_strategy（模拟配送策略）
- 触发场景：老板问"配送费太贵了怎么办？""不同距离的起送价该怎么设？""配送范围怎么划？"
- 思考逻辑：调用工具获取各距离梯度的测算结果 → 提取亏损距离的 min_order_amount(最低起送价)
- 回复策略：为老板输出一张清晰的"距离-起送价"阶梯建议表

## 财务回复风格
- 身份代入：在财务相关对话中，自称"您的总会计师"或"财务系统"
- 数据驱动：所有结论必须有工具返回的具体数据支撑，拒绝模糊表达（如"大概""可能"）
- 结论先行：先说结论（盈/亏/达标/未达标），再列数据，最后给行动建议
- 语气：专业、严谨、客观。在发现亏损风险时，语气要带有紧迫感和警示性

## 主动行为原则（D2-05）
- 如果上下文中有巡检告警，主动在对话中引用具体数据和数字
- 对话开场直接说正事，不要说"你好我是鹿小仓"之类的空话
- 如果用户之前接受过建议（如调价、选品），主动询问执行情况和效果
- 发现异常时主动追问："这个价格偏离较大，需要我生成调价方案吗？"
- 回答末尾如果有相关告警，简要提醒用户关注

## 回答原则
- 需要数据支撑时主动调用工具
- 工具调用失败时告知用户并给出替代建议
- 精确计算交给工具，你只做定性分析和方案生成
- 简洁有力，不废话
- 回答控制在300字以内，重点突出，不要长篇大论
- 用要点和短句，不用大段落

## 选品分析能力（D2-06）
当用户询问选品、商品分层、品类分析、滞销品、搭售等问题时，主动使用以下工具：
- classify_products: 商品分层(引流品/利润品/常规品/长尾品)
- category_gap_analysis: 两店SKU差异对比
- identify_slow_moving: 滞销品识别+淘汰建议
- basket_analysis: 购物篮关联+搭售陈列建议
调用时需要store_id参数，可从list_stores获取门店列表。"""

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_message}]

    for iteration in range(max_iterations):
        # 调用LLM（非流式，因为需要完整内容来判断是否要调工具）
        response = await call_llm_raw(messages, config, stream=False, timeout=60)

        # 检查是否有工具调用
        tool_call = _parse_tool_call(response)
        if tool_call is None:
            # 没有工具调用，说明是最终回答
            yield response
            return

        # 执行工具
        tool_name = tool_call["tool"]
        tool_args = tool_call.get("args", {})

        if tool_name not in TOOLS:
            yield f"⚠️ 未知工具: {tool_name}"
            return

        # 告诉用户正在执行什么
        yield f"\n🔧 正在执行: {tool_name}({json.dumps(tool_args, ensure_ascii=False)})...\n"

        try:
            tool_func = TOOLS[tool_name]["func"]
            if asyncio.iscoroutinefunction(tool_func):
                tool_result = await tool_func(**tool_args)
            else:
                tool_result = tool_func(**tool_args)
        except Exception as e:
            tool_result = f"工具执行失败: {str(e)}\n{traceback.format_exc()[-200:]}"

        # 把工具调用和结果加入上下文
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": f"工具 {tool_name} 返回结果:\n{tool_result}\n\n请根据以上结果继续。如果信息足够，请直接给出最终回答。"})

        # 输出工具结果给用户
        yield f"📋 {tool_name} 结果:\n{str(tool_result)[:500]}\n\n"

    # 达到最大迭代次数
    yield "\n⚠️ 已达到最大工具调用次数。以上是目前的分析结果。"


def _parse_tool_call(text: str) -> Optional[dict]:
    """从LLM输出中解析工具调用JSON"""
    text = text.strip()
    # 尝试直接解析
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "tool" in data:
            return data
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取JSON
    import re
    # 匹配 {"tool": ...} 格式
    pattern = r'\{"tool"\s*:\s*"[^"]+"(?:\s*,\s*"args"\s*:\s*\{[^}]*\})?\}'
    match = re.search(pattern, text)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and "tool" in data:
                return data
        except json.JSONDecodeError:
            pass

    return None


# ===== 内置工具 =====
@register_tool(
    name="get_time",
    description="获取当前时间",
    parameters={}
)
def get_time():
    from datetime import datetime
    return f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


@register_tool(
    name="list_stores",
    description="列出所有门店及其SKU数量和store_id（用于选品分析工具的参数）",
    parameters={}
)
def list_stores():
    # 尝试从数据库获取门店列表
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
    stores = []
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        for row in c.execute("SELECT id, name, address FROM stores"):
            stores.append({"store_id": row[0], "name": row[1], "address": row[2] or ""})
        conn.close()
    except Exception:
        pass
    # 补充SKU数量（已知数据）
    sku_map = {"鹿小仓广安店": 2941, "鹿小仓财富店": 1386}
    for s in stores:
        s["sku"] = sku_map.get(s["name"], "?")
    if not stores:
        # Fallback: 静态数据
        stores = [
            {"store_id": "", "name": "鹿小仓广安店", "sku": 2941, "address": "承德双桥区广安购物中心"},
            {"store_id": "", "name": "鹿小仓财富店", "sku": 1386, "address": "承德双滦区财富广场"},
        ]
    return json.dumps(stores, ensure_ascii=False)


@register_tool(
    name="list_competitors",
    description="列出所有竞品门店及其SKU数量",
    parameters={}
)
def list_competitors():
    return json.dumps([
        {"name": "小柴购", "sku": 7659, "file": "knowledge/competitors/小柴购_全量数据表_v5.xlsx"},
        {"name": "厉臣超市", "sku": 1996, "file": "knowledge/competitors/厉臣超市_标准化总数据表.xlsx"},
    ], ensure_ascii=False)


@register_tool(
    name="run_script",
    description="运行业务脚本（如比价、竞争分析等）",
    parameters={
        "script_name": "脚本名称，可选: compare_price, competitive_analysis, gen_price_plan, data_merge, ocr_extract",
        "args": "脚本参数（可选）"
    }
)
async def run_script(script_name: str, args: str = ""):
    import subprocess
    import sys
    script_map = {
        "compare_price": "compare_price.py",
        "competitive_analysis": "competitive_analysis.py",
        "gen_price_plan": "gen_price_plan.py",
        "data_merge": "data_merge.py",
        "ocr_extract": "ocr_extract.py",
    }
    filename = script_map.get(script_name, f"{script_name}.py")
    script_path = f"scripts/{filename}"
    if not Path(script_path).exists():
        return f"脚本不存在: {script_path}"
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args.split())
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8")
        output = result.stdout[-2000:] if result.stdout else ""
        if result.returncode != 0:
            output += f"\n⚠️ 退出码: {result.returncode}\n{result.stderr[-500:]}"
        return output or "脚本执行完成（无输出）"
    except subprocess.TimeoutExpired:
        return "⚠️ 脚本执行超时（120秒）"
    except Exception as e:
        return f"⚠️ 执行失败: {str(e)}"


# ===== D2-06 选品规划+商品分层工具 =====

@register_tool(
    name="classify_products",
    description="商品自动分层分析：按品类×价格带×毛利率将商品分为引流品(traffic)/利润品(profit)/常规品(regular)/长尾品(long_tail)。返回每类数量、占比和示例商品。",
    parameters={
        "store_id": "门店ID（从list_stores获取）"
    }
)
def classify_products_tool(store_id: str):
    from product_analysis import classify_products
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
    result = classify_products(db_path, store_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@register_tool(
    name="category_gap_analysis",
    description="品类差异分析：对比本店与另一门店的SKU差异，找出对方有本店没有的商品、本店独有的商品、各品类SKU数量对比。",
    parameters={
        "store_id": "门店ID"
    }
)
def category_gap_tool(store_id: str):
    from product_analysis import category_gap_analysis
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
    result = category_gap_analysis(db_path, store_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@register_tool(
    name="identify_slow_moving",
    description="滞销品识别：基于价格偏离品类均价、超高加价率、长尾品类等规则识别潜在滞销品，给出淘汰/促销建议。",
    parameters={
        "store_id": "门店ID"
    }
)
def slow_moving_tool(store_id: str):
    from product_analysis import identify_slow_moving
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
    result = identify_slow_moving(db_path, store_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@register_tool(
    name="basket_analysis",
    description="购物篮关联分析：基于品类互补性给出搭售陈列建议（如饮料配零食）。后续接入POS数据可升级为精确关联规则。",
    parameters={
        "store_id": "门店ID"
    }
)
def basket_analysis_tool(store_id: str):
    from product_analysis import basket_analysis
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
    result = basket_analysis(db_path, store_id)
    return json.dumps(result, ensure_ascii=False, default=str)


@register_tool(
    name="build_store_plan",
    description="建店规划引擎：输入门店卖场面积(㎡)，生成品类权重规划、首批SKU推算数量、货架组数/冷柜数量/动线方案。用于新店筹建或门店改造评估。",
    parameters={
        "area": "卖场面积(平方米)，必填，例如 100",
        "tier": "门店层级: standard/premium/community，默认 standard",
        "has_fresh": "是否规划鲜食岛(True/False)，默认按面积自动判定(≥80㎡为True)",
        "has_tobacco": "是否含烟证(默认 True)",
    }
)
def build_store_plan_tool(area: float, tier: str = "standard", has_fresh: bool = None, has_tobacco: bool = True):
    from build_store import build_store_plan
    plan = build_store_plan(area_m2=area, tier=tier, has_fresh=has_fresh, has_tobacco=has_tobacco)
    return json.dumps(plan.to_dict(), ensure_ascii=False, default=str)
