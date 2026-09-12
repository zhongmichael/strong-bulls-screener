# -*- coding: utf-8 -*-
"""
概念题材映射生成器
==================
从 data/out/stock_blocks.json 抽取「概念题材」标签, 输出 sector_ref.js 供前端聚合板块统计。

输出结构:
    window.SECTOR_NAMES = ["光通信模块","PCB",...]      # 概念名表(去重, 按覆盖股票数降序)
    window.SECTOR_MAP   = {"sh600519":[3,17,42],...}    # 个股 -> 概念索引数组

过滤掉的标签(它们不是「概念题材」):
  - 申万一级行业 31 个(走 meta[sym][3]/[5], 不混入概念)
  - 申万二/三级: 个股标签中「地域标签(XX板块/XX特区)之前」的那些
  - 地域板块(XX板块 / XX特区 / 自贸 / 新区)
  - 指数与风格成分(HS300_/上证50_/大盘股/茅指数/融资融券/百元股 ...)
  - 财报与状态类(2026中报预增 / 昨日涨停 / 破净股 ...)

用法: python3 gen_sector_ref.py     (离线跑一次即可, 板块归属变化很慢)
"""
import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "out")

L1 = set(['农林牧渔', '基础化工', '钢铁', '有色金属', '电子', '汽车', '家用电器', '食品饮料',
          '纺织服饰', '轻工制造', '医药生物', '公用事业', '交通运输', '房地产', '商贸零售',
          '社会服务', '综合', '建筑材料', '建筑装饰', '电力设备', '国防军工', '计算机',
          '传媒', '通信', '银行', '非银金融', '美容护理', '煤炭', '石油石化', '环保', '机械设备'])

REGION = re.compile(r'板块$|特区$|自贸|新区$')
META1 = re.compile(r'^(HS300|上证|深证|中证|创业板|科创|MSCI|富时|标准普尔|央视|茅指数|宁组合'
                   r'|深成|沪股通|深股通|创业成份|深证100R|A50|北证|中概|GDR)')
META2 = re.compile(r'风格$|股$|重仓$|持股$|标的$|成份$|成分$|_$')
META3 = re.compile(r'^(大盘|中盘|小盘|权重|行业龙头|高送转|股权激励|预盈|预亏|央企|国企改革$'
                   r'|北上资金|机构重仓|基金重仓|QFII|社保重仓|券商金股|昨日|今日|新股|热股'
                   r'|次新股|百元股|低价股|ST股|超跌股|破增发价|破净股|AH股|融资融券|转债标的'
                   r'|周期股|成长股|价值股|注册制|含B股|含H股|独角兽|高市净率|低市净率'
                   r'|高市盈率|低市盈率|乡村振兴$)')
FIN = re.compile(r'^\d{4}(中报|年报|一季|三季|半年报)')


def main():
    blocks = json.load(open(os.path.join(OUT, 'stock_blocks.json'), encoding='utf-8'))

    # 1) 申万二/三级 = 个股标签里「地域标签之前」的那些(顺序不定但都排在地域前)
    sw23 = set()
    for sym, blk in blocks.items():
        for b in blk[:4]:
            if REGION.search(b):
                break
            if b not in L1:
                sw23.add(b)

    def keep(b):
        if b in L1 or b in sw23:
            return False
        if REGION.search(b) or META1.search(b) or META2.search(b) or META3.search(b) or FIN.search(b):
            return False
        return True

    # 2) 逐股抽取概念
    per_sym = {}
    freq = {}
    for sym, blk in blocks.items():
        cs = [b for b in blk if keep(b)]
        if not cs:
            continue
        per_sym[sym] = cs
        for c in cs:
            freq[c] = freq.get(c, 0) + 1

    # 3) 概念名表按覆盖股票数降序(前端做 TOP10 时天然优先常见题材)
    names = sorted(freq.keys(), key=lambda k: (-freq[k], k))
    idx = {n: i for i, n in enumerate(names)}
    smap = {sym: [idx[c] for c in cs] for sym, cs in per_sym.items()}

    js = ('window.SECTOR_NAMES=' + json.dumps(names, ensure_ascii=False, separators=(',', ':')) + ';\n'
          + 'window.SECTOR_MAP=' + json.dumps(smap, ensure_ascii=False, separators=(',', ':')) + ';\n')
    p = os.path.join(BASE, 'sector_ref.js')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(js)

    cov = [len(v) for v in smap.values()]
    print('概念题材 %d 个 | 覆盖个股 %d 只' % (len(names), len(smap)))
    print('每只股票概念数: 中位 %d, 最少 %d, 最多 %d' % (
        sorted(cov)[len(cov) // 2], min(cov), max(cov)))
    print('sector_ref.js: %d KB' % (os.path.getsize(p) // 1024))
    print('TOP15 概念(按覆盖数):', ' '.join('%s(%d)' % (n, freq[n]) for n in names[:15]))


if __name__ == '__main__':
    main()
