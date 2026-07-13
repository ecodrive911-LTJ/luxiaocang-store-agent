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
import asyncio
import httpx
import time
import traceback
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
{store_context}

你可以使用以下工具来完成任务：

{tools_desc}

## 工具调用规则
当你需要使用工具时，输出以下JSON格式（独占一行，不要包裹在markdown代码块中）：
{{"tool": "工具名", "args": {{"参数名": "参数值"}}}}

你可以连续调用多个工具（每次一个），每次调用后会收到工具返回的结果。
当你有了足够的信息可以回答用户时，直接用自然语言回答，不要输出JSON。

## 原则
- 需要数据支撑时主动调用工具
- 工具调用失败时告知用户并给出替代建议
- 精确计算交给工具，你只做定性分析和方案生成
- 简洁有力，不废话
- 回答控制在300字以内，重点突出，不要长篇大论
- 用要点和短句，不用大段落
"""

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
    description="列出所有门店及其SKU数量",
    parameters={}
)
def list_stores():
    return json.dumps([
        {"name": "鹿小仓广安店", "sku": 2941, "file": "knowledge/stores/鹿小仓广安店_库存合并总表.xlsx"},
        {"name": "鹿小仓财富店", "sku": 1386, "file": "knowledge/stores/鹿小仓财富店_库存合并总表.xlsx"},
    ], ensure_ascii=False)


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
