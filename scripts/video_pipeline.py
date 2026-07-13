"""
全量帧级电商数据采集与智能聚合分析 Pipeline v2
龙   虾 AI 专用 | 1秒1帧 + RapidOCR + 批量Excel + 最终LLM聚合
架构:脚本做苦力(抽帧/OCR/去重/频次),LLM做语义聚合(明天跑)
支持断点续跑 + 已有Excel自动加载
"""
import os, sys, time, json, re, subprocess, logging, difflib
from pathlib import Path
from collections import Counter
from datetime import datetime

import cv2
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

try:
    from rapidocr_onnxruntime import RapidOCR
    OCR_ENGINE = RapidOCR()
    HAS_OCR = True
except Exception as e:
    OCR_ENGINE, HAS_OCR = None, False
    print(f"[WARN] RapidOCR 加载失败: {e}")

# ── 配置 ────────────────────────────────────────────────
FPS_INTERVAL   = 1          # 每1秒抽1帧
SUPPORTED_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

C_HEADER_BG, C_HEADER_FG = "1F4E79", "FFFFFF"
C_ALT_ROW,  C_BORDER     = "D6E4F0", "8EA9C1"

LOG_FILE = Path(__file__).parent / "pipeline_run.log"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("VideoPipeline")

_ALL_SMALL_ROWS: list[dict] = []

# ════════════════════════════════════════════════
#  抽帧
# ════════════════════════════════════════════════
def get_duration(video_path: str) -> int:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", video_path], capture_output=True, text=True, timeout=30)
        return int(float(json.loads(p.stdout)["format"]["duration"]))
    except Exception:
        return 180  # 默认3分钟

def extract_frames(video_path: str, out_dir: str, interval: int = 1) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    total = get_duration(video_path)
    frames = []
    for sec in range(0, total, interval):
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        ts = f"{h:02d}:{m:02d}:{s:02d}.000"
        fn = f"frame_{sec:06d}.jpg"
        op = os.path.join(out_dir, fn)
        r = subprocess.run(["ffmpeg", "-y", "-ss", ts, "-i", video_path,
                            "-vframes", "1", "-q:v", "2", op],
                           capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(op):
            frames.append({"frame_idx": len(frames), "sec": sec,
                           "filename": fn, "filepath": op})
    return frames

# ════════════════════════════════════════════════
#  OCR
# ════════════════════════════════════════════════
def ocr_frame(img: str) -> dict:
    if not HAS_OCR:
        return {"full_text": "", "blocks": []}
    try:
        res, _ = OCR_ENGINE(img)
        if not res:
            return {"full_text": "", "blocks": []}
        blocks, lines = [], []
        for item in res:
            txt   = item[1].strip()
            score = float(item[-1])
            blocks.append({"text": txt, "score": score})
            lines.append(txt)
        return {"full_text": " ".join(lines), "blocks": blocks}
    except Exception as e:
        log.error(f"OCR异常 {img}: {e}")
        return {"full_text": "", "blocks": []}

# ════════════════════════════════════════════════
#  单视频脚本级整合(去重+频次+字段提取)
# ════════════════════════════════════════════════
PRICE_RE = re.compile(r"[¥￥$]?\s*\d{1,3}(?:[.,]\d{3})*(?:\.\d{1,2})?|\d+\s*元")
PROMO_KW = ["满减", "优惠券", "限时", "折扣", "秒杀", "包邮", "运费", "立减", "券"]

def extract_fields(text: str) -> dict:
    prices = PRICE_RE.findall(text)
    promo  = [k for k in PROMO_KW if k in text]
    return {"prices": prices, "promo": promo}

def integrate_video_text(all_blocks: list[dict]) -> pd.DataFrame:
    """对单视频全部文字块做去重+频次统计+字段提取 → 去重汇总表"""
    # 频次统计(原文精确去重)
    cnt = Counter(b["text"] for b in all_blocks if b["text"].strip())
    rows = []
    for txt, n in cnt.most_common():
        f = extract_fields(txt)
        rows.append({
            "去重后文字": txt,
            "出现帧数": n,
            "提取价格": " ".join(f["prices"]) if f["prices"] else "",
            "促销标签": " ".join(f["promo"]) if f["promo"] else "",
            "疑似商品名": "Y" if (len(txt) >= 4 and any(c.isalpha() for c in txt)
                                   and not f["prices"] and not f["promo"]) else "",
        })
    return pd.DataFrame(rows)

# ════════════════════════════════════════════════
#  单视频处理
# ════════════════════════════════════════════════
def process_single_video(video_path: str, out_dir: str, name: str) -> pd.DataFrame | None:
    log.info(f"\n{'='*60}\n🎬 {name}\n{'='*60}")
    frames_dir = os.path.join(out_dir, "_frames", name)
    ocr_dir    = os.path.join(out_dir, "_ocr", name)
    os.makedirs(frames_dir, exist_ok=True)
    os.makedirs(ocr_dir, exist_ok=True)

    t0 = time.time()
    meta = extract_frames(video_path, frames_dir, FPS_INTERVAL)
    log.info(f"📸 抽帧 {len(meta)} 帧, {(time.time()-t0):.0f}s")
    if not meta:
        return None

    raw_rows, video_blocks = [], []
    for i, fm in enumerate(meta):
        if (i+1) % 30 == 0:
            log.info(f"  OCR {i+1}/{len(meta)}")
        ocr = ocr_frame(fm["filepath"])
        json.dump({"meta": fm, "ocr": ocr},
                  open(os.path.join(ocr_dir, f"{fm['filename']}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        bc = len(ocr["blocks"])
        avg = sum(b["score"] for b in ocr["blocks"]) / bc if bc else 0
        raw_rows.append({"视频文件名": name, "帧序号": fm["frame_idx"],
                         "采集时间(秒)": fm["sec"], "帧文件名": fm["filename"],
                         "完整原文": ocr["full_text"], "文字片段数": bc,
                         "平均置信度": round(avg, 4)})
        for b in ocr["blocks"]:
            video_blocks.append(b)
            _ALL_SMALL_ROWS.append({"视频文件名": name, "帧序号": fm["frame_idx"],
                                    "采集时间(秒)": fm["sec"], "文字片段": b["text"],
                                    "置信度": round(b["score"], 4)})

    df_raw = pd.DataFrame(raw_rows)
    df_dedupe = integrate_video_text(video_blocks)
    log.info(f"✅ OCR完成 {len(df_raw)}行 | 去重后 {len(df_dedupe)}条唯一文字")
    return df_raw, df_dedupe

def save_video_excel(name: str, df_raw: pd.DataFrame, df_dedupe: pd.DataFrame, out_dir: str):
    stem = Path(name).stem
    path = os.path.join(out_dir, f"{stem}_原始明细.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df_raw.to_excel(w, sheet_name="帧级原文", index=False)
        df_dedupe.to_excel(w, sheet_name="去重汇总", index=False)
    log.info(f"📊 {path}")
    return path

# ════════════════════════════════════════════════
#  扫描 + 续跑
# ════════════════════════════════════════════════
def video_index(name: str) -> int:
    """从文件名提取数字序号,如 广安41.mp4 -> 41"""
    m = re.search(r"(\d+)", Path(name).stem)
    return int(m.group(1)) if m else 0

def scan_videos(folder: str, start_from: int = 1) -> list[str]:
    vs = []
    for root, _, files in os.walk(folder):
        for f in files:
            if Path(f).suffix.lower() in SUPPORTED_EXTS:
                p = os.path.join(root, f)
                if video_index(f) >= start_from:
                    vs.append(p)
    return sorted(vs)

def load_progress(pf: str) -> dict:
    return json.load(open(pf, encoding="utf-8")) if os.path.exists(pf) else {"completed": [], "failed": []}

# ════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════
def main(video_folder: str, out_folder: str, extra_excel_dir: str = None,
         resume: bool = True, start_from: int = 1):
    os.makedirs(out_folder, exist_ok=True)
    pf = os.path.join(out_folder, "_progress.json")
    prog = load_progress(pf)

    log.info("="*70 + "\n🚀 启动 | 视频:%s\n输出:%s\n从序号:%d 开始\n"
             % (video_folder, out_folder, start_from) + "="*70)
    videos = scan_videos(video_folder, start_from)
    log.info(f"📋 发现 {len(videos)} 个视频 (序号>={start_from})")

    records = []   # 所有视频的 帧级原文 DataFrame

    # ── 加载已有Excel(40个已完成的)──
    existing_excels = []
    if extra_excel_dir and os.path.isdir(extra_excel_dir):
        existing_excels = [os.path.join(extra_excel_dir, f)
                           for f in os.listdir(extra_excel_dir) if f.endswith("_原始明细.xlsx")]
    # 也检查out_folder本身已有的
    existing_excels += [os.path.join(out_folder, f)
                        for f in os.listdir(out_folder) if f.endswith("_原始明细.xlsx")]
    for ex in set(existing_excels):
        try:
            df = pd.read_excel(ex, sheet_name="帧级原文")
            records.append(df)
            log.info(f"📂 已加载已有Excel: {os.path.basename(ex)} ({len(df)}行)")
        except Exception as e:
            log.warning(f"⚠ 加载失败 {ex}: {e}")

    # ── 逐个处理 ──
    done_names = set(prog["completed"])
    for idx, vp in enumerate(videos):
        name = os.path.basename(vp)
        excel_candidate = os.path.join(out_folder, f"{Path(name).stem}_原始明细.xlsx")
        if resume and (name in done_names or os.path.exists(excel_candidate)):
            log.info(f"⏭ 跳过已完成: {name}")
            if os.path.exists(excel_candidate):
                try:
                    records.append(pd.read_excel(excel_candidate, sheet_name="帧级原文"))
                except Exception: pass
            continue

        t = time.time()
        try:
            res = process_single_video(vp, out_folder, name)
            if not res:
                raise ValueError("无帧")
            df_raw, df_dedupe = res
            save_video_excel(name, df_raw, df_dedupe, out_folder)
            records.append(df_raw)
            prog["completed"].append(name)
            json.dump(prog, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            log.info(f"✅ [{idx+1}/{len(videos)}] {name} | {len(df_raw)}行 | {time.time()-t:.0f}s")
        except Exception as e:
            log.error(f"❌ {name}: {e}")
            prog["failed"].append({name: str(e)})
            json.dump(prog, open(pf, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ── 全局总表 ──
    if records:
        df_global = pd.concat(records, ignore_index=True)
        gp = os.path.join(out_folder, "全局帧级原始总表.xlsx")
        with pd.ExcelWriter(gp, engine="openpyxl") as w:
            df_global.to_excel(w, sheet_name="全局原始数据", index=False)
            if _ALL_SMALL_ROWS:
                pd.DataFrame(_ALL_SMALL_ROWS).to_excel(w, sheet_name="全局文字片段", index=False)
        log.info(f"✅ 全局总表: {gp} ({len(df_global)}行)")
    log.info("🏁 完成。下一步:调LLM做跨视频聚合分析")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python video_frame_pipeline.py <视频文件夹> <输出目录> [已有Excel文件夹] [起始序号]")
        sys.exit(1)
    extra = sys.argv[3] if len(sys.argv) > 3 else None
    if extra in ("", "none"):
        extra = None
    sf = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    main(sys.argv[1], sys.argv[2], extra, start_from=sf)
