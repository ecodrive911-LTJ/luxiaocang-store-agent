"""
鹿小仓 便利店经营决策Agent v0.4
多租户架构 — 支持多用户多门店同时在线
"""

import configparser
import os
import json
import sqlite3
import time
import uuid
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent_loop import agent_loop, call_llm_stream, register_tool, TOOLS
from auth import (
    hash_password, verify_password, create_session, verify_session,
    invalidate_session, get_user_stores, get_store_by_id, extract_token
)

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
        "version": "0.4",
        "brand": "复投科技出品",
    },
    "auth": {
        "secret_key": "luxiaocang-secret-2024",
        "session_ttl_hours": "168",
        "allow_registration": "true",
    },
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

    # ===== 新表 =====
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        phone TEXT,
        role TEXT DEFAULT 'owner',
        created_at REAL,
        updated_at REAL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stores (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        address TEXT,
        city TEXT,
        district TEXT,
        owner_id TEXT NOT NULL,
        created_at REAL,
        FOREIGN KEY (owner_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_stores (
        user_id TEXT NOT NULL,
        store_id TEXT NOT NULL,
        role TEXT DEFAULT 'owner',
        PRIMARY KEY (user_id, store_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (store_id) REFERENCES stores(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at REAL,
        expires_at REAL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    # ===== 现有表改造：加 user_id, store_id =====
    # SQLite 不支持 IF NOT EXISTS 加列，需要检查
    def column_exists(table, col):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols

    for table in ["conversations", "tasks", "data_assets"]:
        if not column_exists(table, "user_id"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")
        if not column_exists(table, "store_id"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN store_id TEXT")

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


# ===== 鉴权依赖 =====
async def require_auth(request: Request):
    """FastAPI 依赖：验证用户登录"""
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = verify_session(DB_PATH, token)
    if not user:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    return user

async def require_auth_optional(request: Request):
    """可选鉴权：有 token 就验证，没有就返回 None"""
    token = extract_token(request)
    if not token:
        return None
    return verify_session(DB_PATH, token)


# ===== System Prompt =====
SYSTEM_PROMPT = """你是「鹿小仓」，一个便利店经营决策Agent。

## 身份
你不是搜索引擎，不是报告生成器。你是一个能采集数据→分析问题→给出方案→追踪执行的闭环系统。
你背后有一支虚拟专家团队：消费品行业分析师、投行专家、供应链企业领导人、便利店连锁经营高管。

## 知识资产
你的全部知识资产存储在本地 knowledge/ 目录下，包含门店数据、竞品数据、行业数据、架构蓝图等。

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
"""


def get_conversation_history(session_id="default", limit=20, user_id=None, store_id=None):
    """获取对话历史（按用户和门店隔离）"""
    sql = "SELECT role, content FROM conversations WHERE 1=1"
    params = []
    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)
    if store_id:
        sql += " AND (store_id = ? OR store_id IS NULL)"
        params.append(store_id)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = db_query(sql, tuple(params), fetch="all")
    rows.reverse()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def save_message(role, content, session_id="default", user_id=None, store_id=None):
    db_exec(
        "INSERT INTO conversations (id, role, content, timestamp, session_id, user_id, store_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), role, content, time.time(), session_id, user_id, store_id)
    )


# ===== FastAPI =====
app = FastAPI(title="鹿小仓")

# ===== 请求模型 =====
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    store_id: str = None

class ConfigRequest(BaseModel):
    provider: str = None
    api_key: str = None
    base_url: str = None
    model: str = None

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = None
    phone: str = None

class LoginRequest(BaseModel):
    username: str
    password: str

class StoreRequest(BaseModel):
    name: str
    address: str = None
    city: str = None
    district: str = None


# ===== 认证接口 =====
@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    """用户注册"""
    allow_reg = config.get("auth", {}).get("allow_registration", "true") == "true"
    if not allow_reg:
        raise HTTPException(status_code=403, detail="注册已关闭")

    if len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少2个字符")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    # 检查用户名是否已存在
    existing = db_query("SELECT id FROM users WHERE username = ?", (req.username,), fetch="one")
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user_id = str(uuid.uuid4())
    now = time.time()
    db_exec(
        "INSERT INTO users (id, username, password_hash, display_name, phone, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, req.username, hash_password(req.password), req.display_name, req.phone, "owner", now, now)
    )

    token = create_session(DB_PATH, user_id)
    return {
        "ok": True,
        "message": "注册成功",
        "token": token,
        "user": {
            "id": user_id,
            "username": req.username,
            "display_name": req.display_name or req.username,
            "role": "owner",
        }
    }

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """用户登录"""
    user = db_query("SELECT * FROM users WHERE username = ?", (req.username,), fetch="one")
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_session(DB_PATH, user["id"])
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"] or user["username"],
            "role": user["role"],
        }
    }

@app.post("/api/auth/logout")
async def logout(request: Request):
    """登出"""
    token = extract_token(request)
    if token:
        invalidate_session(DB_PATH, token)
    return {"ok": True, "message": "已登出"}

@app.get("/api/auth/me")
async def me(user: dict = Depends(require_auth)):
    """获取当前用户信息"""
    stores = get_user_stores(DB_PATH, user["user_id"])
    return {
        "user": user,
        "stores": stores,
    }


# ===== 门店管理接口 =====
@app.get("/api/stores")
async def list_stores(user: dict = Depends(require_auth)):
    """获取当前用户的门店列表"""
    stores = get_user_stores(DB_PATH, user["user_id"])
    return {"stores": stores}

@app.post("/api/stores")
async def create_store(req: StoreRequest, user: dict = Depends(require_auth)):
    """添加门店"""
    store_id = str(uuid.uuid4())
    now = time.time()
    db_exec(
        "INSERT INTO stores (id, name, address, city, district, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (store_id, req.name, req.address, req.city, req.district, user["user_id"], now)
    )
    # 关联到用户
    db_exec(
        "INSERT INTO user_stores (user_id, store_id, role) VALUES (?, ?, ?)",
        (user["user_id"], store_id, "owner")
    )
    return {
        "ok": True,
        "store": {
            "id": store_id,
            "name": req.name,
            "address": req.address,
            "city": req.city,
            "district": req.district,
        }
    }

@app.put("/api/stores/{store_id}")
async def update_store(store_id: str, req: StoreRequest, user: dict = Depends(require_auth)):
    """修改门店"""
    store = get_store_by_id(DB_PATH, store_id, user["user_id"])
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或无权限")
    db_exec(
        "UPDATE stores SET name=?, address=?, city=?, district=? WHERE id=?",
        (req.name, req.address, req.city, req.district, store_id)
    )
    return {"ok": True}

@app.delete("/api/stores/{store_id}")
async def delete_store(store_id: str, user: dict = Depends(require_auth)):
    """删除门店"""
    store = get_store_by_id(DB_PATH, store_id, user["user_id"])
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或无权限")
    db_exec("DELETE FROM user_stores WHERE store_id=?", (store_id,))
    db_exec("DELETE FROM stores WHERE id=?", (store_id,))
    return {"ok": True}


# ===== 业务接口（改造现有接口）=====
@app.get("/")
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.get("/api/status")
async def status(user: dict = Depends(require_auth_optional)):
    cfg = load_config()
    llm = cfg.get("llm", {})
    has_key = bool(llm.get("api_key"))
    result = {
        "agent_name": cfg.get("agent", {}).get("name", "鹿小仓"),
        "version": cfg.get("agent", {}).get("version", "0.4"),
        "brand": cfg.get("agent", {}).get("brand", "复投科技出品"),
        "llm_configured": has_key,
        "llm_provider": llm.get("provider", ""),
        "llm_model": llm.get("model", ""),
        "timestamp": time.time(),
        "tools": list(TOOLS.keys()),
        "agent_loop_enabled": True,
    }
    if user:
        result["logged_in"] = True
        result["user"] = user
        result["stores"] = get_user_stores(DB_PATH, user["user_id"])
    else:
        result["logged_in"] = False
    return result

@app.get("/api/data/assets")
async def data_assets(user: dict = Depends(require_auth)):
    """数据资产（按用户隔离）"""
    user_id = user["user_id"]
    rows = db_query("SELECT * FROM data_assets WHERE user_id=? ORDER BY created_at DESC", (user_id,), fetch="all")
    builtin = [
        {"name": "鹿小仓广安店", "rows": 2941, "type": "门店"},
        {"name": "鹿小仓财富店", "rows": 1386, "type": "门店"},
        {"name": "小柴购（竞品）", "rows": 7659, "type": "竞品"},
        {"name": "厉臣超市（竞品）", "rows": 1996, "type": "竞品"},
        {"name": "商圈POI扫描", "rows": 1396, "type": "商圈"},
    ]
    return {"builtin": builtin, "custom": rows, "total_sku": 13982}

@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_auth)):
    """对话（按用户和门店隔离）"""
    user_id = user["user_id"]
    store_id = req.store_id

    # 如果指定了门店，验证权限
    if store_id:
        store = get_store_by_id(DB_PATH, store_id, user_id)
        if not store:
            raise HTTPException(status_code=403, detail="无权访问该门店")

    save_message("user", req.message, req.session_id, user_id, store_id)
    history = get_conversation_history(req.session_id, limit=10, user_id=user_id, store_id=store_id)

    # 注入门店上下文
    store_context = ""
    if store_id:
        store_info = get_store_by_id(DB_PATH, store_id, user_id)
        if store_info:
            store_context = f"\n\n## 当前门店\n名称: {store_info['name']}\n地址: {store_info.get('address', '未知')}\n区域: {store_info.get('district', '未知')}"

    async def stream_response():
        full_reply = ""
        try:
            async for chunk in agent_loop(req.message, history, config, store_context=store_context):
                full_reply += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            save_message("assistant", full_reply, req.session_id, user_id, store_id)
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")

@app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in TOOLS.values()
        ]
    }

@app.get("/api/conversations")
async def conversations(session_id: str = "default", limit: int = 50, user: dict = Depends(require_auth)):
    """对话历史（按用户隔离）"""
    rows = db_query(
        "SELECT * FROM conversations WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
        (user["user_id"], limit),
        fetch="all"
    )
    rows.reverse()
    return {"messages": rows}

@app.get("/api/config")
async def get_config(user: dict = Depends(require_auth)):
    """获取配置（需要登录）"""
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
async def update_config(req: ConfigRequest, user: dict = Depends(require_auth)):
    """更新配置（需要登录）"""
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


# ===== 数据迁移：首次升级时自动创建默认用户 =====
def migrate_default_user():
    """如果 users 表为空，创建默认用户并迁移现有数据"""
    count = db_query("SELECT COUNT(*) as c FROM users", fetch="one")
    if count and count["c"] > 0:
        return  # 已有用户，跳过

    print("[迁移] 首次升级，创建默认用户 luxiaocang...")
    user_id = str(uuid.uuid4())
    now = time.time()
    db_exec(
        "INSERT INTO users (id, username, password_hash, display_name, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, "luxiaocang", hash_password("LXC2025"), "鹿小仓", "owner", now, now)
    )

    # 创建两个门店
    store1_id = str(uuid.uuid4())
    store2_id = str(uuid.uuid4())
    db_exec(
        "INSERT INTO stores (id, name, address, city, district, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (store1_id, "鹿小仓广安店", "承德双桥区广安购物中心", "承德", "双桥区", user_id, now)
    )
    db_exec(
        "INSERT INTO stores (id, name, address, city, district, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (store2_id, "鹿小仓财富店", "承德双滦区财富广场", "承德", "双滦区", user_id, now)
    )
    # 关联
    db_exec("INSERT INTO user_stores (user_id, store_id, role) VALUES (?, ?, ?)", (user_id, store1_id, "owner"))
    db_exec("INSERT INTO user_stores (user_id, store_id, role) VALUES (?, ?, ?)", (user_id, store2_id, "owner"))

    # 给现有对话记录打上 user_id
    db_exec("UPDATE conversations SET user_id = ?", (user_id,))

    print(f"[迁移] 完成。用户: luxiaocang, 门店: 广安店({store1_id[:8]}), 财富店({store2_id[:8]})")

migrate_default_user()


# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    host = config.get("server", {}).get("host", "127.0.0.1")
    port = int(config.get("server", {}).get("port", "8420"))
    url = f"http://{host}:{port}"
    print(f"鹿小仓 v0.4 启动中... {url}")
    uvicorn.run(app, host=host, port=port, log_level="info")
