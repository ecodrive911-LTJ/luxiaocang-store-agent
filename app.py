import configparser
import os
import json
import sqlite3
import time
import uuid
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent_loop import agent_loop, call_llm_stream, register_tool, TOOLS

# ===== Paths =====
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
SCRIPTS_DIR = BASE_DIR / "scripts"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = BASE_DIR / "database.db"
CONFIG_PATH = BASE_DIR / "config.ini"

for d in [STATIC_DIR, DATA_DIR, SCRIPTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ===== Config =====
DEFAULT_CONFIG = {
    "llm": {
        "provider": "volcengine",
        "api_key": "VxCgNvLTE.ChBFdngzcWRIb1dIOHlaS3BmEOqcvfcHGAEqEO7d3r37wE2Mnd9Wjmsfznw.pMj04EcouHDzGfsjVZEbcgzvSsBAYGTg5a1Mw3VWQ_0K1CqIQ9GJiEKoZ1RIhEsUyjHV037nDKVmwZJ7sKyoeQeZ",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "Evx3qdHoWH8yZKpf",
    },
    "server": {
        "host": "127.0.0.1",
        "port": "8420",
    },
    "agent": {
        "name": "鹿小仓",
        "version": "0.3",
        "brand": "复投科技出品",
    }
}

def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    cfg = {}
    for section in parser.sections():
        cfg[section] = dict(parser[section])
    # merge with defaults
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    return cfg

def save_config(cfg):
    parser = configparser.ConfigParser()
    for section, items in cfg.items():
        parser[section] = items
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        parser.write(f)

config = load_config()

# ===== Database =====
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        role TEXT,
        content TEXT,
        timestamp REAL,
        session_id TEXT DEFAULT 'default'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        type TEXT,
        status TEXT DEFAULT 'pending',
        params TEXT,
        result TEXT,
        created_at REAL,
        updated_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS data_assets (
        id TEXT PRIMARY KEY,
        name TEXT,
        type TEXT,
        path TEXT,
        rows INTEGER,
        description TEXT,
        created_at REAL
    )""")
    conn.commit()
    conn.close()

init_db()

def db_query(sql, params=(), fetch="all"):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(sql, params)
    if fetch == "all":
        rows = c.fetchall()
        result = [dict(r) for r in rows]
    elif fetch == "one":
        result = dict(c.fetchone()) if c.fetchone() else None
    else:
        result = c.rowcount
    conn.commit()
    conn.close()
    return result

def db_exec(sql, params=()):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    conn.close()

# ===== LLM (保留旧接口兼容，实际调用走agent_loop) =====
async def call_llm(messages, api_key=None, model=None, stream=True):
    """旧版LLM调用接口（保留兼容）"""
    cfg = load_config()
    llm_cfg = cfg.get("llm", {})
    key = api_key or llm_cfg.get("api_key", "")
    base_url = llm_cfg.get("base_url", "https://ark.cn-beijing.volces.com/api/v3")
    mdl = model or llm_cfg.get("model", "")

    if not key:
        yield "⚠️ 未配置API Key。请在设置页面配置大模型API Key。"
        return

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": mdl,
        "messages": messages,
        "stream": stream,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    url = f"{base_url}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            if stream:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield f"❌ API错误 ({resp.status_code}): {body.decode()}"
                        return
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
            else:
                resp = await client.post(url, headers=headers, json=payload)
                data = resp.json()
                yield data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        yield f"❌ 请求失败: {str(e)}"


# ===== System Prompt =====
SYSTEM_PROMPT = """你是「鹿小仓」，一个便利店经营决策Agent。

## 身份
你不是搜索引擎，不是报告生成器。你是一个能采集数据→分析问题→给出方案→追踪执行的闭环系统。
你背后有一支虚拟专家团队：消费品行业分析师、投行专家、供应链企业领导人、便利店连锁经营高管。

## 知识资产（独立目录，不依赖任何平台）
你的全部知识资产存储在本地 knowledge/ 目录下，包含：

### 门店数据
- 鹿小仓广安店：2,941 SKU（knowledge/stores/鹿小仓广安店_库存合并总表.xlsx）
- 鹿小仓财富店：1,386 SKU（knowledge/stores/鹿小仓财富店_库存合并总表.xlsx）
- 广安店最终调价方案（76条执行调价）
- 财富店最终调价方案（85条执行调价）

### 竞品数据
- 小柴购：7,659 SKU（knowledge/competitors/小柴购_全量数据表_v5.xlsx）
- 厉臣超市：1,996 SKU（精品店定位）
- 竞争对比分析报告（广安店vs小柴购、财富店vs厉臣）

### 行业数据
- 商圈POI扫描数据
- 高德API商圈扫描方法论
- 能力边界审计报告

### 架构蓝图
- 架构蓝图v0.1：9大模块覆盖建店前/中/后全周期
- 架构蓝图v0.2：三层架构（采集→分析→决策）+ 两端形态（商家端+管理端）
- 信息采集能力体系v0.1：8种采集能力+多平台交叉验证

### 业务脚本（scripts/目录）
- compare_price.py：商品比价（模糊匹配+规格校验）
- gen_price_plan.py：调价方案生成
- competitive_analysis.py：竞争对比分析
- data_merge.py：数据合并处理
- ocr_extract.py：OCR识别

### 案例库
- 比价调价全流程记录（含规格校验、人工复核、最终执行）
- 竞争分析案例
- Agent内核逻辑拆解
- 独立化方案

## 能力（9大模块）
1. 选址评估：商圈POI分析、竞品密度、选址评分
2. 建店规划：面积规划、货架布局、设备清单
3. 选品规划：品类结构推荐、SKU规划、竞品缺口分析
4. 定价策略：毛利分析、价格带分布、引流品定价
5. 供应链：库存周转、缺货预警、批发价对比
6. 品牌管理：品牌定位、VI规范、社群运营
7. 运营诊断：销售趋势、品类贡献、滞销识别
8. 促销营销：促销方案、满减搭赠、效果追踪
9. 财务管理：投资回报、损益表、盈亏平衡

## 交互原则
- 对话驱动：主动提问、引导用户、展示进度
- 务实诚实：做不到的说做不到，做到的说能做到
- 数据说话：每个结论尽量有数据支撑
- 简洁有力：不废话，直接给方案

## 当前版本
v0.3 — Agent Loop引擎已集成，支持工具调用
"""

def get_conversation_history(session_id="default", limit=20):
    rows = db_query(
        "SELECT role, content FROM conversations WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
        (session_id, limit),
        fetch="all"
    )
    rows.reverse()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def save_message(role, content, session_id="default"):
    db_exec(
        "INSERT INTO conversations (id, role, content, timestamp, session_id) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), role, content, time.time(), session_id)
    )

# ===== FastAPI =====
app = FastAPI(title="鹿小仓")

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ConfigRequest(BaseModel):
    provider: str = None
    api_key: str = None
    base_url: str = None
    model: str = None

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.get("/api/status")
async def status():
    cfg = load_config()
    llm = cfg.get("llm", {})
    has_key = bool(llm.get("api_key"))
    return {
        "agent_name": cfg.get("agent", {}).get("name", "鹿小仓"),
        "version": cfg.get("agent", {}).get("version", "0.3"),
        "brand": cfg.get("agent", {}).get("brand", "复投科技出品"),
        "llm_configured": has_key,
        "llm_provider": llm.get("provider", ""),
        "llm_model": llm.get("model", ""),
        "timestamp": time.time(),
        "tools": list(TOOLS.keys()),
        "agent_loop_enabled": True,
    }

@app.get("/api/data/assets")
async def data_assets():
    rows = db_query("SELECT * FROM data_assets ORDER BY created_at DESC", fetch="all")
    builtin = [
        {"name": "鹿小仓广安店", "rows": 2941, "type": "门店"},
        {"name": "鹿小仓财富店", "rows": 1386, "type": "门店"},
        {"name": "小柴购（竞品）", "rows": 7659, "type": "竞品"},
        {"name": "厉臣超市（竞品）", "rows": 1996, "type": "竞品"},
        {"name": "商圈POI扫描", "rows": 1396, "type": "商圈"},
    ]
    return {"builtin": builtin, "custom": rows, "total_sku": 13982}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    save_message("user", req.message, req.session_id)
    history = get_conversation_history(req.session_id, limit=10)

    async def stream_response():
        full_reply = ""
        try:
            # 使用 Agent Loop 引擎
            async for chunk in agent_loop(req.message, history, config):
                full_reply += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            save_message("assistant", full_reply, req.session_id)
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")

@app.get("/api/tools")
async def list_tools():
    """列出所有可用的Agent工具"""
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in TOOLS.values()
        ]
    }

@app.get("/api/config")
async def get_config():
    cfg = load_config()
    llm = cfg.get("llm", {})
    return {
        "provider": llm.get("provider", ""),
        "api_key": llm.get("api_key", "")[:8] + "..." if llm.get("api_key") else "",
        "api_key_set": bool(llm.get("api_key")),
        "base_url": llm.get("base_url", ""),
        "model": llm.get("model", ""),
    }

@app.put("/api/config")
async def update_config(req: ConfigRequest):
    cfg = load_config()
    if "llm" not in cfg:
        cfg["llm"] = {}
    if req.provider is not None:
        cfg["llm"]["provider"] = req.provider
        presets = {
            "volcengine": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": ""},
            "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-plus"},
            "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
            "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
            "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
        }
        if req.provider in presets:
            for k, v in presets[req.provider].items():
                if k not in cfg["llm"] or not cfg["llm"][k]:
                    cfg["llm"][k] = v
    if req.api_key is not None and req.api_key != "":
        cfg["llm"]["api_key"] = req.api_key
    if req.base_url is not None:
        cfg["llm"]["base_url"] = req.base_url
    if req.model is not None:
        cfg["llm"]["model"] = req.model
    save_config(cfg)
    return {"ok": True, "message": "配置已保存"}

@app.get("/api/conversations")
async def conversations(session_id: str = "default", limit: int = 50):
    rows = db_query(
        "SELECT * FROM conversations WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
        (session_id, limit),
        fetch="all"
    )
    rows.reverse()
    return {"messages": rows}

# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading
    host = config.get("server", {}).get("host", "127.0.0.1")
    port = int(config.get("server", {}).get("port", "8420"))
    url = f"http://{host}:{port}"

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    print(f"鹿小仓启动中... {url}")
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")
