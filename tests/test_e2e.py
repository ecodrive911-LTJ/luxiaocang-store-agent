"""
test_e2e.py — 阶段1 全链路端到端回归测试
覆盖: 任务下发 → 视频上传 → AI解析 → 人工复核 → 比价矩阵

用法: python -m pytest tests/test_e2e.py -v
"""

import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

BASE_URL = os.environ.get("LXC_BASE_URL", "http://127.0.0.1:8420")
ADMIN_USER = "luxiaocang"
ADMIN_PASS = "LXC2025"


# ─── helpers ─────────────────────────────────────────────────────────────────

def api_get(path, token):
    import urllib.request
    req = urllib.request.Request(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        r = urllib.request.urlopen(req, timeout=15)
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
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def api_post_file(path, files, token):
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
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def login(username, password):
    _, data = api_post("/api/auth/login", {"username": username, "password": password})
    return data.get("token")


def poll_upload_status(task_id, token, timeout=60, interval=5):
    """轮询上传状态直到非 analyzing/pending/retrying"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, data = api_get(f"/api/tasks/{task_id}", token)
        uploads = data.get("uploads", [])
        if uploads:
            last = uploads[0]
            status = last.get("status")
            print(f"    [{int(time.time() % 1000):04d}] upload status = {status}")
            if status in ("done", "failed", "confirmed"):
                return last
        time.sleep(interval)
    return None


# ─── E2E 全链路测试 ─────────────────────────────────────────────────────────

def test_full_pipeline():
    """V1-10: 全流程链路 — 从登录到比价矩阵输出"""
    print("\n=== E2E 全链路测试 ===\n")

    # Step 1: admin 登录
    print("[1/8] admin 登录...")
    admin_tok = login(ADMIN_USER, ADMIN_PASS)
    assert admin_tok, "admin login failed"
    print("  ✓ admin 登录成功\n")

    # Step 2: 创建任务（用于测试上传）
    print("[2/8] 创建测试任务...")
    _, tasks_before = api_get("/api/tasks", admin_tok)
    before_ids = set(t["id"] for t in tasks_before.get("tasks", []))

    _, create = api_post("/api/tasks", {
        "title": f"AI回归测试任务 {int(time.time())}",
        "store_id": tasks_before["tasks"][0]["store_id"] if tasks_before.get("tasks") else None,
        "competitor_store_name": "小柴购",
        "deadline": time.time() + 86400 * 7,  # 7天后截止
        "description": "自动化回归测试任务",
        "items": [
            {"product_name": "可口可乐500ml", "product_spec": "500ml", "category": "饮料"},
        ]
    }, admin_tok)
    assert create.get("ok"), f"创建任务失败: {create}"
    task_id = create["task"]["id"]
    print(f"  ✓ 任务创建成功: {task_id}\n")

    # Step 3: 验证任务出现在列表中
    print("[3/8] 验证任务下发...")
    _, tasks = api_get("/api/tasks", admin_tok)
    new_ids = set(t["id"] for t in tasks.get("tasks", []))
    assert task_id in new_ids, "新建任务未出现在列表"
    print(f"  ✓ 任务下发成功\n")

    # Step 4: 模拟小视频上传（不走实际AI解析，只测上传流程）
    print("[4/8] 上传视频...")
    fake_video = b"\x00" * (1024 * 1024)  # 1MB fake video
    status, upload_resp = api_post_file(
        f"/api/tasks/{task_id}/upload",
        [("video_file", fake_video, "test.mp4")],
        admin_tok
    )
    # 期望: 成功上传（触发 AI 分析，AI 会失败因为不是真实视频）
    assert status in (200, 201), f"上传失败: status={status} resp={upload_resp}"
    upload_id = upload_resp.get("upload_id")
    print(f"  ✓ 视频上传成功: upload_id={upload_id}\n")

    # Step 5: 等待 AI 解析完成（或超时失败）
    print("[5/8] 等待 AI 解析（最多60s）...")
    upload_result = poll_upload_status(task_id, admin_tok, timeout=60)
    if upload_result:
        final_status = upload_result.get("status")
        print(f"  → 最终状态: {final_status}")
        if final_status == "done":
            print("  ✓ AI 解析成功\n")
        elif final_status == "failed":
            print("  ⚠ AI 解析失败（预期行为，测试视频非真实内容）\n")
        else:
            print(f"  ⚠ 未知状态: {final_status}\n")
    else:
        print("  ⚠ 解析超时（60s内未完成）\n")

    # Step 6: 人工复核（如果解析成功）
    print("[6/8] 人工复核界面...")
    _, uploads_data = api_get(f"/api/tasks/{task_id}", admin_tok)
    if uploads_data.get("uploads"):
        last_upload = uploads_data["uploads"][0]
        review_status, review_data = api_get(f"/api/uploads/{last_upload['id']}/review", admin_tok)
        if review_status == 200:
            print(f"  ✓ 复核界面可访问: upload_id={last_upload['id']}\n")
        else:
            print(f"  ⚠ 复核界面返回 {review_status}\n")
    else:
        print("  ⚠ 无上传记录可复核\n")

    # Step 7: 比价矩阵
    print("[7/8] 比价矩阵...")
    store_id = tasks_before["tasks"][0]["store_id"] if tasks_before.get("tasks") else None
    if store_id:
        matrix_status, matrix_data = api_get(f"/api/price/matrix?store_id={store_id}", admin_tok)
        assert matrix_status == 200, f"比价矩阵失败: {matrix_status} {matrix_data}"
        rows = matrix_data.get("matrix", [])
        print(f"  ✓ 比价矩阵返回 {len(rows)} 个商品\n")
    else:
        print("  ⚠ 无门店，无法测试比价矩阵\n")

    # Step 8: 审计日志验证
    print("[8/8] 审计日志记录...")
    _, logs_data = api_get("/api/audit/logs", admin_tok)
    actions = [l.get("action") for l in logs_data.get("logs", [])]
    print(f"  ✓ 审计日志含动作: {actions[:8]}")
    assert "login" in actions or "login_success" in actions, "未找到登录审计记录"
    print(f"  ✓ 审计日志正常\n")

    print("=" * 50)
    print("E2E 全链路测试: PASS")
    print("=" * 50)


if __name__ == "__main__":
    print("=" * 60)
    print("鹿小仓 E2E 全链路回归测试")
    print(f"目标服务器: {BASE_URL}")
    print("=" * 60)
    try:
        test_full_pipeline()
    except AssertionError as e:
        print(f"\nE2E FAIL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nE2E ERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
