"""
鹿小仓 认证与权限模块
- 密码哈希（bcrypt）
- Session Token 生成与验证
- FastAPI 鉴权中间件
"""

import secrets
import time
import sqlite3
import hashlib
import hmac
from pathlib import Path
from typing import Optional

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

DB_PATH = Path(__file__).parent / "database.db"
SESSION_TTL = 7 * 24 * 3600  # 7天


def hash_password(password: str) -> str:
    """哈希密码"""
    if HAS_BCRYPT:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    else:
        # 降级方案：SHA256 + 随机盐
        salt = secrets.token_hex(16)
        h = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return f"sha256${salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    """验证密码"""
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


def generate_token() -> str:
    """生成 session token"""
    return secrets.token_urlsafe(32)


def create_session(db_path: Path, user_id: str) -> str:
    """创建会话，返回 token"""
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
    """验证 session token，返回用户信息或 None"""
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
    """注销会话"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def get_user_stores(db_path: Path, user_id: str) -> list:
    """获取用户可访问的门店列表"""
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
    """获取门店信息（验证用户权限）"""
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


def extract_token(request) -> Optional[str]:
    """从请求头提取 token"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
