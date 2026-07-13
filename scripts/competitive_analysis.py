# -*- coding: utf-8 -*-
"""
鹿小仓广安店 vs 小柴购 — 全维度竞争对比分析
"""
import pandas as pd, numpy as np, re, os
from pathlib import Path
from collections import Counter

OUT_DIR = Path(r"C:\Users\13522\Desktop\广安商超")
OUT_XLSX = OUT_DIR / "鹿小仓vs小柴购_竞争对比分析.xlsx"

# ── 读取数据 ──
print("读取数据...")
df_lxc = pd.read_excel(r"C:\Users\13522\Desktop\鹿小仓广安店\鹿小仓广安店_库存合并总表.xlsx", sheet_name="库存合并总表", dtype=str)
df_xcg = pd.read_excel(r"C:\Users\13522\Desktop\广安商超\小柴购_全量数据表_v5.xlsx", sheet_name="全量数据表", dtype=str)

# 数值化
for c in ["售价","采购价","毛利","加价率"]:
    df_lxc[c] = pd.to_numeric(df_lxc[c], errors="coerce")
df_xcg["售卖单价"] = pd.to_numeric(df_xcg["售卖单价"], errors="coerce")

print(f"鹿小仓: {len(df_lxc)} 条SKU")
print(f"小柴购: {len(df_xcg)} 条SKU")

# ═══════════════════════════════════════════════════
# 1. 规模与品类结构对比
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("1. 规模与品类结构对比")
print("="*60)

lxc_cats = df_lxc["一级大类"].value_counts()
xcg_cats = df_xcg["一级大类"].value_counts()
all_cats = sorted(set(lxc_cats.index) | set(xcg_cats.index), key=lambda c: -(lxc_cats.get(c,0)+xcg_cats.get(c,0)))

cat_cmp = []
for cat in all_cats:
    lxc_n = int(lxc_cats.get(cat, 0))
    xcg_n = int(xcg_cats.get(cat, 0))
    lxc_pct = lxc_n / len(df_lxc) * 100
    xcg_pct = xcg_n / len(df_xcg) * 100
    lxc_price = df_lxc[df_lxc["一级大类"]==cat]["售价"].mean()
    xcg_price = df_xcg[df_xcg["一级大类"]==cat]["售卖单价"].mean()
    lxc_cost = df_lxc[df_lxc["一级大类"]==cat]["采购价"].mean()
    lxc_margin = df_lxc[df_lxc["一级大类"]==cat]["毛利"].mean()
    lxc_rate = df_lxc[df_lxc["一级大类"]==cat]["加价率"].mean()
    lxc_flow = len(df_lxc[(df_lxc["一级大类"]==cat) & (df_lxc["引流标识"].notna() & (df_lxc["引流标识"]!="") & (df_lxc["引流标识"]!="nan"))])
    xcg_flow = len(df_xcg[(df_xcg["一级大类"]==cat) & (df_xcg["引流标识"].notna() & (df_xcg["引流标识"]!="") & (df_xcg["引流标识"]!="nan"))])
    gap = xcg_n - lxc_n
    cat_cmp.append({
        "品类": cat,
        "鹿小仓SKU": lxc_n, "鹿小仓占比": f"{lxc_pct:.1f}%",
        "小柴购SKU": xcg_n, "小柴购占比": f"{xcg_pct:.1f}%",
        "SKU差距": gap,
        "鹿小仓均价": round(lxc_price,2) if pd.notna(lxc_price) else 0,
        "小柴购均价": round(xcg_price,2) if pd.notna(xcg_price) else 0,
        "价差": round((xcg_price or 0) - (lxc_price or 0), 2),
        "鹿小仓均采购价": round(lxc_cost,2) if pd.notna(lxc_cost) else 0,
        "鹿小仓均毛利": round(lxc_margin,2) if pd.notna(lxc_margin) else 0,
        "鹿小仓均加价率": f"{lxc_rate:.1f}%" if pd.notna(lxc_rate) else "—",
        "鹿小仓引流": lxc_flow, "小柴购引流": xcg_flow,
    })
df_cat_cmp = pd.DataFrame(cat_cmp)
print(df_cat_cmp.to_string(index=False))

# ═══════════════════════════════════════════════════
# 2. 价格带对比
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("2. 价格带对比")
print("="*60)

bins = [0,1,5,10,20,50,100,200,500,1000,999999]
labels = ["0-1元","1-5元","5-10元","10-20元","20-50元","50-100元","100-200元","200-500元","500-1000元","1000元+"]
df_lxc_valid = df_lxc[df_lxc["售价"].notna()].copy()
df_xcg_valid = df_xcg[df_xcg["售卖单价"].notna()].copy()
df_lxc_valid["价格区间"] = pd.cut(df_lxc_valid["售价"], bins=bins, labels=labels, right=False)
df_xcg_valid["价格区间"] = pd.cut(df_xcg_valid["售卖单价"], bins=bins, labels=labels, right=False)

price_cmp = []
for label in labels:
    lxc_n = len(df_lxc_valid[df_lxc_valid["价格区间"]==label])
    xcg_n = len(df_xcg_valid[df_xcg_valid["价格区间"]==label])
    lxc_pct = lxc_n / len(df_lxc_valid) * 100
    xcg_pct = xcg_n / len(df_xcg_valid) * 100
    price_cmp.append({
        "价格区间": label,
        "鹿小仓数量": lxc_n, "鹿小仓占比": f"{lxc_pct:.1f}%",
        "小柴购数量": xcg_n, "小柴购占比": f"{xcg_pct:.1f}%",
        "占比差": f"{xcg_pct - lxc_pct:+.1f}%",
    })
df_price_cmp = pd.DataFrame(price_cmp)
print(df_price_cmp.to_string(index=False))

# ═══════════════════════════════════════════════════
# 3. 引流品对比
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("3. 引流品策略对比")
print("="*60)

lxc_flow_mask = df_lxc["引流标识"].notna() & (df_lxc["引流标识"]!="") & (df_lxc["引流标识"]!="nan")
xcg_flow_mask = df_xcg["引流标识"].notna() & (df_xcg["引流标识"]!="") & (df_xcg["引流标识"]!="nan")

lxc_flow_cnt = lxc_flow_mask.sum()
xcg_flow_cnt = xcg_flow_mask.sum()

print(f"鹿小仓引流品: {lxc_flow_cnt} ({lxc_flow_cnt/len(df_lxc)*100:.1f}%)")
print(f"小柴购引流品: {xcg_flow_cnt} ({xcg_flow_cnt/len(df_xcg)*100:.1f}%)")

# 引流品品类分布
lxc_flow_cats = df_lxc[lxc_flow_mask]["一级大类"].value_counts()
xcg_flow_cats = df_xcg[xcg_flow_mask]["一级大类"].value_counts()

flow_cmp = []
for cat in all_cats:
    ln = int(lxc_flow_cats.get(cat, 0))
    xn = int(xcg_flow_cats.get(cat, 0))
    if ln > 0 or xn > 0:
        flow_cmp.append({"品类": cat, "鹿小仓引流": ln, "小柴购引流": xn, "差距": xn-ln})
df_flow_cmp = pd.DataFrame(flow_cmp)
print(df_flow_cmp.to_string(index=False))

# 引流品价格对比
lxc_flow_prices = df_lxc[lxc_flow_mask]["售价"]
xcg_flow_prices = df_xcg[xcg_flow_mask]["售卖单价"]
print(f"\n鹿小仓引流品均价: {lxc_flow_prices.mean():.2f}, 中位: {lxc_flow_prices.median():.2f}")
print(f"小柴购引流品均价: {xcg_flow_prices.mean():.2f}, 中位: {xcg_flow_prices.median():.2f}")

# ═══════════════════════════════════════════════════
# 4. 商品重叠分析
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("4. 商品重叠分析")
print("="*60)

# 名称清洗
def clean_name(n):
    if not isinstance(n, str): return ""
    n = re.sub(r'\s+', '', n)
    n = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', n)
    return n.lower().strip()

lxc_names = set(df_lxc["商品名称"].apply(clean_name))
xcg_names = set(df_xcg["商品标准名称"].apply(clean_name))
overlap = lxc_names & xcg_names
lxc_only = lxc_names - xcg_names
xcg_only = xcg_names - lxc_names
print(f"鹿小仓SKU(清洗后): {len(lxc_names)}")
print(f"小柴购SKU(清洗后): {len(xcg_names)}")
print(f"重叠商品: {len(overlap)} ({len(overlap)/min(len(lxc_names),len(xcg_names))*100:.1f}%)")
print(f"鹿小仓独有: {len(lxc_only)}")
print(f"小柴购独有: {len(xcg_only)}")

# 重叠商品的价格差异
overlap_price_diff = []
for name in overlap:
    lxc_row = df_lxc[df_lxc["商品名称"].apply(clean_name)==name].iloc[0]
    xcg_row = df_xcg[df_xcg["商品标准名称"].apply(clean_name)==name].iloc[0]
    lp = lxc_row["售价"]
    xp = xcg_row["售卖单价"]
    if pd.notna(lp) and pd.notna(xp) and lp > 0:
        diff = lp - xp
        pct = (diff / xp) * 100 if xp > 0 else 0
        overlap_price_diff.append({
            "商品名称": lxc_row["商品名称"][:40],
            "鹿小仓售价": lp, "小柴购售价": xp,
            "价差": round(diff, 2), "价差比例": f"{pct:+.1f}%",
            "鹿小仓采购价": lxc_row.get("采购价", ""),
            "品类": lxc_row["一级大类"],
        })

df_overlap = pd.DataFrame(overlap_price_diff)
if len(df_overlap) > 0:
    df_overlap["价差"] = pd.to_numeric(df_overlap["价差"], errors="coerce")
    more_expensive = (df_overlap["价差"] > 0).sum()
    cheaper = (df_overlap["价差"] < 0).sum()
    same = (df_overlap["价差"] == 0).sum()
    avg_diff = df_overlap["价差"].mean()
    print(f"\n重叠商品价格对比: {len(df_overlap)} 个")
    print(f"  鹿小仓更贵: {more_expensive} ({more_expensive/len(df_overlap)*100:.1f}%)")
    print(f"  小柴购更贵: {cheaper} ({cheaper/len(df_overlap)*100:.1f}%)")
    print(f"  价格相同: {same}")
    print(f"  平均价差: {avg_diff:+.2f} 元")
    # 价差最大的10个
    df_overlap_sorted = df_overlap.reindex(df_overlap["价差"].abs().sort_values(ascending=False).index)
    print(f"\n  价差最大Top10:")
    print(df_overlap_sorted.head(10)[["商品名称","鹿小仓售价","小柴购售价","价差","价差比例"]].to_string(index=False))

# ═══════════════════════════════════════════════════
# 5. 毛利结构对比
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("5. 鹿小仓毛利结构（小柴购无采购价，仅分析鹿小仓）")
print("="*60)

margin_cats = []
for cat in all_cats:
    cd = df_lxc[df_lxc["一级大类"]==cat]
    has_margin = cd[cd["毛利"].notna()]
    if len(has_margin) > 0:
        margins = has_margin["毛利"]
        rates = has_margin["加价率"]
        margin_cats.append({
            "品类": cat,
            "有毛利SKU": len(has_margin),
            "覆盖率": f"{len(has_margin)/len(cd)*100:.1f}%",
            "均毛利": round(margins.mean(),2),
            "中位毛利": round(margins.median(),2),
            "均加价率": f"{rates.mean():.1f}%",
            "中位加价率": f"{rates.median():.1f}%",
            "负毛利数": int((margins < 0).sum()),
        })
df_margin = pd.DataFrame(margin_cats)
print(df_margin.to_string(index=False))

# ═══════════════════════════════════════════════════
# 6. 小柴购独有品类深挖 — 鹿小仓的选品空白
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("6. 小柴购独有商品分析（鹿小仓选品空白）")
print("="*60)

# 小柴购独有商品的品类分布
xcg_only_df = df_xcg[df_xcg["商品标准名称"].apply(clean_name).isin(xcg_only)]
xcg_only_cats = xcg_only_df["一级大类"].value_counts()
print(f"\n小柴购独有商品品类分布 (共{len(xcg_only_df)}条):")
for cat, cnt in xcg_only_cats.items():
    avg_price = xcg_only_df[xcg_only_df["一级大类"]==cat]["售卖单价"].mean()
    flow_cnt = len(xcg_only_df[(xcg_only_df["一级大类"]==cat) & xcg_flow_mask])
    print(f"  {cat}: {cnt} ({cnt/len(xcg_only_df)*100:.1f}%) 均价{avg_price:.1f} 引流{flow_cnt}")

# 小柴购独有商品中价格≤10元的高频低价品
xcg_only_cheap = xcg_only_df[xcg_only_df["售卖单价"] <= 10]
print(f"\n小柴购独有且≤10元: {len(xcg_only_cheap)} 条")
xcg_only_cheap_cats = xcg_only_cheap["一级大类"].value_counts()
for cat, cnt in xcg_only_cheap_cats.items():
    if cnt >= 20:
        print(f"  {cat}: {cnt}")

# ═══════════════════════════════════════════════════
# 7. 综合差距评分
# ═══════════════════════════════════════════════════
print("\n" + "="*60)
print("7. 综合差距评分")
print("="*60)

metrics = {
    "总SKU数": (len(df_lxc), len(df_xcg), f"{len(df_xcg)/len(df_lxc):.1f}倍"),
    "有价格SKU": (len(df_lxc_valid), len(df_xcg_valid), f"{len(df_xcg_valid)/len(df_lxc_valid):.1f}倍"),
    "引流品数": (lxc_flow_cnt, xcg_flow_cnt, f"{xcg_flow_cnt/lxc_flow_cnt:.1f}倍" if lxc_flow_cnt>0 else "—"),
    "引流品占比": (f"{lxc_flow_cnt/len(df_lxc)*100:.1f}%", f"{xcg_flow_cnt/len(df_xcg)*100:.1f}%", ""),
    "覆盖品类数": (len(lxc_cats), len(xcg_cats), ""),
    "平均售价": (f"{df_lxc_valid['售价'].mean():.2f}元", f"{df_xcg_valid['售卖单价'].mean():.2f}元", ""),
    "中位售价": (f"{df_lxc_valid['售价'].median():.2f}元", f"{df_xcg_valid['售卖单价'].median():.2f}元", ""),
}
print(f"{'指标':<15} {'鹿小仓':<15} {'小柴购':<15} {'倍数':<10}")
for k, (l, x, r) in metrics.items():
    print(f"  {k:<15} {str(l):<15} {str(x):<15} {r}")

# ═══════════════════════════════════════════════════
# 写出Excel
# ═══════════════════════════════════════════════════
print(f"\n写出Excel...")
with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as w:
    # 综合对比
    summary_data = []
    for k, (l, x, r) in metrics.items():
        summary_data.append({"指标": k, "鹿小仓": l, "小柴购": x, "差距": r})
    pd.DataFrame(summary_data).to_excel(w, sheet_name="综合对比", index=False)
    
    # 品类对比
    df_cat_cmp.to_excel(w, sheet_name="品类结构对比", index=False)
    
    # 价格带对比
    df_price_cmp.to_excel(w, sheet_name="价格带对比", index=False)
    
    # 引流品对比
    df_flow_cmp.to_excel(w, sheet_name="引流品对比", index=False)
    
    # 毛利结构
    df_margin.to_excel(w, sheet_name="鹿小仓毛利结构", index=False)
    
    # 重叠商品价格对比
    if len(df_overlap) > 0:
        df_overlap_sorted.to_excel(w, sheet_name="重叠商品价差", index=False)
    
    # 小柴购独有Top品类
    xcg_only_summary = []
    for cat in xcg_only_cats.index:
        cd = xcg_only_df[xcg_only_df["一级大类"]==cat]
        xcg_only_summary.append({
            "品类": cat,
            "独有SKU数": len(cd),
            "均价": round(cd["售卖单价"].mean(), 2),
            "中位价": round(cd["售卖单价"].median(), 2),
            "引流数": len(cd[cd["引流标识"].notna() & (cd["引流标识"]!="") & (cd["引流标识"]!="nan")]),
            "最低价": round(cd["售卖单价"].min(), 2),
            "最高价": round(cd["售卖单价"].max(), 2),
        })
    pd.DataFrame(xcg_only_summary).to_excel(w, sheet_name="小柴购独有分析", index=False)

print(f"输出: {OUT_XLSX}")

# 删除探查脚本
try: os.remove(r"C:\Users\13522\.qclaw\workspace\luxiaocang\_cmp_probe.py")
except: pass

print("\n完成!")
