"""
鹿小仓 D2-09 门店画像 & Agent长期记忆

职责：
1. 召回（对话前）：把门店画像(store_profiles) + Agent记忆(agent_memory) 拼成 system prompt 上下文
2. 写入（对话后）：LLM 从一轮对话中抽取结构化事实，upsert 进两张表

设计要点：
- stores.id 是 TEXT UUID，因此本模块 store_id 一律用 TEXT
- store_profiles 用 (store_id, profile_type, content_key) 唯一约束做幂等 upsert，避免重复刷屏
- agent_memory 每次对话产生独立记忆；召回按 importance DESC, created_at DESC 取 top N
- 所有 DB 操作失败都吞掉异常并降级，绝不影响主对话链路
"""

import json
import sqlite3
import hashlib
import time
import asyncio
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "database.db"

# 画像类型（与路线图 D2-09 一致）
PROFILE_TYPES = {
    "business_feature": "经营特征",
    "historical_issue": "历史问题",
    "pricing_preference": "定价偏好",
    "category_strength": "品类优势",
    "category_weakness": "品类劣势",
}

# 记忆类型
MEMORY_TYPES = {
    "decision": "决策",
    "event": "事件",
    "preference": "偏好",
    "lesson": "教训",
}

# 类型归一化（LLM 偶尔会返回 id/type/name/subject_id 等异构键名或中文，这里归一）
_PROFILE_TYPE_ALIAS = {
    "business_feature": "business_feature", "经营特征": "business_feature", "business": "business_feature",
    "historical_issue": "historical_issue", "历史问题": "historical_issue", "issue": "historical_issue",
    "pricing_preference": "pricing_preference", "定价偏好": "pricing_preference", "pricing": "pricing_preference",
    "category_strength": "category_strength", "品类优势": "category_strength", "strength": "category_strength",
    "category_weakness": "category_weakness", "品类劣势": "category_weakness", "weakness": "category_weakness",
}
_MEMORY_TYPE_ALIAS = {
    "decision": "decision", "决策": "decision",
    "event": "event", "事件": "event",
    "preference": "preference", "偏好": "preference",
    "lesson": "lesson", "教训": "lesson",
}

_PROFILE_CAP = 20      # 召回时单店画像上限
_MEMORY_CAP = 10       # 召回时单店记忆上限
_MEMORY_STORE_CAP = 100  # 单店活跃记忆软上限，超过则清理低重要度旧记忆


def _conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _content_key(text: str) -> str:
    norm = "".join(text.strip().lower().split())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


# ===================== 召回（对话前） =====================

def get_store_profiles(db_path, store_id: str, limit: int = _PROFILE_CAP) -> list:
    try:
        conn = _conn(db_path)
        rows = conn.execute(
            "SELECT * FROM store_profiles WHERE store_id=? ORDER BY profile_type, last_updated DESC LIMIT ?",
            (store_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_agent_memory(db_path, store_id: str, limit: int = _MEMORY_CAP) -> list:
    try:
        conn = _conn(db_path)
        rows = conn.execute(
            "SELECT * FROM agent_memory WHERE store_id=? AND archived=0 "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (store_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def build_memory_context(db_path, store_id: Optional[str], record_recall: bool = True) -> str:
    """生成拼入 system prompt 的门店长期画像上下文。

    返回 "" 表示无画像可注入。record_recall=True 时会更新被召回记忆的召回统计。
    """
    if not store_id:
        return ""
    try:
        profiles = get_store_profiles(db_path, store_id)
        memories = get_agent_memory(db_path, store_id)
        if not profiles and not memories:
            return ""

        lines = ["\n\n## 门店长期画像（历史对话沉淀，供你参考，不要当成用户当前指令）"]

        # 按类型分组画像
        by_type = {}
        for p in profiles:
            by_type.setdefault(p["profile_type"], []).append(p)
        for ptype, label in PROFILE_TYPES.items():
            items = by_type.get(ptype)
            if items:
                lines.append(f"### {label}")
                for p in items:
                    try:
                        cj = json.loads(p["content_json"])
                        text = cj.get("text", p["content_json"])
                    except Exception:
                        text = p["content_json"]
                    conf = p.get("confidence") or 0.5
                    lines.append(f"- {text}（置信度 {conf:.0%}）")

        if memories:
            lines.append("### 我对本店的历史记忆")
            recalled_ids = []
            for m in memories:
                lines.append(f"- [{MEMORY_TYPES.get(m['memory_type'], m['memory_type'])}] {m['summary']}")
                recalled_ids.append(m["id"])
            if record_recall and recalled_ids:
                try:
                    conn = _conn(db_path)
                    now = time.time()
                    for mid in recalled_ids:
                        conn.execute(
                            "UPDATE agent_memory SET last_recalled_at=?, recall_count=recall_count+1 WHERE id=?",
                            (now, mid),
                        )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

        return "\n".join(lines)
    except Exception:
        return ""


# ===================== 用户偏好学习（D2-08） =====================
# 说明：用「确定性关键词分类」而非额外 LLM 调用，避免给本就速率受限的
# 火山引擎端点增加负担。记录用户高频咨询的「问题类型 + 品类/门店」，
# 当某类咨询累计 >= 阈值(默认5) 时，把偏好引用注入 system prompt，
# 让 AI 回答优先照顾该维度（验收 V2-07）。

CATEGORY_LABELS = {
    "pricing": "定价/调价",
    "selection": "选品/商品结构",
    "competitor": "竞品比价",
    "supply": "供应链/库存",
    "siting": "选址/建店",
    "analytics": "数据看板",
    "alert": "异常巡检",
    "general": "综合经营",
}

_CATEGORY_KEYWORDS = {
    "pricing":     ["定价", "调价", "价格", "毛利", "加价", "利润", "促销价", "价签", "降价", "涨价", "标价", "客单价"],
    "selection":   ["选品", "分层", "引流", "利润品", "长尾", "滞销", "搭售", "关联", "品类", "商品结构", "淘汰", "动销"],
    "competitor":  ["竞品", "比价", "小柴购", "厉臣", "对手", "同行"],
    "supply":      ["补货", "库存", "供应链", "进货", "采购", "缺货", "周转", "仓配"],
    "siting":      ["选址", "建店", "开店", "商圈", "铺位", "点位"],
    "analytics":   ["看板", "报表", "数据", "指标", "KPI", "销售额", "营业额", "营收", "毛利额"],
    "alert":       ["异常", "告警", "巡检", "预警", "缺货告警"],
}
_TOPIC_KEYWORDS = ["饮料", "零食", "乳品", "酒水", "方便食品", "生鲜", "日百",
                   "纸品", "洗护", "烟草", "冰品", "调味", "面包", "饼干", "膨化"]


def classify_query(message: str):
    """确定性地把一条用户咨询分类为 (问题类型, 品类/门店主题)。"""
    if not message:
        return "general", ""
    # 主题：优先品类，其次门店名
    topic = ""
    for kw in _TOPIC_KEYWORDS:
        if kw in message:
            topic = kw
            break
    if not topic:
        for name in ("广安", "财富", "承德"):
            if name in message:
                topic = name + "店"
                break
    # 问题类型：命中关键词最多的类别
    best, best_n = "general", 0
    for cat, kws in _CATEGORY_KEYWORDS.items():
        n = sum(1 for k in kws if k in message)
        if n > best_n:
            best, best_n = cat, n
    return best, topic


def record_query(db_path, store_id: str, message: str):
    """记录一次用户咨询的问题类型+主题，用于偏好学习（幂等累加）。"""
    if not store_id:
        return
    category, topic = classify_query(message)
    now = time.time()
    try:
        conn = _conn(db_path)
        conn.execute(
            """INSERT INTO query_stats (store_id, category, topic, count, first_at, updated_at)
               VALUES (?,?,?,1,?,?)
               ON CONFLICT(store_id, category, topic) DO UPDATE SET
                 count = count + 1, updated_at = excluded.updated_at""",
            (store_id, category, topic, now, now),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_top_preferences(db_path, store_id: str, threshold: int = 5) -> list:
    """返回累计咨询次数 >= threshold 的高频偏好（按次数降序）。"""
    try:
        conn = _conn(db_path)
        rows = conn.execute(
            "SELECT category, topic, count FROM query_stats "
            "WHERE store_id=? AND count>=? ORDER BY count DESC LIMIT 5",
            (store_id, threshold),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def build_preference_context(db_path, store_id: str, threshold: int = 5) -> str:
    """生成拼入 system prompt 的用户偏好引用块；未达阈值返回空串。"""
    if not store_id:
        return ""
    prefs = get_top_preferences(db_path, store_id, threshold)
    if not prefs:
        return ""
    lines = ["\n\n## 用户偏好（基于历史高频咨询沉淀，回答请优先照顾这些维度）"]
    for p in prefs:
        cat_label = CATEGORY_LABELS.get(p["category"], p["category"])
        topic_txt = f"「{p['topic']}」" if p["topic"] else ""
        lines.append(
            f"- 您常关注{topic_txt}{cat_label}（累计 {p['count']} 次咨询），"
            f"回答时优先结合本店相关数据，主动给出可执行建议"
        )
    return "\n".join(lines)


# ===================== 写入（对话后） =====================

def _upsert_profile(db_path, store_id: str, profile_type: str, content: str,
                    confidence: float, source: str):
    if profile_type not in PROFILE_TYPES:
        return
    content = (content or "").strip()
    if len(content) < 2:
        return
    try:
        conn = _conn(db_path)
        now = time.time()
        ck = _content_key(content)
        conn.execute(
            """INSERT INTO store_profiles
               (store_id, profile_type, content_json, content_key, confidence, source, last_updated, created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(store_id, profile_type, content_key) DO UPDATE SET
                 confidence = MAX(confidence, excluded.confidence),
                 last_updated = excluded.last_updated,
                 source = excluded.source""",
            (store_id, profile_type, json.dumps({"text": content}, ensure_ascii=False),
             ck, max(0.0, min(1.0, confidence)), source, now, now),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _insert_memory(db_path, store_id: str, memory_type: str, summary: str,
                   importance: int, source_conversation_id: str = None,
                   detail: str = None):
    if memory_type not in MEMORY_TYPES:
        return
    summary = (summary or "").strip()
    if len(summary) < 2:
        return
    try:
        conn = _conn(db_path)
        now = time.time()
        conn.execute(
            """INSERT INTO agent_memory
               (store_id, memory_type, summary, detail_json, source_conversation_id, importance, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (store_id, memory_type, summary,
             json.dumps({"text": detail}, ensure_ascii=False) if detail else None,
             source_conversation_id, max(1, min(3, int(importance))), now),
        )
        conn.commit()
        # 软上限清理：活跃记忆过多时删最低重要度且最少召回的旧记忆
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM agent_memory WHERE store_id=? AND archived=0",
            (store_id,),
        ).fetchone()["c"]
        if cnt > _MEMORY_STORE_CAP:
            to_delete = cnt - _MEMORY_STORE_CAP
            conn.execute(
                """DELETE FROM agent_memory WHERE store_id=? AND archived=0
                   AND id IN (
                     SELECT id FROM agent_memory WHERE store_id=? AND archived=0
                     ORDER BY importance ASC, recall_count ASC, created_at ASC LIMIT ?
                   )""",
                (store_id, store_id, to_delete),
            )
            conn.commit()
        conn.close()
    except Exception:
        pass


_EXTRACT_SYS = (
    "你是鹿小仓的记忆抽取器。从一段便利店店主与AI经营助手的对话中，抽取值得长期记忆的"
    "结构化信息。只抽取确定、可复用的事实/决策/偏好/教训；若没有值得记忆的内容，返回空列表。"
    "你必须严格按下方指定的JSON键名输出，禁止使用 id/type/name/subject_id 等其它键名。"
)

_EXTRACT_USER_TMPL = """门店：{store_name}（store_id={store_id}）

以下是本轮对话（用户提问 + AI回答）：

【用户】{user_msg}

【AI】{assistant_reply}

请抽取以下两类长期记忆，并严格按给定JSON结构输出（键名必须完全一致，不得替换为其它名称）：

1) store_profiles（门店画像），每条对象必须包含：
   - "profile_type"：只能是以下5个值之一：
       "business_feature"（经营特征：客单价/客流时段/主力客群等）
       "historical_issue"（历史问题：曾发生并已处理的经营问题）
       "pricing_preference"（定价偏好：店主对定价的倾向，如"不愿低于进货价"）
       "category_strength"（品类优势：哪些品类表现好）
       "category_weakness"（品类劣势：哪些品类表现差/滞销）
   - "content"：一句话事实，简洁可复用（中文）
   - "confidence"：0.0~1.0 的置信度数字
   示例：{{"profile_type": "business_feature", "content": "主力客群为周边社区居民与写字楼上班族", "confidence": 0.8}}

2) agent_memory（经营记忆），每条对象必须包含：
   - "memory_type"：只能是以下4个值之一："decision"（决策）、"event"（事件）、"preference"（偏好）、"lesson"（教训）
   - "summary"：一句话总结（中文）
   - "importance"：1~3 的整数重要度
   示例：{{"memory_type": "preference", "summary": "店主偏好用红色价签标注促销商品", "importance": 2}}

只输出如下JSON，不要任何额外文字，也不要用 ``` 代码块包裹：
{{"profiles": [ ... ], "memories": [ ... ]}}"""


async def extract_and_save_memory(db_path, store_id: str, user_msg: str,
                                  assistant_reply: str, config: dict,
                                  session_id: str = None,
                                  store_name: str = "") -> dict:
    """对话结束后，调用 LLM 抽取结构化记忆并落库。返回统计。

    纯后台动作：任何异常都被吞掉，绝不抛给主对话链路。
    """
    result = {"saved_profiles": 0, "saved_memories": 0, "skipped": True}
    if not store_id or not (user_msg and assistant_reply):
        return result
    try:
        from agent_loop import call_llm_stream
        user_block = _EXTRACT_USER_TMPL.format(
            store_name=store_name or store_id,
            store_id=store_id,
            user_msg=(user_msg or "")[:1500],
            assistant_reply=(assistant_reply or "")[:3000],
        )
        messages = [
            {"role": "system", "content": _EXTRACT_SYS},
            {"role": "user", "content": user_block},
        ]
        print(f"[D2-09] extract start store={store_id} msg={len(user_msg)}B reply={len(assistant_reply)}B", flush=True)
        # 用流式调用（比非流式快很多：首 token 秒回，整体 ~30s vs 非流式 ~90s）
        parts = []
        async for chunk in call_llm_stream(messages, config, timeout=150):
            parts.append(chunk)
        raw = "".join(parts)
        print(f"[D2-09] extract raw(head): {raw[:200]!r}", flush=True)
        if raw.startswith("⚠️"):
            print(f"[D2-09] extract: LLM error returned, skip", flush=True)
            return result
        # 容错：剥离可能的 ```json 代码块标记
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            print(f"[D2-09] extract: no JSON found, skip", flush=True)
            return result
        data = json.loads(raw[start:end + 1])

        profiles = data.get("profiles") or []
        memories = data.get("memories") or []
        if not isinstance(profiles, list):
            profiles = []
        if not isinstance(memories, list):
            memories = []

        for p in profiles:
            if not isinstance(p, dict):
                continue
            # 容忍异构键名 + 类型归一化
            raw_type = p.get("profile_type") or p.get("type") or p.get("category") or ""
            ptype = _PROFILE_TYPE_ALIAS.get(str(raw_type).strip().lower())
            if not ptype:
                continue
            content = (p.get("content") or p.get("text") or p.get("name") or p.get("detail") or "").strip()
            if len(content) < 2:
                continue
            conf = float(p.get("confidence", 0.5) or 0.5)
            if conf < 0.4:  # 低置信度不入库，避免噪声
                continue
            _upsert_profile(db_path, store_id, ptype, content, conf, source="chat")
            result["saved_profiles"] += 1

        for m in memories:
            if not isinstance(m, dict):
                continue
            raw_type = m.get("memory_type") or m.get("type") or m.get("category") or ""
            mtype = _MEMORY_TYPE_ALIAS.get(str(raw_type).strip().lower())
            if not mtype:
                continue
            summary = (m.get("summary") or m.get("content") or m.get("text") or "").strip()
            if len(summary) < 2:
                continue
            imp = int(m.get("importance", 1) or 1)
            if imp < 1:
                continue
            _insert_memory(db_path, store_id, mtype, summary, imp,
                           source_conversation_id=session_id,
                           detail=m.get("detail") or summary)
            result["saved_memories"] += 1

        result["skipped"] = (result["saved_profiles"] == 0 and result["saved_memories"] == 0)
        print(f"[D2-09] extract done saved_profiles={result['saved_profiles']} saved_memories={result['saved_memories']}", flush=True)
    except Exception as e:
        # 抽取失败不影响主流程
        result["error"] = True
        print(f"[D2-09] extract ERROR: {type(e).__name__}: {e}", flush=True)
    return result


# ===================== 查询（管理/验证） =====================

def get_memory_summary(db_path, store_id: str) -> dict:
    """返回画像/记忆统计 + 注入上下文文本，用于前端展示与验收(V2-08)。"""
    try:
        conn = _conn(db_path)
        pcount = conn.execute(
            "SELECT COUNT(*) AS c FROM store_profiles WHERE store_id=?", (store_id,)
        ).fetchone()["c"]
        mcount = conn.execute(
            "SELECT COUNT(*) AS c FROM agent_memory WHERE store_id=? AND archived=0", (store_id,)
        ).fetchone()["c"]
        conn.close()
        profiles = get_store_profiles(db_path, store_id)
        memories = get_agent_memory(db_path, store_id)
        return {
            "store_id": store_id,
            "profile_count": pcount,
            "memory_count": mcount,
            "context_text": build_memory_context(db_path, store_id, record_recall=False),
            "profiles": [
                {
                    "profile_type": p["profile_type"],
                    "label": PROFILE_TYPES.get(p["profile_type"], p["profile_type"]),
                    "content": json.loads(p["content_json"]).get("text", p["content_json"])
                    if isinstance(p["content_json"], str) else p["content_json"],
                    "confidence": p.get("confidence"),
                    "last_updated": p.get("last_updated"),
                }
                for p in profiles
            ],
            "memories": [
                {
                    "memory_type": m["memory_type"],
                    "label": MEMORY_TYPES.get(m["memory_type"], m["memory_type"]),
                    "summary": m["summary"],
                    "importance": m.get("importance"),
                    "recall_count": m.get("recall_count"),
                    "created_at": m.get("created_at"),
                }
                for m in memories
            ],
        }
    except Exception as e:
        return {"store_id": store_id, "error": str(e), "profile_count": 0, "memory_count": 0}
