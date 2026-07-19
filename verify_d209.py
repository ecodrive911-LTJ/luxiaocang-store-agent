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
    done = False
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
                    elif obj.get("done"): done = True; break
                    elif "error" in obj:
                        log("  [chat error]", obj["error"]); done = True; break
    except Exception as e:
        log("  [chat_stream exception]", type(e).__name__, e)
    return "".join(full), done

login = post("/api/auth/login", {"username": "guangan", "password": "guangan123"})
token = login["token"]
stores = get("/api/stores", token)
sid = stores["stores"][0]["id"]
log(f"门店: {stores['stores'][0]['name']} ({sid[:8]})")

# V2-09: 发诊断/定价类对话，触发 LLM 写回
log("== 发送诊断对话（触发记忆写回）==")
t0 = time.time()
reply, done = chat_stream(token, sid, "我们店客单价大概多少？主力客群是谁？饮料和零食定价有什么要注意的？", "diag1")
log(f"回复{len(reply)}字, done={done}, 用时{time.time()-t0:.1f}s")

# 轮询等待 detached 持久化任务落库
log("== 轮询 /api/memory/summary 等待落库 ==")
saved_profile = saved_memory = -1
for i in range(28):  # 最多等 280s（提取本身可能耗时~90s）
    time.sleep(10)
    s = get(f"/api/memory/summary?store_id={sid}", token)
    pc, mc = s.get("profile_count", 0), s.get("memory_count", 0)
    log(f"  t+{(i+1)*10}s profile={pc} memory={mc}")
    if pc > 0 or mc > 0:
        saved_profile, saved_memory = pc, mc
        break

# V2-08: 第二次对话，验证画像已注入 system prompt（通过服务端 [D2-09] 召回日志确认）
log("== 第二次对话（验证画像召回注入）==")
reply2, done2 = chat_stream(token, sid, "上次的定价建议还适用吗？结合我们店情况再说一下。", "diag2")
log(f"回复2 {len(reply2)}字, done={done2}")

# 拉服务端 D2-09 日志
log("--- 服务端最近 D2-09 日志 ---")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("120.26.176.215", username="root", password="DOWson1108", timeout=20)
    _, stdout, _ = ssh.exec_command("journalctl -u luxiaocang.service --since '5 min ago' --no-pager | grep D2-09 | tail -20")
    print(stdout.read().decode(), file=sys.stderr, flush=True)
    ssh.close()
except Exception as e:
    log("  [ssh log fetch failed]", e)

log(f"=== 结论: V2-09写回 profile={saved_profile} memory={saved_memory} ===")
