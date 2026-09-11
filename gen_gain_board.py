# -*- coding: utf-8 -*-
"""
涨幅榜生成器: 年度/半年度/季度/月度涨幅 TOP50
=============================================
- 年度: 2025-12-31 收盘 -> 最新 (2026 YTD)
- 半年度: 近120个交易日
- 季度: 近60个交易日
- 月度: 近20个交易日
范围: 默认强势股池(规则D)内, 也输出全市场供切换
输出: gain_board.js
"""
import json, glob, os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "out")

def main():
    strong = json.load(open(os.path.join(OUT, 'strong_2026.json'), encoding='utf-8'))
    meta = json.load(open(os.path.join(OUT, 'meta.json'), encoding='utf-8'))
    blocks = json.load(open(os.path.join(OUT, 'stock_blocks.json'), encoding='utf-8'))
    latest_date = sorted(strong.keys())[-1]
    print('最新交易日:', latest_date)

    # 强势池(最新日规则D)
    day = strong.get(latest_date, {})
    pool = {s for s, r in day.items() if r[15] >= 7 and (r[16] >= 6 or r[3] >= 50)}

    # 行业
    def ind_of(sym):
        blk = blocks.get(sym, [])
        return blk[0] if blk else ''

    records = {'year': [], 'half': [], 'quarter': [], 'month': []}
    n_ok = 0
    for fp in glob.glob(os.path.join(BASE, 'data', 'kline', '*.json')):
        sym = os.path.basename(fp)[:-5]
        try:
            bars = json.load(open(fp, encoding='utf-8'))['bars']
        except Exception:
            continue
        if len(bars) < 130:
            continue
        closes = [float(b[2]) for b in bars]
        dates = [b[0] for b in bars]
        latest_close = closes[-1]
        if latest_close <= 0:
            continue
        name = (meta.get(sym) or {}).get('name', sym)
        ind = ind_of(sym)
        in_pool = sym in pool

        # 年度: 2025-12-31收盘
        base_y = None
        for i, dt in enumerate(dates):
            if dt >= '2026-01-01':
                if i > 0:
                    base_y = closes[i-1]
                break
        # 近120/60/20交易日
        base_h = closes[-121] if len(closes) > 121 else None
        base_q = closes[-61] if len(closes) > 61 else None
        base_m = closes[-21] if len(closes) > 21 else None

        item = {'c': sym, 'n': name, 'close': round(latest_close, 2), 'ind': ind, 'in_pool': in_pool}
        if base_y:  item['y'] = round((latest_close/base_y - 1) * 100, 2)
        if base_h:  item['h'] = round((latest_close/base_h - 1) * 100, 2)
        if base_q:  item['q'] = round((latest_close/base_q - 1) * 100, 2)
        if base_m:  item['m'] = round((latest_close/base_m - 1) * 100, 2)
        records['year'].append(item)
        records['half'].append(item)
        records['quarter'].append(item)
        records['month'].append(item)
        n_ok += 1

    # 排序取TOP50 (分别: 强势池内 / 全市场)
    def top(items, key):
        valid = [x for x in items if x.get(key) is not None]
        valid.sort(key=lambda x: x[key], reverse=True)
        return valid[:50]

    out = {
        'date': latest_date,
        'periods': {}
    }
    for p, k in [('year', 'y'), ('half', 'h'), ('quarter', 'q'), ('month', 'm')]:
        all_list = top(records[p], k)
        pool_list = [x for x in records[p] if x.get('in_pool') and x.get(k) is not None]
        pool_list.sort(key=lambda x: x[k], reverse=True)
        pool_list = pool_list[:50]
        out['periods'][p] = {'all': all_list, 'pool': pool_list}
        print(f'{p}: 全市场TOP{len(all_list)} 冠军{all_list[0]["n"]}+{all_list[0][k]}% | 强势池内TOP{len(pool_list)} 冠军{pool_list[0]["n"]}+{pool_list[0][k]}%')

    with open(os.path.join(BASE, 'gain_board.js'), 'w', encoding='utf-8') as f:
        f.write('window.GAIN_BOARD = ')
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';')
    print('gain_board.js:', os.path.getsize(os.path.join(BASE, 'gain_board.js')) // 1024, 'KB')

    # ===== 年度K线(仅日期+收盘) 供浏览器动态计算月度涨幅 =====
    # 结构: {sym: [[date, close], ...]} 2026全年 (含2025-12-31做月初基准)
    yk = {}
    for fp in glob.glob(os.path.join(BASE, 'data', 'kline', '*.json')):
        sym = os.path.basename(fp)[:-5]
        try:
            bars = json.load(open(fp, encoding='utf-8'))['bars']
        except Exception:
            continue
        seq = [[b[0], round(float(b[2]), 2)] for b in bars if b[0] >= '2025-06-01']
        if seq:
            yk[sym] = seq
    with open(os.path.join(BASE, 'year_kline.js'), 'w', encoding='utf-8') as f:
        f.write('window.YEAR_KLINE = ')
        json.dump(yk, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';')
    print('year_kline.js:', os.path.getsize(os.path.join(BASE, 'year_kline.js')) // 1024, 'KB')

if __name__ == '__main__':
    main()
