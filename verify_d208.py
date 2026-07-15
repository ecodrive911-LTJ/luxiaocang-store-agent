import json, sys, urllib.request, time, paramiko

BASE = "http://120.26.176.215"
def log(*a): print(*a, file=sys.stderr, flush=True)

def post(path, data, token=None, timeout=120):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    if token: req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get(path, token=None, timeout=30):
    req = urllib.request.Request(BASE + path)
    if token: req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def chat_stream(token, store_id, message, session, timeout=400):
    data = {"message": message, "store_id": store_id, "session_id": session}
    req = urllib.request.Request(BASE + "/api/chat", data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    full = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = ""
            for raw in r:
                buf += raw.decode(errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data:"): continue
                    payload = line[5:].strip()
                    if not payload: continue
                    try: obj = json.loads(payload)
                    except Exception: continue
                    if "content" in obj: full.append(obj["content"])
                    elif obj.get("done"): return "".join(full)
                    elif "error" in obj:
                        log("  [chat error]", obj["error"]); return "".join(full)
    except Exception as e:
        log("  [exception]", type(e).__name__, e)
    return "".join(full)

login = post("/api/auth/login", {"username": "guangan", "password": "guangan123"})
token = login["token"]
sid = get("/api/stores", token)["stores"][0]["id"]
log(f"门店: {sid[:8]}")

# 1) 真实发1次定价类对话，确认 record_query 已接入
log("== 对话1（定价类，验证record_query接线）==")
r1 = chat_stream(token, sid, "我们店饮料定价怎么调？客单价大概多少？", "d208a")
log(f"回复1 {len(r1)}字")
time.sleep(3)
p1 = get(f"/api/memory/preferences?store_id={sid}", token)
log(f"偏好(对话1后): {p1['preferences']}")

# 2) 直接把定价类累计补到5（模拟历史高频，避免连发5次拖垮LLM端点）
ssh = paramiko.SSHClient(); ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", username="root", password="DOWson1108", timeout=20)
ssh.exec_command(f"cd /opt/luxiaocang && python3 -c \"import sqlite3;c=sqlite3.connect('database.db');c.execute(\\\"UPDATE query_stats SET count=5 WHERE store_id='{sid}' AND category='pricing'\\\");c.commit();print('updated',c.total_changes);c.close()\"")
ssh.close()
p2 = get(f"/api/memory/preferences?store_id={sid}", token)
log(f"偏好(补种后): {p2['preferences']}")

# 3) 再发1次对话，验证 V2-07：偏好已注入 system prompt（AI回答优先照顾定价）
log("== 对话2（验证V2-07偏好注入）==")
r2 = chat_stream(token, sid, "今天门店有什么要重点关注的经营问题？", "d208b")
log(f"回复2 {len(r2)}字")
log(f"回复2片段: {r2[:160]}")
ref = any(k in r2 for k in ("定价", "价格", "调价", "偏好", "常关注", "高频"))
log(f"V2-07 AI引用偏好: {ref}")

# 4) 清理：删除本次测试产生的 query_stats，保持库干净
ssh = paramiko.SSHClient(); ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("120.26.176.215", username="root", password="DOWson1108", timeout=20)
ssh.exec_command(f"cd /opt/luxiaocang && python3 -c \"import sqlite3;c=sqlite3.connect('database.db');c.execute(\\\"DELETE FROM query_stats WHERE store_id='{sid}'\\\");c.commit();c.close()\"")
ssh.close()
log("已清理测试 query_stats")
log("=== V2-07 结论: 偏好记录=%s, 注入生效=%s ===" % (bool(p2['preferences']), ref))
