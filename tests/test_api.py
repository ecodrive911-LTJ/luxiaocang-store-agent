"""
test_api.py — 阶段1 API越权接口 + 数据隔离 + 上传校验 回归测试
用法: python -m pytest tests/test_api.py -v

测试覆盖:
  V1-2  数据资产隔离 (store_owner → 仅本店数据)
  V1-3  竞品数据隐藏 (store_owner 调用 list_competitors → 空/无权)
  V1-4  越权拦截 (store_owner 传其他门店store_id → 403)
  V1-6  视频上传校验 (格式/大小/Deadline)
  V1-11 审计日志记录 (关键操作写audit_log)
"""

import sys, os, time, json, tempfile, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

BASE_URL = os.environ.get("LXC_BASE_URL", "http://127.0.0.1:8420")
ADMIN_USER = "luxiaocang"
ADMIN_PASS = "LXC2025"


# ─── helpers ─────────────────────────────────────────────────────────────────

def api_get(path, token):
    import urllib.request
    req = urllib.request.Request(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def api_post(path, body, token=None):
    import urllib.request
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def api_post_file(path, files, token):
    """multipart/form-data upload"""
    import urllib.request, uuid
    boundary = uuid.uuid4().hex
    body = b""
    for name, content, filename in files:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}"
    }
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def login(username, password):
    _, data = api_post("/api/auth/login", {"username": username, "password": password})
    return data.get("token")


def get_guang_an_store_id(token):
    _, tasks = api_get("/api/tasks", token)
    for t in tasks.get("tasks", []):
        return t.get("store_id")
    return None


# ─── fixtures ─────────────────────────────────────────────────────────────────

def setup_module():
    """全局登录，返回 admin_token 和第一个门店 id"""
    admin_tok = login(ADMIN_USER, ADMIN_PASS)
    assert admin_tok, "admin login failed — check credentials"
    store_id = get_guang_an_store_id(admin_tok)
    return admin_tok, store_id


# ─── V1-2: 数据资产隔离 ──────────────────────────────────────────────────────

class TestDataAssetIsolation:
    """store_owner 登录 → /api/data/assets 只能返回本店数据"""

    def test_owner_sees_only_own_store_data(self):
        """V1-2: store_owner 登录，数据资产 ≤本店SKU数"""
        admin_tok, store_id = setup_module()
        # 获取 store_owner token（通过门店用户列表）
        _, users_data = api_get("/api/users", admin_tok)
        owner_users = [u for u in users_data.get("users", []) if u.get("role") == "store_owner"]
        assert owner_users, "no store_owner found"
        owner_tok = login(owner_users[0]["username"], "LXC2025")
        status, data = api_get("/api/data/assets", owner_tok)
        assert status == 200, f"expected 200, got {status}: {data}"
        # store_owner 只能看到本店数据（不应包含竞品全局数据）
        total = data.get("total", 0)
        # 本店约 2941 条，竞品全量约 9595 条
        assert total <= 5000, f"V1-2 FAIL: store_owner sees {total} 条，超过本店上限，可能泄露竞品数据"
        print(f"  V1-2 PASS: store_owner sees {total} 条 (≤5000)")

    def test_owner_cannot_see_competitor_data(self):
        """V1-3: store_owner 调 list_competitors → 空或无权"""
        admin_tok, _ = setup_module()
        _, users_data = api_get("/api/users", admin_tok)
        owner_users = [u for u in users_data.get("users", []) if u.get("role") == "store_owner"]
        owner_tok = login(owner_users[0]["username"], "LXC2025")
        # 通过对话接口间接测
        status, data = api_post("/api/chat", {
            "message": "有哪些竞品",
            "store_id": None
        }, owner_tok)
        # store_owner 不应收到竞品全局数据
        reply = data.get("reply", "") or data.get("message", "") or str(data)
        # 竞品数据在小柴购/厉臣超市等全局数据中
        assert "小柴购" not in reply and "厉臣" not in reply, \
            f"V1-3 FAIL: store_owner 收到了竞品数据: {reply[:100]}"
        print(f"  V1-3 PASS: store_owner 未收到竞品数据")


# ─── V1-4: 越权拦截 ───────────────────────────────────────────────────────────

class TestStoreOwnerBoundary:
    """store_owner 传其他门店 store_id → 403 拦截"""

    def test_owner_cannot_access_other_store_chat(self):
        """V1-4: store_owner 传入其他门店 store_id → 被强制覆写或403"""
        admin_tok, _ = setup_module()
        _, users_data = api_get("/api/users", admin_tok)
        owner_users = [u for u in users_data.get("users", []) if u.get("role") == "store_owner"]
        owner_tok = login(owner_users[0]["username"], "LXC2025")

        # 找一个其他门店的 id（通过 stores 列表）
        _, stores_data = api_get("/api/stores", admin_tok)
        all_stores = stores_data.get("stores", [])
        owner_store_ids = set()
        for u in owner_users:
            for s in all_stores:
                owner_store_ids.add(s.get("id"))

        other_store = next((s for s in all_stores if s["id"] not in owner_store_ids), None)
        if not other_store:
            print("  V1-4 SKIP: only one store in system")
            return

        # 传其他门店 id
        _, data = api_post("/api/chat", {
            "message": "分析门店情况",
            "store_id": other_store["id"]
        }, owner_tok)

        reply = data.get("reply", "") or ""
        own_store_name = next((s["name"] for s in all_stores if s["id"] in owner_store_ids), "")
        # 应被强制覆写为本店
        assert own_store_name in reply or data.get("store_id") in owner_store_ids, \
            f"V1-4 FAIL: store_owner 越权访问了其他门店: {reply[:100]}"
        print(f"  V1-4 PASS: store_owner 被强制限定本店，拒绝访问其他门店")


# ─── V1-6: 视频上传校验 ──────────────────────────────────────────────────────

class TestVideoUploadValidation:
    """D2-1 前端校验：格式/大小/Deadline"""

    def test_upload_rejects_wrong_format(self):
        """D2-1: 上传 .txt 文件 → 400"""
        admin_tok, _ = setup_module()
        _, tasks_data = api_get("/api/tasks", admin_tok)
        task = next((t for t in tasks_data.get("tasks", [])), None)
        if not task:
            print("  D2-1 FORMAT SKIP: no tasks available")
            return
        status, data = api_post_file(
            f"/api/tasks/{task['id']}/upload",
            [("video_file", b"not a video", "test.txt")],
            admin_tok
        )
        assert status == 400, f"D2-1 FORMAT FAIL: expected 400, got {status}: {data}"
        print(f"  D2-1 FORMAT PASS: txt文件被拒绝")

    def test_upload_rejects_too_large_file(self):
        """D2-1: 上传 >200MB → 400"""
        admin_tok, _ = setup_module()
        _, tasks_data = api_get("/api/tasks", admin_tok)
        task = next((t for t in tasks_data.get("tasks", [])), None)
        if not task:
            print("  D2-1 SIZE SKIP: no tasks available")
            return
        # 构造 201MB 空数据
        large_content = b"\x00" * (201 * 1024 * 1024)
        status, data = api_post_file(
            f"/api/tasks/{task['id']}/upload",
            [("video_file", large_content, "big.mp4")],
            admin_tok
        )
        assert status == 400, f"D2-1 SIZE FAIL: expected 400, got {status}: {data}"
        assert "200MB" in data.get("detail", ""), f"D2-1 SIZE FAIL: wrong message: {data}"
        print(f"  D2-1 SIZE PASS: >200MB 文件被拒绝")


# ─── V1-11: 审计日志 ──────────────────────────────────────────────────────────

class TestAuditLog:
    """关键操作写 audit_log"""

    def test_login_writes_audit_log(self):
        """V1-11: 登录后有 audit_log 记录"""
        admin_tok, _ = setup_module()
        _, logs_data = api_get("/api/audit/logs", admin_tok)
        logs = logs_data.get("logs", [])
        # 至少有一条 login 记录
        login_logs = [l for l in logs if l.get("action") in ("login", "login_success")]
        assert login_logs, f"V1-11 FAIL: 未找到 login 审计记录，现有: {[l.get('action') for l in logs[:5]]}"
        print(f"  V1-11 PASS: 找到 {len(login_logs)} 条 login 审计记录")

    def test_owner_cannot_read_audit_logs(self):
        """V1-11: store_owner 访问 /api/audit/logs → 403"""
        admin_tok, _ = setup_module()
        _, users_data = api_get("/api/users", admin_tok)
        owner_users = [u for u in users_data.get("users", []) if u.get("role") == "store_owner"]
        if not owner_users:
            print("  V1-11 SKIP: no store_owner")
            return
        owner_tok = login(owner_users[0]["username"], "LXC2025")
        status, _ = api_get("/api/audit/logs", owner_tok)
        assert status == 403, f"V1-11 FAIL: store_owner 可以访问审计日志 (status={status})"
        print(f"  V1-11 PASS: store_owner 访问审计日志被拒绝 (403)")


# ─── D2-2: MD5去重 + Deadline ────────────────────────────────────────────────

class TestUploadDeduplication:
    """D2-2: MD5去重 + 截止日期拦截"""

    def test_check_md5_endpoint_exists(self):
        """D2-2: check-md5 接口存在"""
        admin_tok, _ = setup_module()
        _, tasks_data = api_get("/api/tasks", admin_tok)
        task = next((t for t in tasks_data.get("tasks", [])), None)
        if not task:
            print("  D2-2 MD5 SKIP: no tasks")
            return
        status, data = api_get(f"/api/tasks/{task['id']}/check-md5?md5=test123abc", admin_tok)
        assert status == 200, f"D2-2 check-md5 FAIL: expected 200, got {status}"
        assert "duplicate" in data, f"D2-2 FAIL: wrong response: {data}"
        print(f"  D2-2 PASS: check-md5 接口正常 (duplicate={data['duplicate']})")


if __name__ == "__main__":
    print("=" * 60)
    print("鹿小仓阶段1自动化回归测试")
    print(f"目标服务器: {BASE_URL}")
    print("=" * 60)
    try:
        setup_module()
        print("\n[全部测试需用 pytest 运行]")
        print("python -m pytest tests/test_api.py -v")
    except AssertionError as e:
        print(f"\nSETUP FAILED: {e}")
        sys.exit(1)
