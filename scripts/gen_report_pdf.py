# -*- coding: utf-8 -*-
"""
Generate LXC vs XCG competition analysis PDF report
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

font_path = r'C:\Windows\Fonts\msyh.ttc'
if not os.path.exists(font_path):
    font_path = r'C:\Windows\Fonts\simsun.ttc'
pdfmetrics.registerFont(TTFont('CN', font_path))

OUT = r'C:\Users\13522\Desktop\广安商超\鹿小仓vs小柴购_竞争对比分析报告.pdf'

doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=18*mm, rightMargin=18*mm)
styles = getSampleStyleSheet()

s_title = ParagraphStyle('Title', parent=styles['Title'], fontName='CN', fontSize=18, spaceAfter=10, textColor=colors.HexColor('#1a1a2e'))
s_h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName='CN', fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor('#16213e'))
s_h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontName='CN', fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor('#0f3460'))
s_body = ParagraphStyle('Body', parent=styles['Normal'], fontName='CN', fontSize=9.5, leading=15, spaceAfter=4)
s_warn = ParagraphStyle('Warn', parent=s_body, textColor=colors.HexColor('#c0392b'))
s_ok = ParagraphStyle('OK', parent=s_body, textColor=colors.HexColor('#27ae60'))
s_small = ParagraphStyle('Small', parent=s_body, fontSize=8.5, leading=13)

def make_table(data, col_widths=None, highlight_rows=None):
    t = Table(data, colWidths=col_widths)
    style = [
        ('FONT', (0,0), (-1,-1), 'CN', 8.5),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#ddd')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]
    if highlight_rows:
        for r, color_hex in highlight_rows:
            style.append(('BACKGROUND', (0,r), (-1,r), colors.HexColor(color_hex)))
    t.setStyle(TableStyle(style))
    return t

story = []

# Title
story.append(Paragraph('鹿小仓 vs 小柴购 竞争对比分析报告', s_title))
story.append(Paragraph('承德市南营子大街 广安购物中心 | 数据驱动竞品研判', s_body))
story.append(Spacer(1, 8))

# Section 1
story.append(Paragraph('一、核心发现（执行摘要）', s_h1))
story.append(Paragraph('<b>一句话结论：小柴购在SKU广度上碾压鹿小仓2.6倍，引流品数量是鹿小仓的16倍。但鹿小仓在日化清洁、酒水饮料、粮油调味、休闲零食四个民生品类上SKU反而更丰富，问题不是货不够多，而是引流火力太弱和母婴品类完全缺位。</b>', s_body))
story.append(Spacer(1, 4))

summary_data = [
    ['核心指标', '鹿小仓', '小柴购', '差距'],
    ['总SKU数', '2,941', '7,659', '小柴购是鹿小仓的2.6倍'],
    ['引流品数量', '51', '835', '小柴购是鹿小仓的16.4倍'],
    ['引流品占比', '1.7%', '10.9%', '差6.4倍 - 致命短板'],
    ['0-1元低价品', '26个', '766个', '差29倍 - 价格锚点缺失'],
    ['母婴用品SKU', '32', '2,325', '几乎空白 - 巨大品类缺口'],
    ['平均售价', '24.92元', '25.09元', '基本持平'],
    ['中位售价', '12.80元', '9.40元', '鹿小仓偏高 - 下沉不够'],
    ['商品重叠率', '1个', '-', '0.03% - 几乎完全错位'],
]
story.append(make_table(summary_data, [28*mm, 30*mm, 30*mm, 82*mm]))
story.append(Spacer(1, 6))

story.append(Paragraph('<b>三个致命问题：</b>', s_h2))
story.append(Paragraph('<b>1. 引流火力严重不足。</b>小柴购835个引流品铺满了每个品类入口，顾客进店第一眼就有超便宜的价格锚点。鹿小仓只有51个引流品，顾客感知不到便宜，线上搜索权重也会因此吃亏。', s_warn))
story.append(Paragraph('<b>2. 母婴品类几乎空白。</b>小柴购2325个母婴SKU占其总盘30.4%，这是它最大的差异化武器。鹿小仓只有32个SKU，等于把承德广安购物中心的宝妈客群完全拱手让人。', s_warn))
story.append(Paragraph('<b>3. 价格带偏高。</b>鹿小仓中位售价12.80元 vs 小柴购9.40元。在同一个购物中心里，顾客会本能觉得鹿小仓贵。0-1元价格带鹿小仓只有26个SKU，小柴购有766个，这是外卖平台搜索排序的关键权重区。', s_warn))

story.append(Spacer(1, 4))
story.append(Paragraph('<b>三个优势要守住：</b>', s_h2))
story.append(Paragraph('<b>1. 日化清洁品类领先。</b>鹿小仓682个SKU vs 小柴购318个，2.1倍优势。这是高频刚需品类，要巩固。', s_ok))
story.append(Paragraph('<b>2. 酒水饮料结构更全。</b>310 vs 296，且鹿小仓均价19.13元高于小柴购15.12元，说明鹿小仓在中高端饮料上有优势。', s_ok))
story.append(Paragraph('<b>3. 毛利控制健康。</b>整体加价率中位数在143%-280%之间，14个品类仅1个负毛利SKU。利润结构没问题，问题在引流端不在利润端。', s_ok))

story.append(PageBreak())

# Section 2
story.append(Paragraph('二、品类结构全维度对比', s_h1))
story.append(Paragraph('下表是两个店铺在14个一级品类上的完整对比。标黄行为鹿小仓明显劣势品类，标绿行为鹿小仓优势品类。', s_body))
story.append(Spacer(1, 4))

cat_data = [
    ['品类', '鹿小仓\nSKU', '占比', '小柴购\nSKU', '占比', 'SKU\n差距', '鹿小仓\n均价', '小柴购\n均价', '鹿小仓\n引流', '小柴购\n引流'],
    ['日用百货', '913', '31.0%', '3,240', '42.3%', '-2,327', '27.58', '27.63', '16', '357'],
    ['母婴用品', '32', '1.1%', '2,325', '30.4%', '-2,293', '49.88', '23.50', '1', '297'],
    ['日化清洁', '682', '23.2%', '318', '4.2%', '+364', '20.91', '24.40', '11', '43'],
    ['服饰箱包', '304', '10.3%', '547', '7.1%', '-243', '24.61', '27.18', '3', '48'],
    ['酒水饮料', '310', '10.5%', '296', '3.9%', '+14', '19.13', '15.12', '6', '28'],
    ['数码配件', '149', '5.1%', '255', '3.3%', '-106', '55.59', '28.31', '0', '9'],
    ['粮油调味', '155', '5.3%', '76', '1.0%', '+79', '18.51', '13.26', '2', '8'],
    ['宠物用品', '28', '1.0%', '185', '2.4%', '-157', '23.15', '24.46', '1', '14'],
    ['休闲零食', '105', '3.6%', '92', '1.2%', '+13', '10.40', '15.10', '4', '11'],
    ['消杀用品', '13', '0.4%', '144', '1.9%', '-131', '35.41', '23.62', '0', '8'],
    ['文具办公', '123', '4.2%', '33', '0.4%', '+90', '11.95', '7.86', '4', '7'],
    ['个护美妆', '98', '3.3%', '53', '0.7%', '+45', '28.72', '32.58', '0', '0'],
    ['生鲜果蔬', '24', '0.8%', '48', '0.6%', '-24', '46.75', '15.85', '3', '4'],
    ['速食冷冻', '5', '0.2%', '47', '0.6%', '-42', '16.68', '10.94', '0', '1'],
]
t = make_table(cat_data, [20*mm, 14*mm, 12*mm, 14*mm, 12*mm, 14*mm, 14*mm, 14*mm, 14*mm, 14*mm],
              highlight_rows=[(2,'#fff3cd'),(3,'#fff3cd'),(8,'#fff3cd'),(11,'#fff3cd'),(13,'#fff3cd'),
                              (4,'#d4edda'),(6,'#d4edda'),(9,'#d4edda'),(12,'#d4edda')])
story.append(t)
story.append(Spacer(1, 4))

story.append(Paragraph('<b>关键解读：</b>', s_h2))
story.append(Paragraph('- <b>母婴用品是最大缺口：</b>小柴购2325个母婴SKU中，1370个是10元以下的低价品，297个是引流品。这说明小柴购把母婴做成了低价引流+高频复购的核心战术品类。鹿小仓32个SKU等于没做。', s_body))
story.append(Paragraph('- <b>日用百货虽然差距大，但并非真正弱势：</b>鹿小仓913个日用百货SKU已经不少，且均价27.58元与小柴购27.63元持平。问题在于引流品太少（16 vs 357），不是货不够，是便宜感不够。', s_body))
story.append(Paragraph('- <b>消杀用品缺失值得关注：</b>小柴购144个消杀SKU vs 鹿小仓13个。后疫情时代，消杀品类是社区便利店的信任锚点品类，不应空白。', s_body))
story.append(Paragraph('- <b>宠物用品潜力大：</b>小柴购185个SKU vs 鹿小仓28个。承德养宠人群在增长，这是高毛利品类（鹿小仓加价率258.5%），值得加大投入。', s_body))

story.append(PageBreak())

# Section 3
story.append(Paragraph('三、价格带结构对比', s_h1))
story.append(Paragraph('价格带结构决定了顾客的价格感知。下表展示两个店铺在各价格区间的SKU分布。', s_body))
story.append(Spacer(1, 4))

price_data = [
    ['价格区间', '鹿小仓数量', '鹿小仓占比', '小柴购数量', '小柴购占比', '占比差'],
    ['0-1元', '26', '0.9%', '766', '10.0%', '+9.1%'],
    ['1-5元', '605', '20.6%', '1,668', '21.8%', '+1.2%'],
    ['5-10元', '607', '20.6%', '1,732', '22.6%', '+2.0%'],
    ['10-20元', '714', '24.3%', '1,957', '25.6%', '+1.3%'],
    ['20-50元', '653', '22.2%', '867', '11.3%', '-10.9%'],
    ['50-100元', '225', '7.7%', '333', '4.4%', '-3.3%'],
    ['100-200元', '81', '2.8%', '182', '2.4%', '-0.4%'],
    ['200-500元', '28', '1.0%', '88', '1.2%', '+0.2%'],
    ['500-1000元', '2', '0.1%', '49', '0.6%', '+0.6%'],
    ['1000元+', '0', '0.0%', '6', '0.1%', '+0.1%'],
]
t = make_table(price_data, [25*mm, 25*mm, 22*mm, 25*mm, 22*mm, 22*mm],
              highlight_rows=[(1,'#fff3cd'),(5,'#d4edda'),(6,'#d4edda')])
story.append(t)
story.append(Spacer(1, 4))

story.append(Paragraph('<b>关键解读：</b>', s_h2))
story.append(Paragraph('- <b>0-1元价格带是最大软肋：</b>小柴购766个1元以下SKU vs 鹿小仓26个。这不是几个便宜货的问题，这766个SKU在外卖平台上会贡献大量搜索曝光。顾客搜便宜纸巾、便宜垃圾袋，小柴购出现，鹿小仓不出现。', s_warn))
story.append(Paragraph('- <b>20-50元区间鹿小仓偏重：</b>22.2% vs 11.3%，鹿小仓在这个价位囤了太多SKU。这个价位段是利润区不是流量区，不利于拉新。', s_body))
story.append(Paragraph('- <b>中位售价偏高：</b>鹿小仓12.80元 vs 小柴购9.40元。差3.4元。在同商圈内，这个差距足以让价格敏感型顾客选择小柴购而非鹿小仓。', s_body))

story.append(PageBreak())

# Section 4
story.append(Paragraph('四、引流品策略对比', s_h1))
story.append(Paragraph('<b>引流品是什么？</b>不是亏本卖的商品，而是让顾客觉得这家店便宜的价格锚点。一个店如果有10%的SKU定价在1元以下，顾客的整体价格感知就会偏便宜；反之如果只有1.7%，顾客会觉得这家店贵。', s_body))
story.append(Spacer(1, 4))

flow_data = [
    ['指标', '鹿小仓', '小柴购', '差距'],
    ['引流品总数', '51', '835', '16.4倍'],
    ['引流品占比', '1.7%', '10.9%', '6.4倍'],
    ['引流品均价', '0.75元', '0.51元', '鹿小仓偏高'],
    ['引流品中位价', '0.80元', '0.50元', '鹿小仓偏高'],
    ['', '', '', ''],
    ['日用百货引流', '16', '357', '差341'],
    ['母婴用品引流', '1', '297', '差296'],
    ['日化清洁引流', '11', '43', '差32'],
    ['服饰箱包引流', '3', '48', '差45'],
    ['酒水饮料引流', '6', '28', '差22'],
]
story.append(make_table(flow_data, [35*mm, 30*mm, 30*mm, 65*mm]))
story.append(Spacer(1, 6))

story.append(Paragraph('<b>小柴购的引流策略拆解：</b>', s_h2))
story.append(Paragraph('小柴购的引流品不是随机选的，而是有明确战术: <b>每个品类入口都布满低价锚点</b>。日用百货357个、母婴297个、服饰箱包48个、日化清洁43个。这意味着无论顾客进店找什么品类，第一眼看到的都有1元以下的选项。', s_body))
story.append(Paragraph('更关键的是: <b>母婴引流品297个</b>。宝妈是最高频、最忠诚、客单价最高的客群之一。用297个低价母婴引流品把宝妈拉进店，她们顺手买的其他商品才是利润来源。这是非常成熟的引流品+利润品组合拳。', s_body))

story.append(Spacer(1, 6))
story.append(Paragraph('<b>鹿小仓的引流品问题：</b>', s_h2))
story.append(Paragraph('51个引流品集中在日用百货（16个），其他品类几乎空白。等于除了日百区，其他区域顾客感知不到便宜。引流品均价0.75元也比小柴购0.51元高，同样是引流，小柴购更狠。', s_warn))

story.append(PageBreak())

# Section 5
story.append(Paragraph('五、商品重叠分析', s_h1))
story.append(Paragraph('两店2941+7659个SKU中，经过名称清洗后匹配，<b>仅1个商品重叠</b>（农夫山泉饮用天然水550ml，售价均为2.5元）。重叠率0.03%。', s_body))
story.append(Spacer(1, 4))

story.append(Paragraph('<b>这个数字意味着什么？</b>', s_h2))
story.append(Paragraph('- <b>两店选品完全错位。</b>虽然都在广安购物中心，但卖的东西几乎不重合。这可能是鹿小仓的线上仓店基因导致选品偏向日化/粮油，而小柴购更偏母婴/日用。', s_body))
story.append(Paragraph('- <b>没有直接价格战。</b>这是好事，顾客不会在同一个商品上直接比价。但也是坏事，鹿小仓无法在小柴购的强势品类上截流。', s_body))
story.append(Paragraph('- <b>存在选品盲区。</b>小柴购6927个鹿小仓没有的商品中，4251个是10元以下的低价品。这些可能是鹿小仓根本没考虑过的选品方向，但它们构成了小柴购的便宜感知基础。', s_body))

story.append(Spacer(1, 6))
story.append(Paragraph('<b>小柴购独有商品的品类分布（鹿小仓的选品空白）：</b>', s_h2))
xcg_only_data = [
    ['品类', '独有SKU', '均价', '10元以下', '引流数'],
    ['日用百货', '3,240', '27.6', '1,776', '357'],
    ['母婴用品', '2,325', '23.5', '1,370', '297'],
    ['服饰箱包', '547', '27.2', '257', '48'],
    ['日化清洁', '318', '24.4', '202', '43'],
    ['酒水饮料', '295', '15.2', '188', '28'],
    ['数码配件', '255', '28.3', '89', '9'],
    ['宠物用品', '185', '24.5', '91', '14'],
    ['消杀用品', '144', '23.6', '62', '8'],
    ['休闲零食', '92', '15.1', '63', '11'],
    ['粮油调味', '76', '13.3', '61', '8'],
]
story.append(make_table(xcg_only_data, [28*mm, 22*mm, 20*mm, 25*mm, 20*mm]))

story.append(PageBreak())

# Section 6
story.append(Paragraph('六、鹿小仓毛利结构分析', s_h1))
story.append(Paragraph('小柴购无采购价数据，此部分仅分析鹿小仓。加价率 = (售价-采购价)/采购价 x 100%。', s_body))
story.append(Spacer(1, 4))

margin_data = [
    ['品类', '有毛利SKU', '覆盖率', '均毛利', '中位毛利', '均加价率', '中位加价率', '负毛利'],
    ['日用百货', '807', '88.4%', '15.67', '8.15', '214.4%', '172.7%', '1'],
    ['母婴用品', '27', '84.4%', '33.37', '11.91', '305.9%', '188.8%', '0'],
    ['日化清洁', '615', '90.2%', '11.92', '8.10', '178.1%', '143.5%', '0'],
    ['服饰箱包', '273', '89.8%', '15.61', '9.62', '212.3%', '180.4%', '0'],
    ['酒水饮料', '291', '93.9%', '9.56', '4.83', '144.6%', '100.0%', '0'],
    ['数码配件', '125', '83.9%', '35.34', '20.03', '187.6%', '173.1%', '0'],
    ['粮油调味', '146', '94.2%', '9.51', '5.75', '155.3%', '133.3%', '0'],
    ['宠物用品', '25', '89.3%', '15.52', '7.66', '258.5%', '190.8%', '0'],
    ['休闲零食', '99', '94.3%', '6.45', '4.73', '226.3%', '163.9%', '0'],
    ['消杀用品', '12', '92.3%', '22.47', '20.65', '167.8%', '145.1%', '0'],
    ['文具办公', '111', '90.2%', '7.85', '4.00', '281.2%', '184.3%', '0'],
    ['个护美妆', '88', '89.8%', '16.95', '11.68', '174.4%', '157.9%', '0'],
    ['生鲜果蔬', '20', '83.3%', '26.05', '5.55', '198.7%', '163.6%', '0'],
    ['速食冷冻', '3', '60.0%', '6.35', '7.00', '211.8%', '190.4%', '0'],
]
story.append(make_table(margin_data, [22*mm, 18*mm, 16*mm, 16*mm, 16*mm, 18*mm, 18*mm, 14*mm]))
story.append(Spacer(1, 6))

story.append(Paragraph('<b>关键发现：</b>', s_h2))
story.append(Paragraph('- <b>整体毛利结构健康。</b>14个品类仅1个负毛利SKU（衣夹，采购价4.66售价1元，应为数据错误或清仓处理）。采购价覆盖率89.8%，多数品类加价率在150%-280%之间，合理。', s_ok))
story.append(Paragraph('- <b>酒水饮料加价率最低（中位100%）。</b>这是正常的，饮料是大牌通货，价格透明，本就该低毛利跑量。但这也意味着酒水是引流品类而非利润品类。', s_body))
story.append(Paragraph('- <b>母婴用品加价率最高（中位188.8%，均值305.9%）。</b>这恰恰说明母婴是高毛利品类，鹿小仓只有32个SKU却在赚高毛利，如果扩到200-300个SKU，利润空间巨大。', s_ok))
story.append(Paragraph('- <b>休闲零食毛利偏低（均毛利6.45元）。</b>但零食是高频品类，跑量比跑利重要。', s_body))

story.append(PageBreak())

# Section 7
story.append(Paragraph('七、商圈与竞品环境', s_h1))
story.append(Paragraph('承德市南营子大街是承德市双桥区最核心的商业街，承载承德商业老城中心地位。周边主要商业体包括：', s_body))
story.append(Spacer(1, 4))

biz_data = [
    ['商业体', '位置', '业态', '竞争关系'],
    ['广安购物中心', '南营子大街30号', '社区购物中心', '鹿小仓和小柴购所在位'],
    ['承德商城', '南营子大街11号', '百货+宽广超市', '底商超市竞争'],
    ['德汇大厦', '火神庙', '百货+宽广超市', '底商超市竞争'],
    ['名都广场', '二仙居西街', '商业广场+宽广超市', '底商超市竞争'],
    ['双百购物广场', '新华路', '中高端购物中心', '差异定位'],
    ['金龙购物中心', '南营子大街', '综合购物中心', '差异定位'],
    ['万达广场', '迎宾路', '大型综合体', '差异化竞争'],
]
story.append(make_table(biz_data, [30*mm, 35*mm, 35*mm, 50*mm]))
story.append(Spacer(1, 6))

story.append(Paragraph('<b>商圈特征：</b>', s_h2))
story.append(Paragraph('- <b>南营子大街是承德商业第一街</b>，人流量大但以中老年居民和本地工薪阶层为主，消费力中等偏上。', s_body))
story.append(Paragraph('- <b>宽广超市是承德本地连锁巨头</b>，在南营子大街有3家店（德汇店、商城店、名都店），是最大的超市竞争者。', s_body))
story.append(Paragraph('- <b>广安购物中心内部</b>同时存在鹿小仓和小柴购两个线上便利店/仓店，直接竞争关系明确。', s_body))
story.append(Paragraph('- <b>消费特征：</b>承德是旅游城市（避暑山庄），但南营子大街主要服务本地居民，非游客区。客群稳定但消费力有天花板。', s_body))

story.append(PageBreak())

# Section 8
story.append(Paragraph('八、改进建议（可执行行动清单）', s_h1))

story.append(Paragraph('<b>优先级 P0 - 立即执行（1-2周内）</b>', s_h2))
story.append(Paragraph('<b>1. 引流品紧急扩充计划</b>', s_body))
story.append(Paragraph('目标：从51个引流品扩充到300个以上，覆盖每个品类至少20个。', s_body))
story.append(Paragraph('执行方式：从现有SKU中筛选售价2元以下的商品，标记为引流品；同时采购一批0.1-1元的低价小商品（垃圾袋、橡皮筋、便签纸、小零食等），每个品类至少上架20个。', s_body))
story.append(Paragraph('预期效果：外卖平台搜索曝光提升30%+，顾客便宜感知显著改善。', s_body))
story.append(Spacer(1, 4))

story.append(Paragraph('<b>2. 0-1元价格带补齐</b>', s_body))
story.append(Paragraph('目标：0-1元SKU从26个扩充到200个以上。', s_body))
story.append(Paragraph('这是外卖平台搜索排序的关键权重区。小柴购766个1元以下SKU是它线上能力强的核心原因之一。', s_body))

story.append(Spacer(1, 6))
story.append(Paragraph('<b>优先级 P1 - 2-4周内执行</b>', s_h2))
story.append(Paragraph('<b>3. 母婴品类搭建</b>', s_body))
story.append(Paragraph('目标：从32个SKU扩充到300-500个，优先补齐婴儿湿巾、奶瓶、安抚奶嘴、婴儿洗护、儿童餐具等高频低价品类。', s_body))
story.append(Paragraph('原因：母婴是高毛利（加价率188%+）、高频复购、高忠诚度品类。小柴购2325个母婴SKU说明这个品类在广安购物中心有需求。鹿小仓不需要做到2000+，但300个基础SKU是底线。', s_body))
story.append(Spacer(1, 4))

story.append(Paragraph('<b>4. 消杀用品扩充</b>', s_body))
story.append(Paragraph('目标：从13个SKU扩充到80-100个。', s_body))
story.append(Paragraph('补齐蟑螂药、蚊香、除霉剂、管道疏通剂、消毒液等家庭刚需品。这些是急需购买品类，线上搜索转化率极高。', s_body))

story.append(Spacer(1, 4))
story.append(Paragraph('<b>5. 宠物用品扩充</b>', s_body))
story.append(Paragraph('目标：从28个SKU扩充到100-150个。', s_body))
story.append(Paragraph('高毛利（258%）、低竞争（承德宠物店少）。补齐猫粮、狗粮、猫砂、宠物零食、牵引绳等基础品类。', s_body))

story.append(Spacer(1, 6))
story.append(Paragraph('<b>优先级 P2 - 1-2月内执行</b>', s_h2))
story.append(Paragraph('<b>6. 价格带下沉调整</b>', s_body))
story.append(Paragraph('目标：中位售价从12.80元降到10-11元区间。', s_body))
story.append(Paragraph('方式：不是全面降价，而是增加低价SKU数量来拉低中位数。20-50元区间占比从22.2%降到15%左右，释放的货架空间给1-10元区间。', s_body))
story.append(Spacer(1, 4))

story.append(Paragraph('<b>7. 速食冷冻扩充</b>', s_body))
story.append(Paragraph('目标：从5个SKU扩充到50-80个。', s_body))
story.append(Paragraph('便利店的核心差异化品类。速食（关东煮、烤肠、三明治、便当）是实体店对抗纯线上的最大武器，小柴购在这方面也不强（47个），是双方都在空白的机会点。', s_body))

story.append(Spacer(1, 6))
story.append(Paragraph('<b>优先级 P3 - 实体开店前必须完成</b>', s_h2))
story.append(Paragraph('<b>8. 选品差异化定位</b>', s_body))
story.append(Paragraph('既然两店重叠率只有0.03%，说明鹿小仓的选品DNA和小柴购天然不同。开实体店时不要去模仿小柴购的7659个SKU全量铺货，那是它的打法。鹿小仓的实体店应该聚焦300个精选SKU + 10-20个独家特色品，用精选感和故事感打差异。', s_body))
story.append(Paragraph('但线上仓店的SKU可以继续扩充，因为线上不受物理空间限制。', s_body))

story.append(PageBreak())

# Section 9
story.append(Paragraph('九、总结', s_h1))
story.append(Spacer(1, 6))
story.append(Paragraph('<b>鹿小仓 vs 小柴购的核心差异不是货不够多，而是引流火力太弱和品类结构有盲区。</b>', s_body))
story.append(Spacer(1, 4))

story.append(Paragraph('<b>小柴购强在哪：</b>', s_h2))
story.append(Paragraph('1. SKU广度碾压（7659 vs 2941），尤其在母婴和日用百货', s_body))
story.append(Paragraph('2. 引流品体系成熟（835个，占10.9%），每个品类入口都有低价锚点', s_body))
story.append(Paragraph('3. 0-1元价格带铺满（766个），外卖搜索权重高', s_body))
story.append(Paragraph('4. 母婴品类做成核心战术品类（2325个SKU + 297个引流品）', s_body))

story.append(Spacer(1, 4))
story.append(Paragraph('<b>鹿小仓强在哪：</b>', s_h2))
story.append(Paragraph('1. 日化清洁品类领先（682 vs 318，2.1倍优势）', s_body))
story.append(Paragraph('2. 酒水饮料、粮油调味、休闲零食、文具办公四个品类SKU更丰富', s_body))
story.append(Paragraph('3. 毛利结构健康，加价率合理，几乎无负毛利', s_body))
story.append(Paragraph('4. 选品与小柴购完全错位，没有直接价格战压力', s_body))

story.append(Spacer(1, 4))
story.append(Paragraph('<b>最紧急的三件事：</b>', s_h2))
story.append(Paragraph('1. 引流品扩充到300+（1周内）', s_warn))
story.append(Paragraph('2. 0-1元价格带补齐到200+（2周内）', s_warn))
story.append(Paragraph('3. 母婴品类扩到300+ SKU（4周内）', s_warn))

story.append(Spacer(1, 8))
story.append(Paragraph('- 数据来源：鹿小仓广安店库存合并总表（2941条SKU） 和 小柴购全量数据表v5（7659条SKU）', s_small))
story.append(Paragraph('- 分析工具：Python + pandas | 报告生成：reportlab', s_small))
story.append(Paragraph('- 生成时间：2026-07-10', s_small))

doc.build(story)
print('PDF generated: ' + OUT)
