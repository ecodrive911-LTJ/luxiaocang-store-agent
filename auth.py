"""
鹿小仓 认证与权限模块 v0.4.1
- 密码哈希（bcrypt）
- Session Token 生成与验证
- FastAPI 鉴权中间件
- RBAC 角色权限控制（admin > owner > staff）
"""

import secrets
import time
import sqlite3
import hashlib
import hmac
from pathlib import Path
from typing import Optional, Callable
from fastapi import Request, HTTPException

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

DB_PATH = Path(__file__).parent / "database.db"
SESSION_TTL = 7 * 24 * 3600  # 7天

# ===== 角色权限定义 =====
ROLES = {
    "admin": {
        "level": 100,
        "label": "系统管理员",
        "permissions": ["*"],  # 所有权限
    },
    "owner": {
        "level": 50,
        "label": "店主",
        "permissions": [
            "chat", "view_data", "view_stores", "manage_stores",
            "view_config", "edit_config", "register_user",
        ],
    },
    "staff": {
        "level": 10,
        "label": "店员",
        "permissions": [
            "chat", "view_data", "view_stores",
        ],
    },
}

def get_role_level(role: str) -> int:
    return ROLES.get(role, {}).get("level", 0)

def has_permission(user_role: str, permission: str) -> bool:
    perms = ROLES.get(user_role, {}).get("permissions", [])
    if "*" in perms:
        return True
    return permission in perms

def require_role(min_role: str):
    """FastAPI 依赖工厂：要求最低角色级别"""
    min_level = get_role_level(min_role)

    async def role_checker(request: Request):
        token = extract_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = verify_session(DB_PATH, token)
        if not user:
            raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
        user_level = get_role_level(user["role"])
        if user_level < min_level:
            raise HTTPException(status_code=403, detail=f"权限不足，需要{ROLES[min_role]['label']}或更高权限")
        return user

    return role_checker

def require_permission(permission: str):
    """FastAPI 依赖工厂：要求特定权限"""
    async def perm_checker(request: Request):
        token = extract_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = verify_session(DB_PATH, token)
        if not user:
            raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
        if not has_permission(user["role"], permission):
            raise HTTPException(status_code=403, detail=f"权限不足：需要 {permission} 权限")
        return user

    return perm_checker


# ===== 密码处理 =====
def hash_password(password: str) -> str:
    if HAS_BCRYPT:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    else:
        salt = secrets.token_hex(16)
        h = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return f"sha256${salt}${h}"

def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$2b$") and HAS_BCRYPT:
        return bcrypt.checkpw(password.encode('utf-8'), stored.encode('utf-8'))
    elif stored.startswith("sha256$"):
        parts = stored.split("$", 2)
        if len(parts) != 3:
            return False
        salt, expected_hash = parts[1], parts[2]
        h = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return hmac.compare_digest(h, expected_hash)
    return False


# ===== Session =====
def generate_token() -> str:
    return secrets.token_urlsafe(32)

def create_session(db_path: Path, user_id: str) -> str:
    token = generate_token()
    now = time.time()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now, now + SESSION_TTL)
    )
    conn.commit()
    conn.close()
    return token

def verify_session(db_path: Path, token: str) -> Optional[dict]:
    if not token:
        return None
    now = time.time()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT s.user_id, s.expires_at, u.username, u.display_name, u.role
           FROM sessions s
           JOIN users u ON s.user_id = u.id
           WHERE s.token = ?""",
        (token,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    if now > row["expires_at"]:
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }

def invalidate_session(db_path: Path, token: str):
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# ===== 门店权限 =====
def get_user_stores(db_path: Path, user_id: str) -> list:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT s.id, s.name, s.address, s.city, s.district, us.role as user_role
           FROM stores s
           JOIN user_stores us ON s.id = us.store_id
           WHERE us.user_id = ?
           ORDER BY s.name""",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_store_by_id(db_path: Path, store_id: str, user_id: str) -> Optional[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT s.*, us.role as user_role
           FROM stores s
           JOIN user_stores us ON s.id = us.store_id
           WHERE s.id = ? AND us.user_id = ?""",
        (store_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ===== 工具函数 =====
def extract_token(request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
