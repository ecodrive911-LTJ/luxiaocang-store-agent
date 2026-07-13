# -*- coding: utf-8 -*-
import httpx
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("=== 聊天测试 ===")
full = ""
try:
    with httpx.stream("POST", "http://120.26.176.215/api/chat",
        json={"message": "你好", "session_id": "debug"},
        timeout=60) as resp:
        print(f"HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if line and line.startswith("data: "):
                data = line[6:]
                try:
                    obj = json.loads(data)
                    if "content" in obj:
                        full += obj["content"]
                        print(obj["content"], end="", flush=True)
                    elif "done" in obj:
                        print("\n\n[DONE]")
                    elif "error" in obj:
                        err = obj.get("error", "")
                        print(f"\n[ERROR] {err}")
                except:
                    pass
    print(f"\n\nFull reply length: {len(full)}")
except Exception as e:
    print(f"请求失败: {e}")
