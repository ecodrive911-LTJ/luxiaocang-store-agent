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
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent_loop import agent_loop, call_llm_stream, call_llm_raw, register_tool, TOOLS
from memory import (build_memory_context, extract_and_save_memory, get_memory_summary,
                   build_preference_context, record_query, get_top_preferences)
from ingestion import parse_and_import, get_real_sales_summary, get_import_history, make_template_csv
from product_analysis import (
    classify_products as pa_classify,
    category_gap_analysis as pa_category_gap,
    identify_slow_moving as pa_slow_moving,
    basket_analysis as pa_basket,
    full_analysis as pa_full,
)
from analytics import compute_store_dashboard, compute_hq_dashboard
from build_store import build_store_plan as bs_plan
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
        retry_count INTEGER DEFAULT 0,
        uploaded_at REAL,
        analyzed_at REAL,
        file_md5 TEXT,
        FOREIGN KEY (task_id) REFERENCES collect_tasks(id),
        FOREIGN KEY (uploaded_by) REFERENCES users(id)
    )""")
    # 尝试追加 file_md5 列（表可能已存在旧版本）
    try:
        c.execute("ALTER TABLE collect_uploads ADD COLUMN file_md5 TEXT")
    except Exception:
        pass  # 列已存在
    # 尝试追加 retry_count 列（旧表兼容）
    try:
        c.execute("ALTER TABLE collect_uploads ADD COLUMN retry_count INTEGER DEFAULT 0")
    except Exception:
        pass  # 列已存在
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

    # 操作审计日志
    c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        username TEXT,
        role TEXT,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        store_id TEXT,
        details_json TEXT,
        ip_address TEXT,
        result TEXT DEFAULT 'success',
        created_at REAL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_logs(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")

    # 消息队列（D2-01 AI主动巡检推送）
    c.execute("""CREATE TABLE IF NOT EXISTS message_queue (
        id TEXT PRIMARY KEY,
        store_id TEXT,
        user_id TEXT,
        level TEXT DEFAULT 'info',
        title TEXT NOT NULL,
        body TEXT,
        related_type TEXT,
        related_id TEXT,
        is_read INTEGER DEFAULT 0,
        created_at REAL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_store_time ON message_queue(store_id, created_at)")

    # ===== D2-09 门店画像 & Agent长期记忆 =====
    c.execute("""CREATE TABLE IF NOT EXISTS store_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        profile_type TEXT NOT NULL,
        content_json TEXT NOT NULL,
        content_key TEXT,
        confidence REAL DEFAULT 0.5,
        source TEXT,
        last_updated REAL,
        created_at REAL,
        UNIQUE(store_id, profile_type, content_key)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_profiles_store ON store_profiles(store_id, profile_type)")

    c.execute("""CREATE TABLE IF NOT EXISTS agent_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        detail_json TEXT,
        source_conversation_id TEXT,
        importance INTEGER DEFAULT 1,
        last_recalled_at REAL,
        recall_count INTEGER DEFAULT 0,
        archived INTEGER DEFAULT 0,
        created_at REAL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_memory_store ON agent_memory(store_id, archived, importance)")

    # D2-08: 用户偏好学习 —— 记录高频查询的「问题类型 + 品类/门店」
    c.execute("""CREATE TABLE IF NOT EXISTS query_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        category TEXT NOT NULL,
        topic TEXT NOT NULL DEFAULT '',
        count INTEGER DEFAULT 1,
        first_at REAL,
        updated_at REAL,
        UNIQUE(store_id, category, topic)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_query_store ON query_stats(store_id, count)")

    # D2-11: 内部数据采集接入层（raw_data 数据湖）—— 店主从美团/饿了么/收银导出后手动导入
    c.execute("""CREATE TABLE IF NOT EXISTS raw_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        order_id TEXT,
        order_time TEXT,
        product_name TEXT,
        quantity REAL,
        unit_price REAL,
        amount REAL,
        category TEXT,
        batch_id TEXT,
        imported_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS raw_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        review_id TEXT,
        review_time TEXT,
        rating REAL,
        content TEXT,
        batch_id TEXT,
        imported_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS raw_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL,
        item_name TEXT,
        on_sale INTEGER DEFAULT 1,
        price REAL,
        category TEXT,
        batch_id TEXT,
        imported_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS import_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT UNIQUE NOT NULL,
        store_id TEXT NOT NULL,
        data_type TEXT NOT NULL,
        filename TEXT,
        row_count INTEGER,
        status TEXT,
        note TEXT,
        imported_by TEXT,
        imported_at REAL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_raw_orders_store_time ON raw_orders(store_id, order_time)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_raw_reviews_store ON raw_reviews(store_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_raw_items_store ON raw_items(store_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_import_batches_store ON import_batches(store_id, imported_at)")

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
    log_audit({"user_id": user["id"], "username": user["username"], "role": user["role"]},
              "login", resource_type="session", resource_id=token[:8], result="success")
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
    # D2-08: 记录本次咨询的问题类型+主题（高频偏好学习，确定性分类，不调LLM）
    if store_id:
        try:
            record_query(DB_PATH, store_id, req.message)
        except Exception:
            pass
    history = get_conversation_history(req.session_id, limit=10, user_id=user_id, store_id=store_id)
    log_audit(user, "chat", resource_type="conversation", resource_id=req.session_id,
              store_id=store_id, details={"message": req.message[:200]})

    # 注入门店上下文 + 角色上下文 + 告警上下文
    store_context = ""
    role_context = f"\n\n## 当前角色\n{ROLES.get(role, {}).get('label', role)}（{role}）"
    if store_id:
        store_info = get_store_by_id(DB_PATH, store_id, user_id)
        if store_info:
            store_context = f"\n\n## 当前门店\n名称: {store_info['name']}\n地址: {store_info.get('address', '未知')}\n区域: {store_info.get('district', '未知')}"
    # Store owner: add permission boundary
    if role == "store_owner":
        role_context += "\n⚠️ 你是分店店主，仅能查看本店数据。不可查询竞品全局数据、不可查询其他门店数据、不可使用选址/建店/品牌管理功能。"

    # D2-05: 注入最新告警上下文，让AI在对话中主动引用
    alert_context = _get_alert_context(user, store_id)

    # D2-09: 注入门店长期画像 & Agent记忆（对话前召回）
    memory_context = build_memory_context(DB_PATH, store_id) if store_id else ""
    # D2-08: 注入用户高频偏好引用（连续5次同类型后生效，调整AI回答优先级）
    preference_context = build_preference_context(DB_PATH, store_id) if store_id else ""

    # 记忆写回时携带门店名（避免 stream_response 内重复查询）
    store_name_for_memory = store_info["name"] if (store_id and store_info) else ""

    full_context = role_context + store_context + alert_context + memory_context + preference_context

    async def stream_response():
        full_reply = ""
        _persist_done = asyncio.Event()

        # D2-09: 持久化 + 记忆抽取放在「脱离请求生命周期」的后台任务中，
        # 即使客户端中途断开（SSE 超时/刷新），服务端仍会落库，不丢记忆。
        async def _persist_turn():
            try:
                # 等待本轮流式输出结束（正常完成或被客户端断开触发 finally）
                await asyncio.wait_for(_persist_done.wait(), timeout=600)
            except Exception:
                pass
            text = full_reply
            if not (store_id and text.strip()):
                return
            try:
                save_message("assistant", text, req.session_id, user_id, store_id)
            except Exception:
                pass
            # D2-09: LLM 抽取结构化门店画像 & Agent记忆落库（异常不阻断）
            if store_id and text.strip():
                try:
                    await extract_and_save_memory(
                        DB_PATH, store_id, req.message, text, config,
                        session_id=req.session_id, store_name=store_name_for_memory)
                except Exception:
                    pass

        # 用 create_task 启动，不受请求 cancel scope 影响（客户端断开也不会被取消）
        _bg = asyncio.create_task(_persist_turn())

        try:
            async for chunk in agent_loop(req.message, history, config, store_context=full_context):
                full_reply += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            _persist_done.set()

    return StreamingResponse(stream_response(), media_type="text/event-stream")


def _get_alert_context(user: dict, store_id: str = None) -> str:
    """获取最新巡检告警，拼成上下文文本供 system prompt 注入"""
    role = user.get("role", "store_owner")
    user_id = user["user_id"]
    if role in ("admin", "manager") and not store_id:
        rows = db_query(
            "SELECT * FROM message_queue WHERE is_read=0 ORDER BY created_at DESC LIMIT 10",
            fetch="all")
    else:
        sids = [store_id] if store_id else [s["id"] for s in get_user_stores(DB_PATH, user_id)]
        if not sids:
            return ""
        placeholders = ",".join("?" * len(sids))
        rows = db_query(
            f"SELECT * FROM message_queue WHERE is_read=0 AND store_id IN ({placeholders}) ORDER BY created_at DESC LIMIT 10",
            sids, fetch="all")
    if not rows:
        return ""
    level_label = {"urgent": "🔴紧急", "warning": "🟡警告", "info": "🔵提醒"}
    lines = []
    for r in rows:
        lvl = level_label.get(r.get("level", "info"), "🔵提醒")
        lines.append(f"- {lvl} {r['title']}：{r.get('body', '')}")
    return "\n\n## 最新巡检告警（未读）\n" + "\n".join(lines) + "\n\n⚠️ 重要：你应该在对话中主动引用这些告警，帮助用户了解当前经营问题。如果用户没有问及相关话题，可以在回答末尾简要提醒。"


@app.get("/api/chat/proactive-opening")
async def proactive_opening(user: dict = Depends(require_auth)):
    """D2-05: AI主动开场——根据最新巡检告警和门店数据生成主动对话开场白。
    前端在无对话历史时调用此端点，替代静态'你好我是鹿小仓'。"""
    role = user.get("role", "store_owner")
    user_id = user["user_id"]
    user_stores = get_user_stores(DB_PATH, user_id)
    store_id = user_stores[0]["id"] if user_stores else None

    # 收集上下文：门店信息 + 未读告警 + 最近价格数据
    store_info_text = ""
    if store_id:
        s = get_store_by_id(DB_PATH, store_id, user_id)
        if s:
            store_info_text = f"门店：{s['name']}（{s.get('address', '')}）"

    # 未读告警
    alert_context = _get_alert_context(user, store_id)
    alerts_brief = alert_context.replace("\n\n## 最新巡检告警（未读）\n", "").replace(
        "\n\n⚠️ 重要：你应该在对话中主动引用这些告警，帮助用户了解当前经营问题。如果用户没有问及相关话题，可以在回答末尾简要提醒。", "")

    # 最近价格数据摘要
    price_summary = ""
    if store_id:
        price_rows = db_query(
            "SELECT product_name, product_spec, price, competitor_store FROM price_data "
            "WHERE store_id=? ORDER BY captured_at DESC LIMIT 5",
            (store_id,), fetch="all")
        if price_rows:
            price_summary = "\n最近采集的价格数据：\n" + "\n".join(
                f"- {r['product_name']} {r.get('product_spec') or ''}: ¥{r['price']:.2f}（竞品：{r.get('competitor_store') or '未知'}）"
                for r in price_rows if r.get("price"))

    # 构建开场白生成 prompt
    role_label = ROLES.get(role, {}).get("label", role)

    # D2-09: 注入门店长期画像，让主动开场也能引用历史认知
    memory_ctx = build_memory_context(DB_PATH, store_id) if store_id else ""

    opening_prompt = f"""你是「鹿小仓」，一个便利店经营决策Agent。现在用户刚打开对话窗口，你需要生成一句主动开场白。

## 当前用户
角色：{role_label}
{store_info_text}

## 最新巡检告警
{alerts_brief if alerts_brief.strip() else "（暂无告警）"}
{price_summary}
{memory_ctx}

## 开场白要求
1. 如果有告警：直接引用最紧急的告警内容，用具体数字说话（如"可口可乐比竞品贵0.8元"），并给出初步建议
2. 如果无告警但有价格数据：简述最近采集情况，询问是否需要分析
3. 如果都没有：友好问候并引导用户使用功能
4. 控制在2-3句话，简洁有力，不要废话
5. 不要说"你好我是鹿小仓"，直接说正事
6. 用中文，口语化，像同事汇报工作一样自然

请直接输出开场白，不要加任何前缀或解释。"""

    try:
        messages = [{"role": "user", "content": opening_prompt}]
        opening_text = await call_llm_raw(messages, config, stream=False, timeout=30)
        opening_text = opening_text.strip()
        # 如果LLM失败（包含⚠️），返回降级消息
        if opening_text.startswith("⚠️"):
            if alerts_brief.strip():
                opening_text = "📊 今日巡检发现以下异常，建议关注：\n" + alerts_brief.strip()[:200]
            else:
                opening_text = "📊 欢迎回来！目前各项指标正常，有需要随时找我。"
        return {"opening": opening_text, "has_alerts": bool(alerts_brief.strip())}
    except Exception as e:
        return {"opening": f"📊 欢迎回来！随时可以问我经营分析、竞品比价、定价策略等问题。", "has_alerts": False, "error": str(e)}

@app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in TOOLS.values()
        ]
    }


@app.get("/api/memory/summary")
async def memory_summary(store_id: str = None, user: dict = Depends(require_auth)):
    """D2-09: 返回门店画像/记忆概览 + 注入system prompt的上下文文本（用于验证V2-08）"""
    role = user.get("role", "store_owner")
    user_id = user["user_id"]
    owned = get_user_stores(DB_PATH, user_id)
    if not store_id:
        if owned:
            store_id = owned[0]["id"]
        else:
            raise HTTPException(status_code=403, detail="未绑定门店")
    if role == "store_owner":
        if not any(s["id"] == store_id for s in owned):
            raise HTTPException(status_code=403, detail="无权访问该门店")
    elif not get_store_by_id(DB_PATH, store_id, user_id):
        raise HTTPException(status_code=403, detail="无权访问该门店")
    return get_memory_summary(DB_PATH, store_id)


@app.get("/api/memory/preferences")
async def memory_preferences(store_id: str = None, threshold: int = 5,
                             user: dict = Depends(require_auth)):
    """D2-08: 返回门店用户高频咨询偏好（累计>=threshold次）。"""
    role = user.get("role", "store_owner")
    user_id = user["user_id"]
    owned = get_user_stores(DB_PATH, user_id)
    if not store_id:
        if owned:
            store_id = owned[0]["id"]
        else:
            raise HTTPException(status_code=403, detail="未绑定门店")
    if role == "store_owner":
        if not any(s["id"] == store_id for s in owned):
            raise HTTPException(status_code=403, detail="无权访问该门店")
    elif not get_store_by_id(DB_PATH, store_id, user_id):
        raise HTTPException(status_code=403, detail="无权访问该门店")
    prefs = get_top_preferences(DB_PATH, store_id, threshold)
    return {"store_id": store_id, "threshold": threshold, "preferences": prefs}


# ===== D2-11 内部数据采集接入（手动导入）=====

@app.post("/api/data/import")
async def data_import(request: Request, user: dict = Depends(require_auth)):
    """店主从美团/饿了么/收银后台导出 Excel/CSV 后手动导入 (路线A)。
    - Content-Type: multipart/form-data
    - 字段: file(必需), data_type(orders|reviews|items), store_id(可选, store_owner强制本店)
    """
    role = user.get("role", "store_owner")
    user_id = user["user_id"]
    owned = get_user_stores(DB_PATH, user_id)
    if not owned:
        raise HTTPException(status_code=403, detail="未绑定门店")

    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="请使用 multipart/form-data 格式上传")

    file = form.get("file")
    data_type = (form.get("data_type") or "").strip()
    req_store = (form.get("store_id") or "").strip()
    if data_type not in ("orders", "reviews", "items"):
        raise HTTPException(status_code=400, detail="data_type 必须是 orders/reviews/items")
    if not file:
        raise HTTPException(status_code=400, detail="缺少 file 字段")

    # 门店权限：store_owner 锁定本店
    if role == "store_owner":
        store_id = owned[0]["id"]
    else:
        store_id = req_store or (owned[0]["id"] if owned else None)
        if store_id and not get_store_by_id(DB_PATH, store_id, user_id):
            raise HTTPException(status_code=403, detail="无权访问该门店")
    if not store_id:
        raise HTTPException(status_code=400, detail="请指定 store_id")

    filename = getattr(file, "filename", "upload") or "upload"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        result = parse_and_import(DB_PATH, store_id, data_type, filename, content, user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")

    return {"ok": True, "store_id": store_id, **result}


@app.get("/api/data/imports")
async def data_imports(store_id: str = None, user: dict = Depends(require_auth)):
    role = user.get("role", "store_owner")
    user_id = user["user_id"]
    owned = get_user_stores(DB_PATH, user_id)
    if not store_id:
        store_id = owned[0]["id"] if owned else None
    if not store_id:
        raise HTTPException(status_code=403, detail="未绑定门店")
    if role == "store_owner":
        if not any(s["id"] == store_id for s in owned):
            raise HTTPException(status_code=403, detail="无权访问该门店")
    elif not get_store_by_id(DB_PATH, store_id, user_id):
        raise HTTPException(status_code=403, detail="无权访问该门店")
    return {"store_id": store_id, "history": get_import_history(DB_PATH, store_id)}


@app.get("/api/data/template")
async def data_template(data_type: str = "orders", user: dict = Depends(require_auth)):
    if data_type not in ("orders", "reviews", "items"):
        raise HTTPException(status_code=400, detail="data_type 必须是 orders/reviews/items")
    from fastapi.responses import Response
    csv_text = make_template_csv(data_type)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={data_type}_template.csv"},
    )


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


# ===== D2-06 选品规划+商品分层 =====

@app.get("/api/products/classify")
async def api_classify_products(store_id: str, user: dict = Depends(require_auth)):
    """商品自动分层：traffic/profit/regular/long_tail"""
    try:
        result = pa_classify(DB_PATH, store_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")

@app.get("/api/products/category-gap")
async def api_category_gap(store_id: str, user: dict = Depends(require_auth)):
    """品类差异分析：本店vs另一店的SKU差异"""
    try:
        result = pa_category_gap(DB_PATH, store_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")

@app.get("/api/products/slow-moving")
async def api_slow_moving(store_id: str, user: dict = Depends(require_auth)):
    """滞销品识别：基于价格偏离度+加价率+品类占比"""
    try:
        result = pa_slow_moving(DB_PATH, store_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")

@app.get("/api/products/basket-analysis")
async def api_basket_analysis(store_id: str, user: dict = Depends(require_auth)):
    """购物篮关联分析：品类互补搭售建议"""
    try:
        result = pa_basket(DB_PATH, store_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")

@app.get("/api/products/full-analysis")
async def api_full_analysis(store_id: str, user: dict = Depends(require_auth)):
    """一键完整选品分析报告"""
    try:
        result = pa_full(DB_PATH, store_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")


# ===== 建店规划引擎 (D2-后续) =====

@app.get("/api/build_store/plan")
async def api_build_store_plan(
    area: float,
    tier: str = "standard",
    has_fresh: bool = None,
    has_tobacco: bool = True,
    user: dict = Depends(require_auth),
):
    """建店规划：按卖场面积生成品类权重、SKU 推算与货架方案（admin/manager 可用）"""
    try:
        plan = bs_plan(area_m2=area, tier=tier, has_fresh=has_fresh, has_tobacco=has_tobacco)
        return plan.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"建店规划失败: {e}")


# ===== 数据看板接口 (D2-07) =====

@app.get("/api/analytics/store")
async def api_analytics_store(store_id: str = None, user: dict = Depends(require_auth)):
    """单店看板数据。
    store_owner 仅本店；admin/manager 可指定任意店（不传则默认第一店）。
    """
    if user["role"] == "store_owner":
        owned = get_user_stores(DB_PATH, user["user_id"])
        if not owned:
            raise HTTPException(status_code=403, detail="无关联门店")
        store_id = owned[0]["id"]
    if not store_id:
        # admin/manager 不传 store_id 时取第一店
        owned = get_user_stores(DB_PATH, user["user_id"])
        if not owned:
            raise HTTPException(status_code=404, detail="无门店数据")
        store_id = owned[0]["id"]
    try:
        result = compute_store_dashboard(DB_PATH, store_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"看板生成失败: {e}")


@app.get("/api/analytics/headquarters")
async def api_analytics_hq(user: dict = Depends(require_auth)):
    """总部看板：所有门店汇总 + 排行（manager/admin 可见全部，store_owner 看本店视角）"""
    try:
        result = compute_hq_dashboard(DB_PATH)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        # store_owner 只保留本店数据
        if user["role"] == "store_owner":
            owned = get_user_stores(DB_PATH, user["user_id"])
            my_id = owned[0]["id"] if owned else None
            result["stores"] = [s for s in result.get("stores", []) if s["store_id"] == my_id]
            result["store_count"] = len(result["stores"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"看板生成失败: {e}")


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

    log_audit(user, "create_task", resource_type="task", resource_id=task_id,
              store_id=req.store_id, details={"title": req.title, "items": items_added})
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
    """上传采集视频 [D2-1 D2-2]
    - Content-Type: multipart/form-data
    - 字段名: video_file, task_item_id (可选), file_md5 (可选，客户端预计算)
    - 支持格式: MP4/MOV/AVI/MKV/WEBM，≤200MB
    - 含截止日期校验 + MD5去重拦截
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

    # D2-2: 截止日期校验（兼容 ISO 字符串或时间戳，避免 float() 解析 ISO 报错 500）
    if task.get("deadline"):
        dl_raw = task["deadline"]
        try:
            if isinstance(dl_raw, (int, float)):
                dl = float(dl_raw)
            else:
                dl = datetime.fromisoformat(str(dl_raw).strip().replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                dl = float(str(dl_raw).strip())
            except Exception:
                dl = None
        if dl is not None and time.time() > dl:
            raise HTTPException(status_code=400, detail="该任务已过截止日期，无法上传")

    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="请使用 multipart/form-data 格式上传")

    video_file = form.get("video_file")
    if not video_file:
        raise HTTPException(status_code=400, detail="缺少 video_file 字段")

    task_item_id = form.get("task_item_id", None)
    file_md5 = form.get("file_md5", None)  # 客户端预计算MD5

    # 读取文件内容
    content = await video_file.read()
    size = len(content)

    # D2-1: 文件大小限制：200MB
    if size > 200 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="视频文件不能超过200MB")
    if size < 1024:
        raise HTTPException(status_code=400, detail="文件太小，可能是空文件")

    # D2-2: MD5去重拦截 — 同任务+同明细项+同MD5 → 拒绝
    if file_md5:
        dup_sql = "SELECT id, filename, uploaded_at FROM collect_uploads WHERE task_id=? AND file_md5=? AND status NOT IN ('failed')"
        dup_params = [task_id, file_md5]
        if task_item_id:
            dup_sql += " AND task_item_id=?"
            dup_params.append(str(task_item_id))
        dup_sql += " LIMIT 1"
        dup = db_query(dup_sql, dup_params, fetch="one")
        if dup:
            dup_time = datetime.fromtimestamp(dup["uploaded_at"]).strftime("%m-%d %H:%M")
            raise HTTPException(
                status_code=409,
                detail=f"检测到相同视频（{dup['filename']}，{dup_time}已上传），请勿重复上传同一视频"
            )

    # 保存到 uploads 目录
    file_ext = os.path.splitext(video_file.filename or "video.mp4")[1] or ".mp4"
    safe_name = f"{task_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    # 写入数据库
    upload_id = str(uuid.uuid4())
    now = time.time()

    db_exec(
        """INSERT INTO collect_uploads
           (id, task_id, task_item_id, uploaded_by, filename, file_path, file_size, status, uploaded_at, file_md5)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'analyzing', ?, ?)""",
        (upload_id, task_id, str(task_item_id) if task_item_id else None,
         user["user_id"], video_file.filename or safe_name, str(file_path), size, now, file_md5)
    )

    # 如果有 task_item_id，标记该明细为已提交
    if task_item_id:
        db_exec("UPDATE collect_task_items SET status='done' WHERE id=?", (str(task_item_id),))

    # 更新任务状态
    db_exec("UPDATE collect_tasks SET status='in_progress', updated_at=? WHERE id=?", (now, task_id))

    # 异步触发 AI 视频分析
    product_name = db_query(
        "SELECT ti.product_name FROM collect_task_items ti WHERE ti.id=?",
        (str(task_item_id),), fetch="one"
    )
    asyncio.create_task(analyze_upload_video(upload_id, str(file_path), product_name["product_name"] if product_name else None))

    return {
        "ok": True,
        "upload_id": upload_id,
        "filename": video_file.filename or safe_name,
        "file_size": size,
        "status": "analyzing",
        "message": "上传成功，AI分析已自动启动"
    }


@app.get("/api/tasks/{task_id}/check-md5")
async def check_upload_md5(task_id: str, md5: str, task_item_id: str = None, user: dict = Depends(require_auth)):
    """[D2-1] 前端预上传MD5查重接口
    - 前端选好文件后，先计算MD5，调用此接口查询是否已存在
    - 返回 {duplicate: true/false, existing_upload: {...}}
    """
    task = db_query("SELECT * FROM collect_tasks WHERE id=?", (task_id,), fetch="one")
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    sql = "SELECT id, task_item_id, filename, file_size, uploaded_at, status FROM collect_uploads WHERE task_id=? AND file_md5=? AND status NOT IN ('failed')"
    params = [task_id, md5]
    if task_item_id:
        sql += " AND task_item_id=?"
        params.append(task_item_id)
    sql += " LIMIT 1"
    dup = db_query(sql, params, fetch="one")
    return {"duplicate": dup is not None, "existing_upload": dup}


# ===== AI 视频分析异步任务 =====

async def analyze_upload_video(upload_id: str, file_path: str, product_name: str = None):
    """后台异步执行视频分析：抽帧 → OCR → 结构提取（含失败重试 D2-4）"""
    import subprocess, sys
    MAX_RETRY = 2  # 最多重试 2 次（共 3 次尝试）
    attempt = 0
    last_error = ""
    while attempt <= MAX_RETRY:
        attempt += 1
        try:
            # Step 1: 调用单视频解析器（抽帧+OCR+价格提取）
            analyzer_script = str(SCRIPTS_DIR / "analyze_video.py")
            cmd = [sys.executable, analyzer_script, file_path, product_name or ""]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')[-1000:]

            if proc.returncode == 0:
                # 解析解析器输出（取最后一段 JSON）
                parsed = None
                for line in reversed(stdout_text.strip().splitlines()):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            parsed = json.loads(line)
                            break
                        except Exception:
                            parsed = None
                if parsed and parsed.get("success"):
                    # 写入 price_data（核心闭环 V1-6）
                    await _write_price_data(upload_id, product_name, parsed)
                    result_json = json.dumps({
                        "method": "rapidocr",
                        "success": True,
                        "product_name": parsed.get("product_name") or product_name,
                        "detected_price": parsed.get("detected_price"),
                        "product_spec": parsed.get("product_spec"),
                        "promotion_desc": parsed.get("promotion_desc"),
                        "has_promotion": parsed.get("has_promotion", 0),
                        "confidence": parsed.get("confidence", 0),
                    }, ensure_ascii=False)
                    db_exec(
                        "UPDATE collect_uploads SET status='done', result_json=?, analyzed_at=?, retry_count=? WHERE id=?",
                        (result_json, time.time(), attempt, upload_id)
                    )
                    return
                else:
                    last_error = f"解析器未返回有效JSON: {stdout_text[:300]}"
                    print(f"[视频分析] upload={upload_id} 解析结果无效: {last_error[:200]}")
            else:
                # 解析器失败，记录错误，进入重试
                last_error = f"解析器退出码 {proc.returncode}: {stderr_text[:500]}"
                print(f"[视频分析] upload={upload_id} 第{attempt}次失败: {last_error[:200]}")
        except asyncio.TimeoutError:
            last_error = "视频分析超时（180秒）"
            print(f"[视频分析] upload={upload_id} 第{attempt}次超时")
        except Exception as e:
            last_error = f"分析异常: {str(e)[:500]}"
            print(f"[视频分析] upload={upload_id} 第{attempt}次异常: {str(e)[:200]}")

        # 标记重试中（ui 可显示），稍后重试
        if attempt <= MAX_RETRY:
            db_exec(
                "UPDATE collect_uploads SET status='retrying', retry_count=?, error_message=? WHERE id=?",
                (attempt, f"第{attempt}次失败，准备重试: {last_error[:300]}", upload_id)
            )
            await asyncio.sleep(5)  # 退避 5 秒

    # 所有重试耗尽，标记最终失败
    db_exec(
        "UPDATE collect_uploads SET status='failed', error_message=?, analyzed_at=? WHERE id=?",
        (last_error[:500], time.time(), upload_id)
    )


async def _write_price_data(upload_id: str, product_name: str, parsed: dict):
    """将视频解析结果写入 price_data（核心闭环 V1-6）"""
    upload = db_query("SELECT * FROM collect_uploads WHERE id=?", (upload_id,), fetch="one")
    if not upload:
        return
    task = db_query("SELECT * FROM collect_tasks WHERE id=?", (upload["task_id"],), fetch="one")
    store_id = task["store_id"] if task else None
    competitor = (task or {}).get("competitor_store_name")
    # 先删后插，保证每个 upload 仅一条 price_data
    db_exec("DELETE FROM price_data WHERE upload_id=?", (upload_id,))
    db_exec(
        """INSERT INTO price_data
           (id, task_id, upload_id, store_id, product_name, product_spec, competitor_store,
            price, has_promotion, promotion_desc, captured_at, source_video, ai_confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), upload["task_id"], upload_id, store_id,
         parsed.get("product_name") or product_name or "未识别商品",
         parsed.get("product_spec"), competitor,
         parsed.get("detected_price"), parsed.get("has_promotion", 0),
         parsed.get("promotion_desc"), time.time(), upload.get("file_path"),
         parsed.get("confidence", 0))
    )


@app.post("/api/uploads/{upload_id}/reprocess")
async def reprocess_upload(upload_id: str, user: dict = Depends(require_role("manager"))):
    """手动触发重新分析视频（manager/admin）"""
    upload = db_query("SELECT * FROM collect_uploads WHERE id=?", (upload_id,), fetch="one")
    if not upload:
        raise HTTPException(status_code=404, detail="上传记录不存在")
    db_exec("UPDATE collect_uploads SET status='analyzing', error_message=NULL, result_json=NULL WHERE id=?", (upload_id,))
    asyncio.create_task(analyze_upload_video(upload_id, upload["file_path"]))
    log_audit(user, "reprocess", resource_type="upload", resource_id=upload_id, store_id=upload.get("task_id"))
    return {"ok": True, "message": "重新分析已启动", "upload_id": upload_id}


@app.get("/api/uploads/{upload_id}/review")
async def get_upload_review(upload_id: str, user: dict = Depends(require_role("manager"))):
    """获取上传记录的复核信息（仅 manager/admin）"""
    upload = db_query(
        """SELECT u.*, ti.product_name, ti.product_spec,
                  usr.username as uploader_name
           FROM collect_uploads u
           LEFT JOIN collect_task_items ti ON u.task_item_id = ti.id
           LEFT JOIN users usr ON u.uploaded_by = usr.id
           WHERE u.id=?""",
        (upload_id,), fetch="one"
    )
    if not upload:
        raise HTTPException(status_code=404, detail="上传记录不存在")
    # 解析result_json
    parsed = None
    if upload.get("result_json"):
        try:
            parsed = json.loads(upload["result_json"])
        except:
            parsed = {"raw": upload["result_json"]}
    return {
        "upload": upload,
        "parsed": parsed,
        "review_status": upload.get("status"),
        "error_message": upload.get("error_message"),
    }


def _upsert_price_data(upload_id, *, product_name=None, product_spec=None, price=None,
                       has_promotion=None, promotion_desc=None, confidence=1.0):
    """[F2修复] confirm时若price_data无该upload记录则INSERT，否则UPDATE。
    保证人工复核（即使AI解析失败）也能形成价格数据闭环。"""
    existing = db_query("SELECT id FROM price_data WHERE upload_id=?", (upload_id,), fetch="one")
    if existing:
        db_exec("""UPDATE price_data SET
                      product_name=COALESCE(?, product_name),
                      product_spec=COALESCE(?, product_spec),
                      price=COALESCE(?, price),
                      has_promotion=COALESCE(?, has_promotion),
                      promotion_desc=COALESCE(?, promotion_desc),
                      ai_confidence=?
                   WHERE upload_id=?""",
                 (product_name, product_spec, price, has_promotion, promotion_desc, confidence, upload_id))
        return
    upload = db_query("SELECT * FROM collect_uploads WHERE id=?", (upload_id,), fetch="one")
    if not upload:
        return
    task = db_query("SELECT * FROM collect_tasks WHERE id=?", (upload["task_id"],), fetch="one")
    store_id = task["store_id"] if task else None
    competitor = (task or {}).get("competitor_store_name")
    db_exec("""INSERT INTO price_data
        (id, task_id, upload_id, store_id, product_name, product_spec, competitor_store,
         price, has_promotion, promotion_desc, captured_at, source_video, ai_confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), upload["task_id"], upload_id, store_id,
         product_name or "未命名商品", product_spec, competitor, price,
         has_promotion or 0, promotion_desc, time.time(), upload.get("file_path"), confidence))


@app.post("/api/uploads/{upload_id}/confirm")
async def confirm_upload_review(upload_id: str, req: dict, user: dict = Depends(require_role("manager"))):
    """确认/人工修正视频解析结果（manager/admin）。[F2修复] 确保回写 price_data。"""
    upload = db_query("SELECT * FROM collect_uploads WHERE id=?", (upload_id,), fetch="one")
    if not upload:
        raise HTTPException(status_code=404, detail="上传记录不存在")
    confirm = req.get("confirm", True)
    correction = req.get("correction", {})
    existing_parsed = None
    if upload.get("result_json"):
        try:
            existing_parsed = json.loads(upload["result_json"])
        except Exception:
            existing_parsed = None
    if not correction and confirm:
        pn = (existing_parsed or {}).get("product_name") if existing_parsed else None
        pp = (existing_parsed or {}).get("detected_price") if existing_parsed else None
        _upsert_price_data(upload_id, product_name=pn, price=pp, confidence=1.0)
        db_exec("UPDATE collect_uploads SET status='confirmed', analyzed_at=? WHERE id=?", (time.time(), upload_id))
        log_audit(user, "confirm", resource_type="upload", resource_id=upload_id, details={"method": "accepted"})
        return {"ok": True, "message": "已确认（价格数据已写入）", "upload_id": upload_id}
    corrected = {
        "method": "human_corrected",
        "corrected_by": user.get("username"),
        "corrected_at": time.time(),
        "original_result": upload.get("result_json"),
        **correction,
    }
    db_exec(
        "UPDATE collect_uploads SET status='confirmed', result_json=?, analyzed_at=? WHERE id=?",
        (json.dumps(corrected, ensure_ascii=False), time.time(), upload_id)
    )
    # F2: 回写 price_data（人工修正后的可信数据）
    cname = correction.get("product_name") or None
    cspec = correction.get("product_spec") or None
    cprice_raw = correction.get("captured_price")
    try:
        cprice = float(cprice_raw) if cprice_raw not in (None, "") else None
    except (TypeError, ValueError):
        cprice = None
    _upsert_price_data(upload_id, product_name=cname, product_spec=cspec, price=cprice, confidence=1.0)
    log_audit(user, "confirm", resource_type="upload", resource_id=upload_id,
              details={"method": "human_corrected", "correction": correction})
    return {"ok": True, "message": "已保存人工修正（价格数据已写入）", "upload_id": upload_id}


@app.get("/api/uploads/pending")
async def list_pending_uploads(user: dict = Depends(require_role("manager"))):
    """列出待复核的上传（manager/admin）"""
    rows = db_query(
        """SELECT u.*, ti.product_name, ti.product_spec,
                  usr.username as uploader_name, c.title as task_name, s.name as store_name
           FROM collect_uploads u
           JOIN collect_tasks c ON u.task_id = c.id
           LEFT JOIN collect_task_items ti ON u.task_item_id = ti.id
           LEFT JOIN users usr ON u.uploaded_by = usr.id
           LEFT JOIN stores s ON c.store_id = s.id
           WHERE u.status IN ('done', 'failed', 'analyzing', 'retrying')
           ORDER BY u.uploaded_at DESC LIMIT 100""",
        fetch="all"
    )
    return {"uploads": rows, "count": len(rows)}


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


@app.get("/api/price/matrix")
async def price_matrix(store_id: str = None, user: dict = Depends(require_role("manager"))):
    """D3-2 比价矩阵 + 三档定价建议
    聚合某门店的竞品采集价，给出每个商品的竞品价格分布与低/中/高三档建议定价。
    """
    user_role = user["role"]
    if not store_id:
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        if not user_stores:
            return {"matrix": [], "store_id": None}
        store_id = user_stores[0]["id"]
    if user_role == "store_owner":
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        if store_id not in [s["id"] for s in user_stores]:
            raise HTTPException(status_code=403, detail="无权查看该门店")

    store = db_query("SELECT name FROM stores WHERE id=?", (store_id,), fetch="one")
    store_name = store["name"] if store else ""
    # 本店价标记：competitor_store 含 '本店'/'我店'/门店名
    own_markers = ["本店", "我店", store_name]

    rows = db_query(
        "SELECT product_name, product_spec, competitor_store, price, has_promotion, promotion_desc, captured_at FROM price_data WHERE store_id=? ORDER BY product_name, captured_at DESC",
        (store_id,), fetch="all"
    )

    # 按商品聚合
    groups = {}
    for r in rows:
        key = (r["product_name"], r["product_spec"] or "")
        groups.setdefault(key, []).append(r)

    matrix = []
    for (pname, pspec), recs in sorted(groups.items()):
        competitor_prices = [r["price"] for r in recs
                             if not any(mk and mk in (r["competitor_store"] or "") for mk in own_markers)]
        own_recs = [r for r in recs
                    if any(mk and mk in (r["competitor_store"] or "") for mk in own_markers)]
        own_price = own_recs[0]["price"] if own_recs else None
        if competitor_prices:
            cp_min = min(competitor_prices)
            cp_max = max(competitor_prices)
            cp_avg = round(sum(competitor_prices) / len(competitor_prices), 2)
            # 三档定价建议
            tier_low = round(cp_min, 2)                      # 引流档：贴最低价抢客流
            tier_mid = round(cp_avg, 2)                      # 利润档：跟均价
            tier_high = round(cp_max * 1.03, 2)              # 形象/毛利档：略高于最高
            # 我方位次
            if own_price is not None:
                below = sum(1 for p in competitor_prices if p > own_price)
                rank_pct = round(below / len(competitor_prices) * 100)
            else:
                rank_pct = None
        else:
            cp_min = cp_max = cp_avg = tier_low = tier_mid = tier_high = None
            rank_pct = None
        matrix.append({
            "product_name": pname,
            "product_spec": pspec,
            "own_price": own_price,
            "competitor_count": len(competitor_prices),
            "competitor_min": cp_min,
            "competitor_avg": cp_avg,
            "competitor_max": cp_max,
            "tier_low": tier_low,
            "tier_mid": tier_mid,
            "tier_high": tier_high,
            "rank_pct": rank_pct,
            "competitors": [
                {"store": r["competitor_store"], "price": r["price"],
                 "promo": r["promotion_desc"] if r["has_promotion"] else None}
                for r in recs
            ],
        })
    return {"matrix": matrix, "store_id": store_id, "store_name": store_name}


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


# ===== 操作审计 (D1-5) =====

def log_audit(user: dict, action: str, resource_type: str = None, resource_id: str = None,
              store_id: str = None, details: dict = None, result: str = "success", ip: str = None):
    """记录一条审计日志"""
    try:
        log_id = str(uuid.uuid4())
        db_exec(
            """INSERT INTO audit_logs
               (id, user_id, username, role, action, resource_type, resource_id, store_id,
                details_json, ip_address, result, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (log_id, user.get("user_id"), user.get("username"), user.get("role"),
             action, resource_type, resource_id, store_id,
             json.dumps(details, ensure_ascii=False) if details else None,
             ip, result, time.time())
        )
    except Exception as e:
        print(f"[AUDIT] failed to log: {e}")


@app.get("/api/audit/logs")
async def list_audit_logs(
    user_id: str = None, action: str = None, resource_type: str = None,
    limit: int = 100, offset: int = 0,
    user: dict = Depends(require_role("admin"))
):
    """查询审计日志（仅 admin）"""
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if user_id:
        sql += " AND user_id=?"
        params.append(user_id)
    if action:
        sql += " AND action=?"
        params.append(action)
    if resource_type:
        sql += " AND resource_type=?"
        params.append(resource_type)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = db_query(sql, tuple(params), fetch="all")
    return {"logs": rows, "count": len(rows)}


@app.get("/api/audit/stats")
async def audit_stats(user: dict = Depends(require_role("admin"))):
    """审计统计（仅 admin）"""
    rows = db_query(
        """SELECT action, COUNT(*) as count
           FROM audit_logs
           WHERE created_at > ?
           GROUP BY action
           ORDER BY count DESC""",
        (time.time() - 86400 * 7,), fetch="all"
    )
    return {"stats_7d": rows}


# ===== D2-01 AI 主动巡检引擎 =====
def run_inspection():
    """扫描 price_data 检测价格异常，生成消息入 message_queue。
    当前覆盖：同商品跨店/跨竞品价格异常（高于均价30%）。
    库存临期/滞销检测预留（待库存数据源接入）。"""
    rows = db_query("SELECT * FROM price_data WHERE price IS NOT NULL ORDER BY product_name, product_spec", fetch="all")
    if not rows:
        return {"scanned": 0, "alerts": 0, "note": "price_data 为空"}
    groups = {}
    for r in rows:
        key = (r["product_name"], r["product_spec"] or "")
        groups.setdefault(key, []).append(r)
    alerts = 0
    for (pname, pspec), items in groups.items():
        prices = [it["price"] for it in items if it["price"] is not None]
        if len(prices) < 2:
            continue
        avg = sum(prices) / len(prices)
        for it in items:
            if it["price"] is None:
                continue
            ratio = it["price"] / avg if avg > 0 else 1
            if ratio > 1.3:
                store_id = it["store_id"]
                level = "urgent" if ratio > 1.5 else "warning"
                pct = int((ratio - 1) * 100)
                title = f"价格异常：{pname}{(' ' + pspec) if pspec else ''} 高于同类均价{pct}%"
                body = (f"本店价 ¥{it['price']:.2f}，同类均价 ¥{avg:.2f}"
                        f"（竞品：{it.get('competitor_store') or '未知'}）。建议核查定价策略。")
                dup = db_query(
                    "SELECT id FROM message_queue WHERE store_id=? AND title=? AND is_read=0 AND related_type='price_anomaly' LIMIT 1",
                    (store_id, title), fetch="one")
                if not dup:
                    db_exec(
                        """INSERT INTO message_queue (id, store_id, level, title, body, related_type, related_id, created_at)
                           VALUES (?, ?, ?, ?, ?, 'price_anomaly', ?, ?)""",
                        (str(uuid.uuid4()), store_id, level, title, body, it["id"], time.time()))
                    alerts += 1
    return {"scanned": len(rows), "alerts": alerts}


async def scheduler_loop():
    """每小时运行一次巡检（启动后30秒首跑）"""
    await asyncio.sleep(30)
    while True:
        try:
            run_inspection()
        except Exception as e:
            print(f"[巡检调度] 异常: {e}")
        await asyncio.sleep(3600)


@app.post("/api/inspection/run")
async def trigger_inspection(user: dict = Depends(require_role("manager"))):
    """手动触发巡检（manager/admin）"""
    res = run_inspection()
    log_audit(user, "inspection_run", details=res)
    return {"ok": True, "result": res}


@app.get("/api/messages")
async def get_messages(user: dict = Depends(require_auth)):
    """消息中心：store_owner 仅本店，manager/admin 看全部"""
    if user["role"] in ("admin", "manager"):
        rows = db_query("SELECT * FROM message_queue ORDER BY created_at DESC LIMIT 100", fetch="all")
    else:
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        store_ids = [s["id"] for s in user_stores]
        if not store_ids:
            return {"messages": [], "count": 0}
        placeholders = ",".join(["?"] * len(store_ids))
        rows = db_query(
            f"SELECT * FROM message_queue WHERE store_id IN ({placeholders}) ORDER BY created_at DESC LIMIT 100",
            store_ids, fetch="all")
    return {"messages": rows, "count": len(rows)}


@app.put("/api/messages/{msg_id}/read")
async def mark_message_read(msg_id: str, user: dict = Depends(require_auth)):
    """标记单条消息已读（store_owner 仅本店消息）"""
    msg = db_query("SELECT * FROM message_queue WHERE id=?", (msg_id,), fetch="one")
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    if user["role"] == "store_owner":
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        store_ids = [s["id"] for s in user_stores]
        if msg.get("store_id") not in store_ids:
            raise HTTPException(status_code=403, detail="无权操作")
    db_exec("UPDATE message_queue SET is_read=1 WHERE id=?", (msg_id,))
    return {"ok": True}


@app.put("/api/messages/read-all")
async def mark_all_read(user: dict = Depends(require_auth)):
    """全部标记已读"""
    if user["role"] in ("admin", "manager"):
        db_exec("UPDATE message_queue SET is_read=1 WHERE is_read=0")
    else:
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        store_ids = [s["id"] for s in user_stores]
        if store_ids:
            placeholders = ",".join(["?"] * len(store_ids))
            db_exec(
                f"UPDATE message_queue SET is_read=1 WHERE is_read=0 AND store_id IN ({placeholders})",
                store_ids)
    return {"ok": True}


@app.get("/api/messages/unread-count")
async def get_unread_count(user: dict = Depends(require_auth)):
    """获取未读消息数（轻量级轮询用）"""
    if user["role"] in ("admin", "manager"):
        row = db_query("SELECT COUNT(*) as cnt FROM message_queue WHERE is_read=0", fetch="one")
    else:
        user_stores = get_user_stores(DB_PATH, user["user_id"])
        store_ids = [s["id"] for s in user_stores]
        if not store_ids:
            return {"unread": 0}
        placeholders = ",".join(["?"] * len(store_ids))
        row = db_query(
            f"SELECT COUNT(*) as cnt FROM message_queue WHERE is_read=0 AND store_id IN ({placeholders})",
            store_ids, fetch="one")
    return {"unread": row["cnt"] if row else 0}


@app.on_event("startup")
async def _startup_scheduler():
    asyncio.create_task(scheduler_loop())


# ===== 静态文件服务 (D2-07: ECharts 等前端资源) =====
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    host = config.get("server", {}).get("host", "127.0.0.1")
    port = int(config.get("server", {}).get("port", "8420"))
    url = f"http://{host}:{port}"
    print(f"鹿小仓 v0.5.1 启动中... {url}")
    uvicorn.run(app, host=host, port=port, log_level="info")
