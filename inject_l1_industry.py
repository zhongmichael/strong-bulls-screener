# -*- coding: utf-8 -*-
"""给 strong_data.js 的 meta 数组注入 一级行业(索引5), 不重算 strong 行。
仅重写 meta 部分, 其余字段(strong/dates/sum/gen)原样保留。
用法: python3 inject_l1_industry.py [文件...]
"""
import json
import sys

L1_ORDER = ['农林牧渔','基础化工','钢铁','有色金属','电子','汽车','家用电器','食品饮料','纺织服饰','轻工制造','医药生物','公用事业','交通运输','房地产','商贸零售','社会服务','综合','建筑材料','建筑装饰','电力设备','国防军工','计算机','传媒','通信','银行','非银金融','美容护理','煤炭','石油石化','环保','机械设备']
L1_SET = set(L1_ORDER)


def l1_of(blk):
    if not blk:
        return ''
    for x in blk:
        if x in L1_SET:
            return x
    return ''


def inject(path, blocks, dry=False):
    src = open(path, encoding='utf-8').read()
    eq = src.index('=') + 1
    tail = src[eq:]
    semi = tail.rfind(';')
    j = json.loads(tail[:semi] if semi >= 0 else tail)
    meta = j.get('meta', {})
    n_empty_before = sum(1 for v in meta.values() if len(v) <= 3 or not v[3])
    n_added = n_no_blk = 0
    for sym, arr in meta.items():
        while len(arr) < 5:
            arr.append('')
        if len(arr) < 6 or not arr[5]:
            blk = blocks.get(sym, [])
            l1 = l1_of(blk)
            if len(arr) < 6:
                arr.append(l1)
            else:
                arr[5] = l1
            if l1:
                n_added += 1
            else:
                n_no_blk += 1
    n_empty_after = sum(1 for v in meta.values() if not v[5] if len(v) > 5)
    if not dry:
        out = 'window.STRONG_DATA = ' + json.dumps(j, ensure_ascii=False, separators=(',', ':')) + ';\n'
        open(path, 'w', encoding='utf-8').write(out)
    print(f"  {path}: 注入一级 {n_added}, 仍无板块 {n_no_blk}; meta细分空 {n_empty_before} -> 一级空 {n_empty_after}")


def main():
    files = sys.argv[1:] or ['strong_data.js', 'dist_strong/strong_data.js']
    blocks = json.load(open('data/out/stock_blocks.json', encoding='utf-8'))
    for fp in files:
        inject(fp, blocks)


if __name__ == '__main__':
    main()
