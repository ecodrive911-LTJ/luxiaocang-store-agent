"""
鹿小仓 便利店经营决策Agent v0.5
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
    invalidate_session, get_user_stores, get_store_by_id, extract_token,
    require_role, require_permission, has_permission, ROLES
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
        "version": "0.5",
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
    def column_exists(table, col):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols

    for table in ["conversations", "tasks", "data_assets"]:
        if not column_exists(table, "user_id"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")
        if not column_exists(table, "store_id"):
            c.execute(f"ALTER TABLE {table} ADD COLUMN store_id TEXT")

    # ===== v0.5 数据采集任务系统 =====
    # 任务主表
    c.execute("""CREATE TABLE IF NOT EXISTS collect_tasks (
        id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL,
        created_by TEXT NOT NULL,
        assigned_to TEXT,
        task_type TEXT NOT NULL DEFAULT 'price_compare',
        title TEXT NOT NULL,
        description TEXT,
        competitor_store_id TEXT,
        competitor_store_name TEXT,
        status TEXT DEFAULT 'pending',
        deadline TEXT,
        created_at REAL,
        updated_at REAL,
        FOREIGN KEY (store_id) REFERENCES stores(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )""")

    # 任务明细：每个要采集的商品
    c.execute("""CREATE TABLE IF NOT EXISTS collect_task_items (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        product_spec TEXT,
        product_barcode TEXT,
        category TEXT,
        status TEXT DEFAULT 'pending',
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY (task_id) REFERENCES collect_tasks(id)
    )""")

    # 上传记录
    c.execute("""CREATE TABLE IF NOT EXISTS collect_uploads (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        task_item_id TEXT,
        uploaded_by TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER,
        duration_seconds REAL,
        status TEXT DEFAULT 'pending',
        result_json TEXT,
        error_message TEXT,
        uploaded_at REAL,
        analyzed_at REAL,
        FOREIGN KEY (task_id) REFERENCES collect_tasks(id),
        FOREIGN KEY (uploaded_by) REFERENCES users(id)
    )""")

    # 比价结果
    c.execute("""CREATE TABLE IF NOT EXISTS price_data (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        upload_id TEXT,
        store_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        product_spec TEXT,
        competitor_store TEXT,
        price REAL,
        has_promotion INTEGER DEFAULT 0,
        promotion_desc TEXT,
        captured_at REAL,
        source_video TEXT,
        ai_confidence REAL,
        FOREIGN KEY (task_id) REFERENCES collect_tasks(id),
        FOREIGN KEY (store_id) REFERENCES stores(id)
    )""")

    # 对标商品清单（系统级商品基准库）
    c.execute("""CREATE TABLE IF NOT EXISTS benchmark_products (
        id TEXT PRIMARY KEY,
        product_name TEXT NOT NULL,
        product_spec TEXT,
        product_barcode TEXT,
        category TEXT,
        product_role TEXT DEFAULT 'regular',
        is_active INTEGER DEFAULT 1,
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
        row = c.fetchone()
        result = dict(row) if row else None
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
    role: str = "store_owner"  # admin 可指定角色

class LoginRequest(BaseModel):
    username: str
    password: str

class StoreRequest(BaseModel):
    name: str
    address: str = None
    city: str = None
    district: str = None

class UserRoleRequest(BaseModel):
    role: str  # admin / manager / store_owner


# ===== 认证接口 =====
@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request):
    """用户注册
    - 公开注册（allow_registration=true）：只能注册 owner 角色
    - admin 登录时注册：可指定任意角色
    """
    # 判断是否有 admin token（admin 主动创建用户）
    token = extract_token(request)
    creator_is_admin = False
    if token:
        creator = verify_session(DB_PATH, token)
        if creator and creator["role"] == "admin":
            creator_is_admin = True

    # 非admin注册需要检查是否开放注册
    if not creator_is_admin:
        allow_reg = config.get("auth", {}).get("allow_registration", "true") == "true"
        if not allow_reg:
            raise HTTPException(status_code=403, detail="注册已关闭，请联系管理员")
        # 公开注册只能是 store_owner
        if req.role != "store_owner":
            raise HTTPException(status_code=403, detail="无权创建该角色用户")

    # 验证角色合法性
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"无效角色，可选: {', '.join(ROLES.keys())}")

    if len(req.username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少2个字符")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    existing = db_query("SELECT id FROM users WHERE username = ?", (req.username,), fetch="one")
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user_id = str(uuid.uuid4())
    now = time.time()
    db_exec(
        "INSERT INTO users (id, username, password_hash, display_name, phone, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, req.username, hash_password(req.password), req.display_name, req.phone, req.role, now, now)
    )

    # 如果是admin创建用户，不自动登录，返回用户信息
    if creator_is_admin:
        return {
            "ok": True,
            "message": f"用户 {req.username} 创建成功",
            "user": {
                "id": user_id,
                "username": req.username,
                "display_name": req.display_name or req.username,
                "role": req.role,
            }
        }

    # 公开注册自动登录
    token = create_session(DB_PATH, user_id)
    return {
        "ok": True,
        "message": "注册成功",
        "token": token,
        "user": {
            "id": user_id,
            "username": req.username,
            "display_name": req.display_name or req.username,
            "role": req.role,
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
async def create_store(req: StoreRequest, user: dict = Depends(require_role("admin"))):
    """添加门店（仅 admin）"""
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
async def update_store(store_id: str, req: StoreRequest, user: dict = Depends(require_role("admin"))):
    """修改门店（仅 admin）"""
    store = get_store_by_id(DB_PATH, store_id, user["user_id"])
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或无权限")
    db_exec(
        "UPDATE stores SET name=?, address=?, city=?, district=? WHERE id=?",
        (req.name, req.address, req.city, req.district, store_id)
    )
    return {"ok": True}

@app.delete("/api/stores/{store_id}")
async def delete_store(store_id: str, user: dict = Depends(require_role("admin"))):
    """删除门店（仅 admin）"""
    store = get_store_by_id(DB_PATH, store_id, user["user_id"])
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或无权限")
    db_exec("DELETE FROM user_stores WHERE store_id=?", (store_id,))
    db_exec("DELETE FROM stores WHERE id=?", (store_id,))
    return {"ok": True}


# ===== 用户管理接口（admin only）=====
@app.get("/api/users")
async def list_users(user: dict = Depends(require_role("admin"))):
    """获取所有用户列表（仅 admin）"""
    rows = db_query("SELECT id, username, display_name, phone, role, created_at FROM users ORDER BY created_at", fetch="all")
    return {"users": rows}

@app.put("/api/users/{user_id}/role")
async def update_user_role(user_id: str, req: UserRoleRequest, user: dict = Depends(require_role("admin"))):
    """修改用户角色（仅 admin）"""
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"无效角色，可选: {', '.join(ROLES.keys())}")
    target = db_query("SELECT id FROM users WHERE id = ?", (user_id,), fetch="one")
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    db_exec("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (req.role, time.time(), user_id))
    return {"ok": True, "message": f"用户角色已更新为 {ROLES[req.role]['label']}"}

@app.get("/api/roles")
async def list_roles(user: dict = Depends(require_auth)):
    """获取角色列表"""
    return {"roles": {k: {"label": v["label"], "level": v["level"]} for k, v in ROLES.items()}}


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
    """数据资产（按角色隔离）
    - admin/manager：全部数据（两家门店+竞品+商圈）
    - store_owner：仅本店数据，不显示竞品和商圈
    """
    user_id = user["user_id"]
    role = user.get("role", "store_owner")
    user_stores = get_user_stores(DB_PATH, user_id)

    rows = db_query("SELECT * FROM data_assets WHERE user_id=? ORDER BY created_at DESC", (user_id,), fetch="all")

    if role == "store_owner":
        # Store owner: only own store data
        my_store_name = user_stores[0]["name"] if user_stores else "本店"
        # Try to count actual SKUs for this store from price_data or other tables
        store_id = user_stores[0]["id"] if user_stores else None
        store_count = 0
        if store_id:
            try:
                count_row = db_query(
                    "SELECT COUNT(*) as cnt FROM price_data WHERE store_id=?",
                    (store_id,), fetch="one"
                )
                if count_row:
                    store_count = count_row["cnt"]
            except:
                pass
        # If no price_data, fall back to builtin counts
        if store_count == 0 and user_stores:
            # Check store name
            name = user_stores[0]["name"]
            if "广安" in name:
                store_count = 2941
            elif "财富" in name:
                store_count = 1386

        assets = {my_store_name: store_count}
        return {"assets": assets, "role": "store_owner", "store_name": my_store_name}
    else:
        # Admin / Manager: full data
        builtin = {
            "鹿小仓广安店": 2941,
            "鹿小仓财富店": 1386,
            "小柴购（竞品）": 7659,
            "厉臣超市（竞品）": 1996,
            "商圈POI扫描": 1396,
        }
        total = sum(builtin.values())
        return {"assets": builtin, "total_sku": total, "role": role, "custom": rows}

@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_auth)):
    """对话（按角色和门店隔离）
    - store_owner：强制绑定其唯一门店，不可传入其他门店ID
    - admin/manager：可指定任意有权限的门店
    """
    user_id = user["user_id"]
    role = user.get("role", "store_owner")
    user_stores = get_user_stores(DB_PATH, user_id)
    store_id = req.store_id

    # Store owner: auto-bind to their only store, ignore passed store_id
    if role == "store_owner":
        if not user_stores:
            raise HTTPException(status_code=403, detail="未绑定门店，请联系管理员")
        store_id = user_stores[0]["id"]  # Force to their only store
    elif store_id:
        # Admin/Manager: verify access
        store = get_store_by_id(DB_PATH, store_id, user_id)
        if not store:
            raise HTTPException(status_code=403, detail="无权访问该门店")

    save_message("user", req.message, req.session_id, user_id, store_id)
    history = get_conversation_history(req.session_id, limit=10, user_id=user_id, store_id=store_id)

    # 注入门店上下文 + 角色上下文
    store_context = ""
    role_context = f"\n\n## 当前角色\n{ROLES.get(role, {}).get('label', role)}（{role}）"
    if store_id:
        store_info = get_store_by_id(DB_PATH, store_id, user_id)
        if store_info:
            store_context = f"\n\n## 当前门店\n名称: {store_info['name']}\n地址: {store_info.get('address', '未知')}\n区域: {store_info.get('district', '未知')}"
    # Store owner: add permission boundary
    if role == "store_owner":
        role_context += "\n⚠️ 你是分店店主，仅能查看本店数据。不可查询竞品全局数据、不可查询其他门店数据、不可使用选址/建店/品牌管理功能。"

    full_context = role_context + store_context

    async def stream_response():
        full_reply = ""
        try:
            async for chunk in agent_loop(req.message, history, config, store_context=full_context):
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
async def get_config(user: dict = Depends(require_permission("view_config"))):
    """获取配置（需要 view_config 权限）"""
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
async def update_config(req: ConfigRequest, user: dict = Depends(require_role("admin"))):
    """更新配置（仅 admin）"""
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


# ===== v0.5 数据采集任务系统 =====

class CreateTaskRequest(BaseModel):
    store_id: str
    task_type: str = "price_compare"  # price_compare / competitor_scan / self_check
    title: str
    description: str = None
    competitor_store_id: str = None
    competitor_store_name: str = None
    assigned_to: str = None
    deadline: str = None
    items: list = []  # [{product_name, product_spec, category}]

class UpdateTaskItemRequest(BaseModel):
    status: str  # pending / done / skipped


# ===== 对标商品库接口 =====

@app.get("/api/benchmark/products")
async def list_benchmark_products(category: str = None, user: dict = Depends(require_auth)):
    """获取对标商品清单"""
    if category:
        rows = db_query(
            "SELECT * FROM benchmark_products WHERE is_active=1 AND category=? ORDER BY category, product_name",
            (category,), fetch="all"
        )
    else:
        rows = db_query(
            "SELECT * FROM benchmark_products WHERE is_active=1 ORDER BY category, product_name",
            fetch="all"
        )
    # 如果没有数据，返回内置默认列表
    if not rows:
        rows = get_default_benchmark()
    return {"products": rows}

@app.post("/api/benchmark/products")
async def add_benchmark_product(req: dict, user: dict = Depends(require_role("manager"))):
    """添加对标商品"""
    pid = str(uuid.uuid4())
    now = time.time()
    db_exec(
        "INSERT INTO benchmark_products (id, product_name, product_spec, product_barcode, category, product_role, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (pid, req.get("product_name"), req.get("product_spec"), req.get("product_barcode"), req.get("category"), req.get("product_role", "regular"), now)
    )
    return {"ok": True, "id": pid}


# ===== 任务管理接口 =====

@app.post("/api/tasks")
async def create_task(req: CreateTaskRequest, user: dict = Depends(require_role("manager"))):
    """创建采集任务（manager/admin）"""
    task_id = str(uuid.uuid4())
    now = time.time()

    # 验证门店权限（manager/admin 能操作任意门店）
    store = get_store_by_id(DB_PATH, req.store_id, user["user_id"])
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在或无权限")

    db_exec(
        """INSERT INTO collect_tasks
           (id, store_id, created_by, assigned_to, task_type, title, description,
            competitor_store_id, competitor_store_name, status, deadline, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (task_id, req.store_id, user["user_id"], req.assigned_to,
         req.task_type, req.title, req.description,
         req.competitor_store_id, req.competitor_store_name,
         req.deadline, now, now)
    )

    # 插入任务明细
    items_added = 0
    if req.items:
        for idx, item in enumerate(req.items):
            item_id = str(uuid.uuid4())
            db_exec(
                "INSERT INTO collect_task_items (id, task_id, product_name, product_spec, product_barcode, category, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item_id, task_id, item.get("product_name"), item.get("product_spec"),
                 item.get("product_barcode"), item.get("category"), idx)
            )
            items_added += 1

    return {
        "ok": True,
        "task": {
            "id": task_id,
            "title": req.title,
            "task_type": req.task_type,
            "store_name": store["name"],
            "items_count": items_added,
            "status": "pending",
            "deadline": req.deadline,
            "created_at": now,
        }
    }

@app.get("/api/tasks")
async def list_tasks(store_id: str = None, status: str = None, user: dict = Depends(require_auth)):
    """获取任务列表
    - admin/manager：能看所有门店的任务
    - store_owner：只能看自己门店的任务
    """
    user_role = user["role"]

    sql = """SELECT t.*, s.name as store_name,
              (SELECT COUNT(*) FROM collect_task_items WHERE task_id=t.id) as total_items,
              (SELECT COUNT(*) FROM collect_task_items WHERE task_id=t.id AND status='done') as done_items
           FROM collect_tasks t
           JOIN stores s ON t.store_id = s.id
           WHERE 1=1"""
    params = []

    if user_role == "store_owner":
        # 只能看自己门店的任务
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        store_ids = [s["id"] for s in user_stores]
        if not store_ids:
            return {"tasks": []}
        placeholders = ",".join(["?"] * len(store_ids))
        sql += f" AND t.store_id IN ({placeholders})"
        params.extend(store_ids)

    if store_id:
        sql += " AND t.store_id = ?"
        params.append(store_id)

    if status:
        sql += " AND t.status = ?"
        params.append(status)

    sql += " ORDER BY t.created_at DESC LIMIT 50"
    rows = db_query(sql, tuple(params), fetch="all")
    return {"tasks": rows}

@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str, user: dict = Depends(require_auth)):
    """获取任务详情，含商品清单"""
    task = db_query("""SELECT t.*, s.name as store_name
        FROM collect_tasks t JOIN stores s ON t.store_id = s.id WHERE t.id=?""",
        (task_id,), fetch="one")
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 权限检查：store_owner 只能看自己门店的
    user_role = user["role"]
    if user_role == "store_owner":
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        if not any(s["id"] == task["store_id"] for s in user_stores):
            raise HTTPException(status_code=403, detail="无权查看该任务")

    items = db_query(
        "SELECT * FROM collect_task_items WHERE task_id=? ORDER BY sort_order",
        (task_id,), fetch="all"
    )
    uploads = db_query(
        """SELECT u.*, ti.product_name
           FROM collect_uploads u
           LEFT JOIN collect_task_items ti ON u.task_item_id = ti.id
           WHERE u.task_id=? ORDER BY u.uploaded_at DESC""",
        (task_id,), fetch="all"
    )
    return {"task": task, "items": items, "uploads": uploads}

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, req: dict, user: dict = Depends(require_role("manager"))):
    """更新任务状态或指派"""
    now = time.time()
    if "status" in req:
        db_exec("UPDATE collect_tasks SET status=?, updated_at=? WHERE id=?", (req["status"], now, task_id))
    if "assigned_to" in req:
        db_exec("UPDATE collect_tasks SET assigned_to=?, updated_at=? WHERE id=?", (req["assigned_to"], now, task_id))
    return {"ok": True}


# ===== 视频上传接口 =====

import shutil

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/tasks/{task_id}/upload")
async def upload_video(task_id: str, request: Request, user: dict = Depends(require_auth)):
    """上传采集视频
    - Content-Type: multipart/form-data
    - 字段名: video_file
    - 可附带字段: task_item_id, note
    """
    # 验证任务存在
    task = db_query("SELECT * FROM collect_tasks WHERE id=?", (task_id,), fetch="one")
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 权限：store_owner 只能上传自己门店的
    user_role = user["role"]
    if user_role == "store_owner":
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        if not any(s["id"] == task["store_id"] for s in user_stores):
            raise HTTPException(status_code=403, detail="无权上传到该任务")

    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="请使用 multipart/form-data 格式上传")

    video_file = form.get("video_file")
    if not video_file:
        raise HTTPException(status_code=400, detail="缺少 video_file 字段")

    # 读取文件内容
    content = await video_file.read()
    size = len(content)

    # 文件大小限制：50MB
    if size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="视频文件不能超过50MB")

    # 保存到 uploads 目录
    file_ext = os.path.splitext(video_file.filename or "video.mp4")[1] or ".mp4"
    safe_name = f"{task_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    # 写入数据库
    upload_id = str(uuid.uuid4())
    now = time.time()
    task_item_id = form.get("task_item_id", None)

    db_exec(
        """INSERT INTO collect_uploads
           (id, task_id, task_item_id, uploaded_by, filename, file_path, file_size, status, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (upload_id, task_id, str(task_item_id) if task_item_id else None,
         user["user_id"], video_file.filename or safe_name, str(file_path), size, now)
    )

    # 如果有 task_item_id，标记该明细为已提交
    if task_item_id:
        db_exec("UPDATE collect_task_items SET status='done' WHERE id=?", (str(task_item_id),))

    # 更新任务状态
    db_exec("UPDATE collect_tasks SET status='in_progress', updated_at=? WHERE id=?", (now, task_id))

    return {
        "ok": True,
        "upload_id": upload_id,
        "filename": video_file.filename or safe_name,
        "file_size": size,
        "status": "pending",
        "message": "上传成功，等待AI分析"
    }


# ===== 上传记录 & 分析状态 =====

@app.get("/api/tasks/{task_id}/uploads")
async def list_uploads(task_id: str, user: dict = Depends(require_auth)):
    """获取任务的所有上传记录"""
    rows = db_query(
        """SELECT u.*, ti.product_name
           FROM collect_uploads u
           LEFT JOIN collect_task_items ti ON u.task_item_id = ti.id
           WHERE u.task_id=? ORDER BY u.uploaded_at DESC""",
        (task_id,), fetch="all"
    )
    return {"uploads": rows}


# ===== 比价数据查询 =====

@app.get("/api/price-data")
async def get_price_data(store_id: str = None, product_name: str = None, limit: int = 50, user: dict = Depends(require_auth)):
    """查询比价数据
    - admin/manager：能查任意门店
    - store_owner：只能查自己的门店
    """
    user_role = user["role"]
    sql = "SELECT * FROM price_data WHERE 1=1"
    params = []

    if store_id:
        sql += " AND store_id = ?"
        params.append(store_id)

    if user_role == "store_owner":
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        store_ids = [s["id"] for s in user_stores]
        if store_id and store_id not in store_ids:
            raise HTTPException(status_code=403, detail="无权查看该门店的比价数据")
        if not store_id:
            if not store_ids:
                return {"price_data": []}
            placeholders = ",".join(["?"] * len(store_ids))
            sql += f" AND store_id IN ({placeholders})"
            params.extend(store_ids)

    if product_name:
        sql += " AND product_name LIKE ?"
        params.append(f"%{product_name}%")

    sql += " ORDER BY captured_at DESC LIMIT ?"
    params.append(limit)

    rows = db_query(sql, tuple(params), fetch="all")
    return {"price_data": rows}


@app.get("/api/price-data/summary")
async def get_price_summary(store_id: str = None, user: dict = Depends(require_auth)):
    """比价汇总：每个商品的竞品最低价、平均价、我方价格位次"""
    user_role = user["role"]

    if not store_id:
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        if not user_stores:
            return {"summary": []}
        store_id = user_stores[0]["id"]

    sql = """SELECT
        product_name,
        product_spec,
        COUNT(*) as data_points,
        MIN(price) as min_price,
        MAX(price) as max_price,
        ROUND(AVG(price), 2) as avg_price,
        MIN(captured_at) as first_captured,
        MAX(captured_at) as last_captured
    FROM price_data
    WHERE store_id = ?
    GROUP BY product_name, COALESCE(product_spec, '')
    ORDER BY product_name
    """
    rows = db_query(sql, (store_id,), fetch="all")
    return {"summary": rows}


# ===== 内置对标商品清单 =====

def get_default_benchmark():
    """返回便利店引流品核心对标清单（30-50个SKU）"""
    products = [
        # 饮用水
        {"product_name": "农夫山泉天然水", "product_spec": "550ml", "category": "饮用水", "product_role": "traffic"},
        {"product_name": "怡宝纯净水", "product_spec": "555ml", "category": "饮用水", "product_role": "traffic"},
        {"product_name": "百岁山矿泉水", "product_spec": "570ml", "category": "饮用水", "product_role": "traffic"},
        {"product_name": "康师傅饮用水", "product_spec": "550ml", "category": "饮用水", "product_role": "traffic"},
        # 碳酸饮料
        {"product_name": "可口可乐", "product_spec": "500ml", "category": "碳酸饮料", "product_role": "traffic"},
        {"product_name": "百事可乐", "product_spec": "500ml", "category": "碳酸饮料", "product_role": "traffic"},
        {"product_name": "雪碧", "product_spec": "500ml", "category": "碳酸饮料", "product_role": "traffic"},
        {"product_name": "芬达橙味", "product_spec": "500ml", "category": "碳酸饮料", "product_role": "traffic"},
        # 茶饮
        {"product_name": "康师傅冰红茶", "product_spec": "500ml", "category": "茶饮", "product_role": "traffic"},
        {"product_name": "康师傅绿茶", "product_spec": "500ml", "category": "茶饮", "product_role": "traffic"},
        {"product_name": "统一阿萨姆奶茶", "product_spec": "500ml", "category": "茶饮", "product_role": "traffic"},
        {"product_name": "东方树叶茉莉花茶", "product_spec": "500ml", "category": "茶饮", "product_role": "regular"},
        # 功能饮料
        {"product_name": "红牛维生素功能饮料", "product_spec": "250ml", "category": "功能饮料", "product_role": "traffic"},
        {"product_name": "东鹏特饮", "product_spec": "500ml", "category": "功能饮料", "product_role": "traffic"},
        # 乳制品
        {"product_name": "蒙牛纯牛奶", "product_spec": "250ml", "category": "乳制品", "product_role": "traffic"},
        {"product_name": "伊利纯牛奶", "product_spec": "250ml", "category": "乳制品", "product_role": "traffic"},
        {"product_name": "安慕希酸奶", "product_spec": "205g", "category": "乳制品", "product_role": "regular"},
        # 方便面
        {"product_name": "康师傅红烧牛肉面", "product_spec": "105g", "category": "方便面", "product_role": "traffic"},
        {"product_name": "统一老坛酸菜牛肉面", "product_spec": "105g", "category": "方便面", "product_role": "traffic"},
        {"product_name": "汤达人日式豚骨拉面", "product_spec": "80g", "category": "方便面", "product_role": "regular"},
        # 零食
        {"product_name": "乐事原味薯片", "product_spec": "75g", "category": "膨化食品", "product_role": "traffic"},
        {"product_name": "奥利奥原味夹心饼干", "product_spec": "97g", "category": "饼干", "product_role": "traffic"},
        {"product_name": "好丽友派", "product_spec": "68g", "category": "糕点", "product_role": "regular"},
        {"product_name": "德芙丝滑牛奶巧克力", "product_spec": "43g", "category": "糖果巧克力", "product_role": "regular"},
        # 日用品
        {"product_name": "心相印手帕纸", "product_spec": "10包装", "category": "纸品", "product_role": "traffic"},
        {"product_name": "清风抽纸", "product_spec": "3包装", "category": "纸品", "product_role": "traffic"},
        # 啤酒
        {"product_name": "青岛啤酒经典", "product_spec": "500ml", "category": "啤酒", "product_role": "traffic"},
        {"product_name": "雪花啤酒勇闯天涯", "product_spec": "500ml", "category": "啤酒", "product_role": "traffic"},
        # 咖啡
        {"product_name": "雀巢咖啡丝滑拿铁", "product_spec": "268ml", "category": "咖啡", "product_role": "regular"},
        # 方便食品
        {"product_name": "双汇王中王火腿肠", "product_spec": "60g", "category": "肉制品", "product_role": "traffic"},
        # 果汁
        {"product_name": "美汁源果粒橙", "product_spec": "420ml", "category": "果汁", "product_role": "regular"},
    ]
    return products


# ===== 数据迁移：首次升级时自动创建默认用户 =====
def migrate_default_user():
    """如果 users 表为空，创建默认用户并迁移现有数据"""
    count = db_query("SELECT COUNT(*) as c FROM users", fetch="one")
    if count and count["c"] > 0:
        return  # 已有用户，跳过

    print("[迁移] 首次升级，创建默认管理员 luxiaocang...")
    user_id = str(uuid.uuid4())
    now = time.time()
    db_exec(
        "INSERT INTO users (id, username, password_hash, display_name, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, "luxiaocang", hash_password("LXC2025"), "鹿小仓管理员", "admin", now, now)
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

    print(f"[迁移] 完成。管理员: luxiaocang(admin), 门店: 广安店({store1_id[:8]}), 财富店({store2_id[:8]})")

migrate_default_user()


# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    host = config.get("server", {}).get("host", "127.0.0.1")
    port = int(config.get("server", {}).get("port", "8420"))
    url = f"http://{host}:{port}"
    print(f"鹿小仓 v0.4 启动中... {url}")
    uvicorn.run(app, host=host, port=port, log_level="info")
