# -*- coding: utf-8 -*-
"""
每日强势股池 × 买点区域选股器 V2.1 算法
=========================================
门禁: 当前项目规则D强势池 (周线近10周≥7站上周MA5 且 (月线≥6 或 强度≥50)), 每日动态更新
算法: V2.1 (买点区域选股器V2.1-实时版 gen_v2_live.py computeCode 移植)

V2.1 分级:
  S级: 回踩MA60 + Trigger + 周线共振 + 缩量  -> 核心买点
  A级: 回踩MA60 + Trigger                     -> 试仓
  B级: 回踩MA60 但 Trigger 未确认             -> 观察
  C级: 低9 / RSI<30 (非核心, 仅记录)
  排除: 实体大阴线跌超5%
"""
import json
import glob
import os
import time
import numpy as np
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
KLINE = os.path.join(BASE, "data", "kline")
OUT = os.path.join(BASE, "data", "out")

def ma_part(vals, n):
    """与JS maPart一致: 前n-1个用部分均值, 之后用完整均值"""
    out = np.zeros(len(vals))
    s = 0.0
    for i in range(len(vals)):
        s += vals[i]
        if i >= n:
            s -= vals[i - n]
        out[i] = s / min(i + 1, n)
    return out

def atr14(h, l, c):
    n = len(c)
    tr = np.zeros(n)
    for i in range(n):
        if i == 0:
            tr[i] = h[i] - l[i]
        else:
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr = np.zeros(n)
    s = 0.0
    for i in range(n):
        s += tr[i]
        if i >= 14:
            s -= tr[i-14]
        atr[i] = s / min(i + 1, 14)
    return atr

def rsi14(c):
    n = len(c)
    out = np.full(n, np.nan)
    if n < 15:
        return out
    ag = al = 0.0
    for i in range(1, 15):
        chg = c[i] - c[i-1]
        ag += max(chg, 0)
        al += max(-chg, 0)
    ag /= 14; al /= 14
    out[14] = 100 if al == 0 else 100 - 100 / (1 + ag/al)
    for i in range(15, n):
        chg = c[i] - c[i-1]
        ag = (ag * 13 + max(chg, 0)) / 14
        al = (al * 13 + max(-chg, 0)) / 14
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag/al)
    return out

def nine_cnt(c):
    n = len(c)
    cnt = np.zeros(n, dtype=int)
    for i in range(4, n):
        if c[i] < c[i-4]:
            cnt[i] = cnt[i-1] + 1 if cnt[i-1] > 0 else 1
        else:
            cnt[i] = 0
    return cnt

def is_stab(o, c, h, l):
    body = abs(c - o)
    lower = min(o, c) - l
    upper = h - max(o, c)
    rng = (h - l) or 0.01
    if body <= 0.004 * c:
        return True
    if lower >= 2 * body and lower >= 0.4 * rng and upper <= 0.35 * rng:
        return True
    if c > o and lower >= 0.5 * rng:
        return True
    return False

def bisect_right(arr, v):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[mid] <= v:
            lo = mid + 1
        else:
            hi = mid
    return lo

LEVELS = [['M5', 5], ['M10', 10], ['M20', 20], ['M30', 30], ['M52', 52], ['M60', 60]]

def wma(closes, idx, n):
    if idx + 1 < n:
        return None
    return sum(closes[idx-n+1:idx+1]) / n

def week_label(closes, idx):
    """与JS weekLabel一致"""
    c = closes[idx]
    devs = {}
    for nm, nn in LEVELS:
        m = wma(closes, idx, nn)
        devs[nm] = (c / m - 1) * 100 if m else None
    hits = []
    for nm, nn in LEVELS:
        d = devs[nm]
        if d is not None and abs(d) <= 2:
            hits.append([nm, d])
    if hits:
        hits.sort(key=lambda x: abs(x[1]))
        nm2 = hits[0][0]
        cls = 'red' if nm2 in ('M52', 'M60') else 'blue'
        return {'lab': '回踩' + nm2, 'cls': cls}
    for nm, nn in reversed(LEVELS):
        d3 = devs[nm]
        if d3 is not None and d3 < 0:
            return {'lab': '跌破' + nm, 'cls': 'down'}
    d10 = devs['M10']
    if d10 is not None:
        sign = '+' if d10 >= 0 else ''
        return {'lab': sign + str(int(round(d10))) + '%', 'cls': 'flat'}
    return {'lab': '—', 'cls': 'flat'}

def compute_code(sym, name, day_rows, week_rows, month_rows):
    """V2.1 computeCode 移植. 返回 {date: rec} 或 None"""
    # 日线序列
    dates = [r[0] for r in day_rows]
    o = np.array([float(r[1]) for r in day_rows])
    c = np.array([float(r[2]) for r in day_rows])
    h = np.array([float(r[3]) for r in day_rows])
    l = np.array([float(r[4]) for r in day_rows])
    v = np.array([float(r[5]) if len(r) > 5 else 0 for r in day_rows])
    n = len(c)
    if n < 130:
        return None
    m5 = ma_part(c, 5); m10 = ma_part(c, 10); m20 = ma_part(c, 20)
    m30 = ma_part(c, 30); m60 = ma_part(c, 60); m120 = ma_part(c, 120); m250 = ma_part(c, 250)
    s = 0.0
    start = max(0, n - 250)
    for k in range(start, n):
        s += c[k]
    ma250approx = s / (n - start)
    atr = atr14(h, l, c)
    rsi = rsi14(c)
    vma5 = ma_part(v, 5); vma20 = ma_part(v, 20)
    nine = nine_cnt(c)
    # 周线
    wdates = [r[0] for r in week_rows]
    wcloses = [float(r[2]) for r in week_rows]
    wma5 = ma_part(np.array(wcloses), 5)
    wma10 = ma_part(np.array(wcloses), 10)
    wma20 = ma_part(np.array(wcloses), 20)
    # 月线
    mdates = [r[0] for r in month_rows]
    mcloses = [float(r[2]) for r in month_rows]
    mma5 = ma_part(np.array(mcloses), 5)
    mma10 = ma_part(np.array(mcloses), 10)

    out = {}
    for i in range(n):
        dt = dates[i]
        if dt < '2026-01-01':
            continue
        cv = c[i]
        a5, a10, a20, a30, a60, a120 = m5[i], m10[i], m20[i], m30[i], m60[i], m120[i]
        atrV = atr[i]
        if atrV <= 0:
            continue
        # 趋势分
        ts = 0
        if a5 > a10: ts += 10
        if a10 > a20: ts += 10
        if a20 > a60: ts += 15
        if a60 > a120: ts += 15
        if i >= 5 and m60[i] > m60[i-5]: ts += 10
        if i >= 5 and m120[i] > m120[i-5]: ts += 10
        widx = bisect_right(wdates, dt) - 1
        weekMa10Up = (widx >= 4) and (wma10[widx] > wma10[widx-4])
        if weekMa10Up: ts += 10
        midx = bisect_right(mdates, dt) - 1
        monthBull = (midx >= 0) and (mma5[midx] > mma10[midx])
        if monthBull: ts += 10
        if cv > ma250approx: ts += 10

        bull_align = (a5 > a10 and a10 > a20 and a20 > a60 and a60 > a120) \
            and (i >= 5 and m20[i] > m20[i-5]) and (m60[i] > m60[i-5])
        osc_up = (a20 > a60 and a60 > a120) and (i >= 5 and m60[i] > m60[i-5]) and (m120[i] >= m120[i-5])
        align = 'bull' if bull_align else ('osc' if osc_up else 'none')

        wm = {'w5': wma5[widx], 'w10': wma10[widx], 'w20': wma20[widx], 'wc': wcloses[widx]}
        week_strong = (widx >= 0) and (wm['w5'] > wm['w10'] and wm['w10'] > wm['w20']) and (wm['wc'] > wm['w20'])
        day_strong = (a20 > a60 and a60 > a120) and (i >= 5 and m60[i] > m60[i-5]) and (m120[i] >= m120[i-5])
        month_strong = monthBull
        if not (day_strong and week_strong and month_strong):
            continue

        dists = {
            'MA5': abs(cv - a5) / atrV, 'MA10': abs(cv - a10) / atrV,
            'MA20': abs(cv - a20) / atrV, 'MA30': abs(cv - a30) / atrV,
            'MA60': abs(cv - a60) / atrV, 'MA120': abs(cv - a120) / atrV}
        ma60_pullback = dists['MA60'] <= 1.0
        primary = 'MA60' if ma60_pullback else None

        shrink = vma5[i] < vma20[i] * 0.8
        ma_up = False
        if primary:
            ma_up = (i >= 5) and (m60[i] >= m60[i-5])
        stable = is_stab(o[i], cv, h[i], l[i])
        breakout = (i >= 1) and (cv > h[i-1]) and (v[i] >= vma5[i] * 1.0)
        trig_cnt = (1 if shrink else 0) + (1 if ma_up else 0) + (1 if stable else 0)
        trigger_ok = trig_cnt >= 2

        low9 = nine[i] >= 9
        low8 = nine[i] == 8
        wst = week_label(wcloses, widx) if widx >= 0 else None
        week_hit = (wst['lab'] if (wst and (wst['cls'] == 'red' or wst['cls'] == 'blue')) else None)
        resonate = (primary is not None) and (week_hit is not None)

        seg_low = min(l[max(0, i-19):i+1])
        stop = seg_low
        hi60 = max(h[max(0, i-59):i+1])
        resistance = hi60
        risk = cv - stop
        rr = (resistance - cv) / risk if risk > 0 else None

        bs = 0
        if ts >= 90: bs += 10
        elif ts >= 80: bs += 5
        if shrink: bs += 10
        if ma_up: bs += 10
        if stable: bs += 15
        if breakout: bs += 10

        level = None
        if ma60_pullback and trigger_ok:
            level = 'S' if (resonate and shrink) else 'A'
        elif ma60_pullback and not trigger_ok:
            level = 'B'
        elif low9 or (rsi[i] is not None and not np.isnan(rsi[i]) and rsi[i] < 30):
            level = 'C'
        chg = (cv / c[i-1] - 1) * 100 if i >= 1 else 0
        big_bear = (chg <= -5) and (cv < o[i])
        if big_bear:
            level = None

        rec = {
            'c': sym, 'n': name, 'close': round(float(cv), 2),
            'trend_score': int(ts), 'align': align, 'primary_ma': primary,
            'pullback_dist': round(float(dists['MA60']), 2) if primary else None,
            'shrink': bool(shrink), 'ma_up': bool(ma_up), 'stable': bool(stable),
            'breakout': bool(breakout), 'trigger_ok': bool(trigger_ok), 'trig_cnt': int(trig_cnt),
            'low9': bool(low9), 'low8': bool(low8), 'week_hit': week_hit,
            'resonate': bool(resonate), 'buy_score': int(bs), 'level': level,
            'stop': round(float(stop), 2), 'resistance': round(float(resistance), 2),
            'rr': round(float(rr), 2) if rr is not None else None,
            'rsi14': round(float(rsi[i]), 1) if not np.isnan(rsi[i]) else None,
            'dev60': round((float(cv) / float(a60) - 1) * 100, 1)}
        out[dt] = rec
    return out

def process_stock(fp):
    sym = os.path.basename(fp)[:-5]
    try:
        with open(fp, encoding='utf-8') as f:
            d = json.load(f)
        day_rows = d['bars']
        if len(day_rows) < 130:
            return sym, None
        name = sym
        # 尝试加载名称 (meta.json 或 all_stock_names)
        try:
            meta = json.load(open(os.path.join(OUT, 'meta.json'), encoding='utf-8'))
            name = (meta.get(sym) or {}).get('name', sym)
        except Exception:
            pass
        # 聚合周/月K (与compute_strong逻辑一致: 收盘聚合)
        wkeys, wrows = [], []
        cur = None
        for r in day_rows:
            dt = datetime.strptime(r[0], '%Y-%m-%d').date()
            iso = dt.isocalendar()
            wk = iso[0] * 100 + iso[1]
            if wk != cur:
                wkeys.append(wk); wrows.append([r[0], r[1], r[2], r[3], r[4], r[5]])
                cur = wk
            else:
                wrows[-1] = [r[0], r[1], r[2], r[3], r[4], r[5]]
        mkeys, mrows = [], []
        cur = None
        for r in day_rows:
            dt = datetime.strptime(r[0], '%Y-%m-%d').date()
            mk = dt.year * 100 + dt.month
            if mk != cur:
                mkeys.append(mk); mrows.append([r[0], r[1], r[2], r[3], r[4], r[5]])
                cur = mk
            else:
                mrows[-1] = [r[0], r[1], r[2], r[3], r[4], r[5]]
        # 只对"当日属于强势池"的日期计算? 不——V2.1有自身门禁, 但用户要求: 用当前项目强势池做门禁
        # 方案: 先算全部日期, 再按强势池过滤
        return sym, compute_code(sym, name, day_rows, wrows, mrows)
    except Exception as e:
        return sym, None

def main():
    t0 = time.time()
    # 加载当前项目强势池 (规则D, 每日)
    strong = json.load(open(os.path.join(OUT, 'strong_2026.json')))
    meta = json.load(open(os.path.join(OUT, 'meta.json')))
    # 加载强势池名单 (每个日期)
    strong_pool = {}
    for date, day in strong.items():
        strong_pool[date] = set(s for s, r in day.items() if r[15] >= 7 and (r[16] >= 6 or r[3] >= 50))

    files = glob.glob(os.path.join(KLINE, '*.json'))
    print(f'stocks: {len(files)}', flush=True)
    results = {}
    n_ok = 0
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        for k, (sym, out) in enumerate(ex.map(process_stock, files, chunksize=20)):
            if out:
                results[sym] = out
                n_ok += 1
            if (k + 1) % 500 == 0:
                print(f'  {k+1}/{len(files)} ok={n_ok} elapsed={time.time()-t0:.0f}s', flush=True)
    print(f'computed ok={n_ok} elapsed={time.time()-t0:.0f}s', flush=True)

    # 按日期+强势池过滤组装
    by_date = {}
    for sym, dmap in results.items():
        for date, rec in dmap.items():
            if sym not in strong_pool.get(date, set()):
                continue   # 仅保留当日强势池内的信号
            by_date.setdefault(date, []).append(rec)

    # 排序: S > A > B > C, 同级按 buy_score 降序
    rank = {'S': 0, 'A': 1, 'B': 2, 'C': 3}
    for date in by_date:
        by_date[date].sort(key=lambda x: (rank.get(x['level'], 9), -x['buy_score']))

    with open(os.path.join(OUT, 'buydian_v21_daily.json'), 'w', encoding='utf-8') as f:
        json.dump(by_date, f, ensure_ascii=False)

    dates = sorted(by_date.keys())
    last = dates[-1] if dates else 'N/A'
    day = by_date.get(last, [])
    cnt = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
    for r in day:
        if r['level'] in cnt:
            cnt[r['level']] += 1
    print(f'dates={len(dates)} latest={last}')
    print(f'最新日分级: S={cnt["S"]} A={cnt["A"]} B={cnt["B"]} C={cnt["C"]}')
    for r in day:
        if r['level'] in ('S', 'A'):
            print(f'  [{r["level"]}] {r["c"]} {r["n"]} 收盘{r["close"]} 回踩{r["pullback_dist"]} Trigger{r["trig_cnt"]} 共振{r["resonate"]} 缩量{r["shrink"]} 止损{r["stop"]} R/R{r["rr"]}')
    print(f'elapsed={time.time()-t0:.0f}s')

if __name__ == '__main__':
    main()
