# -*- coding: utf-8 -*-
"""
完整数据归集：合并 广安1-40 报告 + 商品信息*(41-89) → 单一主表
输出：商品数据全集_1_89.xlsx
"""
import pandas as pd, re, os
from pathlib import Path

dest = Path(r"C:\Users\13522\Desktop\广安商超\处理结果_41_89\_商品提取")
OUT  = dest / "商品数据全集_1_89.xlsx"

def parse_price(text):
    if not isinstance(text, str): return None
    m = re.search(r'[￥¥$]\s*(\d+(?:\.\d+)?)', text)
    if m:
        v = float(m.group(1))
        if 0 < v < 100000:
            return round(v, 2)
    return None

def norm(s):
    return re.sub(r'\s+', '', str(s)) if isinstance(s, str) else ""

rows = []

# ── A. 广安1-40 商品详情汇总 ──────────────────────────────
print("读取 广安1-40 报告...")
n140 = 0
for f in sorted(dest.glob("广安*.xlsx")):
    try:
        xl = pd.ExcelFile(f)
        if "商品详情汇总" not in xl.sheet_names:
            continue
        raw = pd.read_excel(f, sheet_name="商品详情汇总", header=None)
        # 定位表头行（含"一级品类"）
        hdr_row = None
        for i in range(min(12, len(raw))):
            if any("一级品类" in str(x) for x in raw.iloc[i]):
                hdr_row = i; break
        if hdr_row is None:
            continue
        header = [str(x) for x in raw.iloc[hdr_row]]
        df = raw.iloc[hdr_row+1:].copy()
        df.columns = header
        # 合并单元格：前向填充一级/二级品类
        if "一级品类" in df.columns: df["一级品类"] = df["一级品类"].ffill()
        if "二级品类" in df.columns: df["二级品类"] = df["二级品类"].ffill()
        cn = next((c for c in df.columns if "商品名称" in str(c)), None)
        if cn is None:
            continue
        cp = next((c for c in df.columns if "价格" in str(c) or "备注" in str(c)), None)
        vid = f.stem
        for _, r in df.iterrows():
            name = r[cn]
            if not isinstance(name, str) or len(norm(name)) < 3:
                continue
            if norm(name) in ("一级品类", "商品名称", ""):
                continue
            c1v = r.get("一级品类", "")
            c2v = r.get("二级品类", "")
            rows.append({
                "来源范围": "广安1-40",
                "来源视频": vid,
                "一级品类": str(c1v).strip() if isinstance(c1v, str) else "",
                "二级品类": str(c2v).strip() if isinstance(c2v, str) else "",
                "商品名称": name.strip(),
                "价格文本": str(r[cp]) if cp and isinstance(r[cp], str) else "",
                "描述": "",
            })
            n140 += 1
    except Exception as e:
        print(f"  [跳过 {f.name}] {e}")
print(f"  广安1-40 提取: {n140} 行")

# ── B. 商品信息* (41-89) ─────────────────────────────────
print("读取 商品信息* (41-89)...")
n489 = 0
seen = set()
info_files = sorted(dest.glob("商品信息*.xlsx"))
for f in info_files:
    try:
        xl = pd.ExcelFile(f)
        sn = xl.sheet_names[0]
        df = pd.read_excel(f, sheet_name=sn)
        cols = list(df.columns)
        c_cat = next((c for c in cols if "分类" in str(c)), None)
        cn   = next((c for c in cols if "商品名称" in str(c)), None)
        if cn is None:
            cn = next((c for c in cols if str(c) == "商品名称"), None)
        cp   = next((c for c in cols if "价格" in str(c)), None)
        cd   = next((c for c in cols if "描述" in str(c)), None)
        if cn is None:
            continue
        for _, r in df.iterrows():
            name = r[cn]
            if not isinstance(name, str) or len(norm(name)) < 3:
                continue
            price_txt = str(r[cp]) if cp and isinstance(r[cp], str) else ""
            cat = str(r[c_cat]).strip() if c_cat and isinstance(r[c_cat], str) else ""
            desc = str(r[cd]).strip() if cd and isinstance(r[cd], str) else ""
            key = (norm(name), parse_price(price_txt))
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "来源范围": "广安41-89",
                "来源视频": "",
                "一级品类": cat,
                "二级品类": "",
                "商品名称": name.strip(),
                "价格文本": price_txt,
                "描述": desc,
            })
            n489 += 1
    except Exception as e:
        print(f"  [跳过 {f.name}] {e}")
print(f"  商品信息* 去重后: {n489} 行")

# ── 构建 DataFrame ────────────────────────────────────────
master = pd.DataFrame(rows)
master["价格"] = master["价格文本"].apply(parse_price)
master = master[["来源范围","来源视频","一级品类","二级品类","商品名称","价格","价格文本","描述"]]

# 排序：先按来源范围，再按视频，再按品类
master["_vid_sort"] = master["来源视频"].apply(lambda x: int(re.sub(r'\D','',str(x)) or 0))
master = master.sort_values(["来源范围","_vid_sort","一级品类","商品名称"], kind="stable").drop(columns="_vid_sort")
master = master.reset_index(drop=True)
master.insert(0, "序号", range(1, len(master)+1))

print(f"\n主表总行数: {len(master)}")
print(f"  广安1-40: {(master['来源范围']=='广安1-40').sum()}")
print(f"  广安41-89: {(master['来源范围']=='广安41-89').sum()}")

# ── 汇总 Sheet ────────────────────────────────────────────
# 按品类(一级)
cat_summary = master[master["一级品类"].astype(str).str.len() > 0].groupby("一级品类").agg(
    商品数=("商品名称","count"),
    均价=("价格","mean"),
    最低价=("价格","min"),
    最高价=("价格","max"),
).round(2).sort_values("商品数", ascending=False)

# 按来源
src_summary = master.groupby("来源范围").agg(
    商品数=("商品名称","count"),
    有价格数=("价格", lambda s: s.notna().sum()),
    均价=("价格","mean"),
).round(2)

# 价格分布
valid = master[master["价格"].notna()].copy()
bins = [0,1,5,10,15,20,30,50,100,100000]
labels = ["0-1","1-5","5-10","10-15","15-20","20-30","30-50","50-100","100+"]
valid["区间"] = pd.cut(valid["价格"], bins=bins, labels=labels)
price_dist = valid.groupby("区间", observed=True).agg(商品数=("商品名称","count"), 均价=("价格","mean")).round(2)

# ── 写出 ──────────────────────────────────────────────────
with pd.ExcelWriter(OUT, engine="openpyxl") as w:
    master.to_excel(w, sheet_name="商品数据全集", index=False)
    cat_summary.to_excel(w, sheet_name="按品类统计")
    src_summary.to_excel(w, sheet_name="按来源统计")
    price_dist.to_excel(w, sheet_name="价格分布")
    # 无价格商品清单
    noprice = master[master["价格"].isna()][["序号","来源范围","来源视频","一级品类","商品名称","价格文本"]]
    noprice.to_excel(w, sheet_name="无价格商品", index=False)

print(f"\n已写出: {OUT}")
print(f"  Sheet: 商品数据全集 / 按品类统计 / 按来源统计 / 价格分布 / 无价格商品")
