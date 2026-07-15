#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单视频价格解析器（供 app.py analyze_upload_video 调用）

流程: 抽帧(ffmpeg) → RapidOCR → 价格/促销提取 → 结构化 JSON
用法: python3 analyze_video.py <video_path> [product_name]
  - 成功: 向 stdout 输出单行 JSON，退出码 0
  - 失败: 向 stderr 输出错误，退出码 1

输出 JSON 字段:
  success        bool
  method         "rapidocr"
  product_name   str   商品名（优先用传入的，否则从 OCR 推断）
  detected_price float 检测到的价格（无则为 null）
  product_spec   str   推断的规格（可选）
  promotion_desc str   促销标签拼接
  has_promotion  int   0/1
  confidence     float 0~1 置信度
  frame_count    int   抽帧数
  raw_text       str   全部 OCR 文本拼接（调试用）
"""
import os
import sys
import json
import re
import subprocess
import tempfile
from pathlib import Path

try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

try:
    from rapidocr_onnxruntime import RapidOCR
    OCR_ENGINE = RapidOCR()
    HAS_OCR = True
except Exception as e:
    HAS_OCR = False
    OCR_ENGINE = None

PRICE_RE = re.compile(r"(?:[¥￥]\s?|RMB\s?)?(\d{1,3}(?:[.,]\d{3})*(?:\.\d{1,2})?)")
PROMO_KW = ["满减", "优惠券", "限时", "折扣", "秒杀", "包邮", "运费", "立减", "券", "特价", "促销", "买一送", "第二件", "半价"]

SPEC_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:ml|mL|L|g|kg|KG|克|千克|ml|L|瓶|袋|包|盒|听|罐))")


def get_duration(video_path):
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "json", video_path],
                           capture_output=True, text=True, timeout=30)
        return int(float(json.loads(p.stdout)["format"]["duration"]))
    except Exception:
        return 60


def extract_frames(video_path, out_dir, interval=2, max_frames=40):
    total = get_duration(video_path)
    frames = []
    sec = 0
    while sec < total:
        op = os.path.join(out_dir, f"f{sec:05d}.jpg")
        r = subprocess.run(["ffmpeg", "-y", "-ss", str(sec), "-i", video_path,
                            "-vframes", "1", "-q:v", "2", op],
                           capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(op):
            frames.append(op)
        sec += interval
        if len(frames) >= max_frames:
            break
    return frames


def ocr_frame(img_path):
    if not HAS_OCR:
        return [], 0.0
    try:
        res, _ = OCR_ENGINE(img_path)
        if not res:
            return [], 0.0
        blocks = []
        scores = []
        for item in res:
            txt = (item[1] or "").strip()
            try:
                score = float(item[-1])
            except Exception:
                score = 0.0
            if txt:
                blocks.append(txt)
                scores.append(score)
        avg = sum(scores) / len(scores) if scores else 0.0
        return blocks, avg
    except Exception as e:
        return [], 0.0


def clean_name(text):
    """从含价格的文本块里抠出商品名候选"""
    t = text
    t = re.sub(PRICE_RE, " ", t)
    t = re.sub(r"[¥￥RMB]", " ", t)
    for kw in PROMO_KW:
        t = t.replace(kw, " ")
    t = re.sub(r"\s+", " ", t).strip(" :：-—")
    return t


def main():
    if len(sys.argv) < 2:
        print("用法: python3 analyze_video.py <video_path> [product_name]", file=sys.stderr)
        sys.exit(1)

    video_path = sys.argv[1]
    given_name = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(video_path):
        print(json.dumps({"success": False, "error": f"文件不存在: {video_path}"}))
        sys.exit(1)

    if not HAS_CV2 or not HAS_OCR:
        print(json.dumps({"success": False, "error": f"依赖缺失 cv2={HAS_CV2} ocr={HAS_OCR}"}))
        sys.exit(1)

    tmp = tempfile.mkdtemp(prefix="analyze_")
    frames = extract_frames(video_path, tmp, interval=2, max_frames=40)

    all_blocks = []
    scores = []
    for fr in frames:
        blocks, avg = ocr_frame(fr)
        all_blocks.extend(blocks)
        if blocks:
            scores.append(avg)

    raw_text = " | ".join(all_blocks)

    # 价格提取（跨所有帧取出现次数最多且合理的价格）
    price_counter = {}
    for b in all_blocks:
        for m in PRICE_RE.finditer(b):
            try:
                val = float(m.group(1).replace(",", ""))
            except Exception:
                continue
            if 0.1 <= val <= 9999:
                price_counter[val] = price_counter.get(val, 0) + 1
    detected_price = None
    if price_counter:
        # 取频次最高；并列时取中位数
        best = max(price_counter.items(), key=lambda kv: (kv[1], -abs(kv[0] - 10)))
        detected_price = best[0]

    # 促销标签
    promo = [kw for kw in PROMO_KW if kw in raw_text]
    promotion_desc = "、".join(promo)
    has_promotion = 1 if promo else 0

    # 规格
    spec_match = SPEC_RE.search(raw_text)
    product_spec = spec_match.group(1) if spec_match else None

    # 商品名：优先用传入；否则从含价格的文本块推断
    product_name = given_name
    if not product_name:
        for b in all_blocks:
            if PRICE_RE.search(b):
                cand = clean_name(b)
                if 2 <= len(cand) <= 20:
                    product_name = cand
                    break

    # 置信度：OCR 平均分数；若检测到价格则加权
    base_conf = round(sum(scores) / len(scores), 3) if scores else 0.0
    if detected_price is not None:
        confidence = min(0.95, max(base_conf, 0.6))
    else:
        confidence = round(base_conf * 0.5, 3)

    out = {
        "success": True,
        "method": "rapidocr",
        "product_name": product_name,
        "detected_price": detected_price,
        "product_spec": product_spec,
        "promotion_desc": promotion_desc,
        "has_promotion": has_promotion,
        "confidence": confidence,
        "frame_count": len(frames),
        "raw_text": raw_text[:2000],
    }
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
