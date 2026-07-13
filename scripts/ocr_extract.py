"""OCR 质量验证实验：合成仿真电商录屏图 → RapidOCR 识别"""
import os
from PIL import Image, ImageDraw, ImageFont

FONT = r"C:\Windows\Fonts\simhei.ttf"

def make_test_image(path: str):
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(img)
    try:
        f_big = ImageFont.truetype(FONT, 48)
        f_mid = ImageFont.truetype(FONT, 32)
        f_sml = ImageFont.truetype(FONT, 22)
    except Exception:
        f_big = f_mid = f_sml = ImageFont.load_default()

    # 商品主标题
    d.text((40, 40), "【旗舰店】新疆和田大枣特产免洗即食骏枣2斤装", fill=(20, 20, 20), font=f_big)
    # 价格区
    d.text((40, 120), "¥ 29.90", fill=(220, 0, 0), font=f_big)
    d.text((320, 135), "原价 ¥59.80", fill=(150, 150, 150), font=f_mid)
    d.text((520, 135), "券后¥19.90", fill=(220, 80, 0), font=f_mid)
    # 促销小字
    d.text((40, 210), "满199减30 | 限时秒杀 | 前100名送枸杞 | 包邮", fill=(0, 100, 200), font=f_mid)
    d.text((40, 270), "已售8.6万  月销2.3万  库存紧张", fill=(100, 100, 100), font=f_sml)
    # 规格参数小字
    d.text((40, 330), "规格:500g*2袋  产地:新疆和田  保质期:12个月", fill=(60, 60, 60), font=f_sml)
    d.text((40, 370), "发货:48小时内  运费:新疆西藏补5元  不支持7天无理由", fill=(60, 60, 60), font=f_sml)
    # 边角备注
    d.text((980, 660), "广告  平台提示:理性消费", fill=(160, 160, 160), font=f_sml)
    img.save(path)
    print(f"✅ 测试图已生成: {path} ({W}x{H})")

def run_ocr(path: str):
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    result, elapse = ocr(path)
    total_ms = elapse[-1] * 1000 if isinstance(elapse, (list, tuple)) else elapse * 1000
    print(f"\n[OCR耗时] {total_ms:.0f}ms")
    print("-" * 60)
    if not result:
        print("[未识别到任何文字]")
        return
    print(f"[识别到 {len(result)} 个文字块]\n")
    for i, item in enumerate(result):
        text = item[1]
        score = float(item[-1])
        print(f"  [{i+1:02d}] {text}  (conf:{score:.3f})")
    print("-" * 60)
    # 验证关键字段
    all_text = " ".join(item[1] for item in result)
    checks = {
        "商品标题": "新疆和田大枣" in all_text,
        "价格29.90": "29.90" in all_text,
        "原价": "59.80" in all_text,
        "券后": "19.90" in all_text,
        "满减": "满199减30" in all_text,
        "限时秒杀": "限时秒杀" in all_text,
        "包邮": "包邮" in all_text,
        "规格": "500g" in all_text,
        "运费说明": "新疆西藏" in all_text,
    }
    print("\n[关键字段识别验证]")
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'XX'}] {k}")

    # 写 UTF-8 干净报告（绕过控制台GBK）
    rep = os.path.join(os.path.dirname(__file__), "ocr_test_report.md")
    with open(rep, "w", encoding="utf-8") as rf:
        rf.write("# OCR 质量验证报告\n\n")
        rf.write(f"- 测试图: {path}\n- OCR耗时: {total_ms:.0f}ms\n- 识别文字块数: {len(result)}\n\n")
        rf.write("## 识别结果\n\n")
        for i, item in enumerate(result):
            rf.write(f"{i+1:02d}. {item[1]}  (conf:{float(item[-1]):.3f})\n")
        rf.write("\n## 关键字段验证\n\n")
        for k, v in checks.items():
            rf.write(f"- [{'OK' if v else 'XX'}] {k}\n")
    print(f"\n[报告已保存] {rep}")

if __name__ == "__main__":
    tp = os.path.join(os.path.dirname(__file__), "ocr_test_image.png")
    make_test_image(tp)
    run_ocr(tp)
