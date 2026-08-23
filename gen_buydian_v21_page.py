# -*- coding: utf-8 -*-
"""生成 V2.1 买点区域网页: 每日 S/A/B 级买点"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "out")

by_date = json.load(open(os.path.join(OUT, 'buydian_v21_daily.json'), encoding='utf-8'))
meta = json.load(open(os.path.join(OUT, 'meta.json'), encoding='utf-8'))
blocks = json.load(open(os.path.join(OUT, 'stock_blocks.json'), encoding='utf-8'))

GENERIC = {'融资融券','深股通','沪股通','创业板综','央国企改革','富时罗素','标准普尔',
  '机构重仓','小盘股','破增发价股','QFII重仓','MSCI中国','HS300_','上证50_','上证180_',
  '深证100R','深成500','创业成份','央视50_','茅指数','百元股','东方财富热股','行业龙头',
  '权重股','大盘股','消费风格','乡村振兴','AH股','证金持股','破净股','红利破净股','周期股',
  '红利股','大盘价值','大盘成长','先进制造风格','金融地产风格','参股券商','参股银行',
  'IPO受益','独角兽','区块链','深圳特区','电商概念','西部大开发','超级品牌','宁组合','储能概念',
  '昨日涨停_含一字','昨日涨停','昨日高振幅','昨日高换手','近期新高','百日新高','历史新高',
  '趋势股','题材股','高市净率','贬值受益','昨涨停_含一字','今破新高','均线多头'}
IND_NAMES = {'医药生物','基础化工','电力设备','食品饮料','非银金融','银行','电子','计算机',
  '机械设备','汽车','有色金属','钢铁','煤炭','石油石化','公用事业','交通运输','房地产',
  '建筑装饰','建筑材料','家用电器','纺织服饰','轻工制造','商贸零售','社会服务','农林牧渔',
  '国防军工','通信','传媒','环保','美容护理','综合','其他塑料制品','其他生物制品','塑料','电池',
  '酿酒','白酒','化学制药','生物制品'}

def industry_of(sym):
    blk = blocks.get(sym, [])
    if not blk: return ''
    return blk[0]

# 汇总: 每日期S/A/B/C数量
summ = {}
for date, lst in by_date.items():
    c = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
    for r in lst:
        if r['level'] in c: c[r['level']] += 1
    summ[date] = c

dates = sorted(by_date.keys())
data = {'dates': dates, 'daily': by_date, 'sum': summ, 'gen': '2026-08-22'}

# 生成JS数据文件
with open(os.path.join(BASE, 'buydian_v21_data.js'), 'w', encoding='utf-8') as f:
    f.write('window.BD21_DATA = ')
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    f.write(';')

print('buydian_v21_data.js:', os.path.getsize(os.path.join(BASE, 'buydian_v21_data.js')) // 1024, 'KB')
print('dates:', len(dates), 'latest:', dates[-1] if dates else 'N/A')
# 全年统计
tot = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
for date, lst in by_date.items():
    for r in lst:
        if r['level'] in tot: tot[r['level']] += 1
print('全年信号: S=%d A=%d B=%d C=%d' % (tot['S'], tot['A'], tot['B'], tot['C']))
