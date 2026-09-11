# -*- coding: utf-8 -*-
"""
三周期强势股计算 + 强势回踩评分模型 v4
=========================================
强势股池 (周月持续强势, 规则D):
  周线近10周≥7周站上周MA5 (核心)
  且 (月线近12月≥6月站上月MA5  或  三周期强度≥50)
  说明: 周线持续强势为核心, 月线不足时用高强度(乖离)补偿,
        覆盖哈药股份这类"周线先行、月线刚转强、动量极强"的强势股
  并集: 与"日周月全站上"取并集

强势回踩评分 (0~100) — 基于"强势回踩"七维度标准:
  1. 前期涨幅 (0-20):  近20日涨幅≥15%满分, ≥10%给15, ≥5%给8, <0给0
  2. 均线多头 (0-20):  MA5>MA10>MA20 +10, MA10斜率↑+5, MA20斜率↑+5
  3. 回踩深度 (0-15):  盘中触及MA(低点≤MA*1.01/1.02)+10, 收盘收回+5
  4. 缩量确认 (0-15):  量<0.8×5日均量+15, <1.0×+10, <1.2×+5, ≥1.5×-10(放量回踩危险)
  5. K线止跌 (0-15):  长下影+6, 阳线/十字星+4, 阳包阴+5
  6. 收回速度 (0-15):  收盘>MA5 +8, 收盘>目标均线 +7
  7. 大周期配合 (0-10): 周收盘>周MA5 +6, >周MA10 +4
  失败形态剔除: 放量长阴破位 / 均线明显向下 / 周线走坏
  突破回踩有效性约束 (v4.1, 参考"突破回踩如何确认有效"标准):
  8. 回踩节奏 (±20/4): 当日大阴线(实体≤-3.2%)-20 (大阴线砸下=假突破信号);
     阴线实体较昨日收窄过半 +4 (碎步下跌/动能衰竭)
  9. 深度极限 (-15): 盘中低点深破目标均线3%以上 (深入前期箱体下半部, 突破宣告失败)
  10. 时间过滤 (±20/5): 连续≥6日收盘站不回MA5 -20 (久盘必跌); ≤2日快速企稳 +5
  11. 突破量对比 (±5): 当日量<近20日突破峰值量55% +5 (放量突破→缩量回踩, 健康);
      ≥85% -5 (回踩量接近突破日, 抛压未消化)

输出: data/out/strong_2026.json
  {date: {sym: [day_ok, week_ok, month_ok, strength,
                bias10, bias20, pull10, pull20, form_score,
                pull10_score, pull20_score, vol_ratio10, vol_ratio20]}}
  pull10: 收盘0~2.5%上MA10 且盘中触及 → 基础回踩
  pull10_score: 强势回踩综合评分(0-100), 用于排序
"""
import json
import glob
import os
import sys
import time
import numpy as np
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n-1:] = (c[n:] - c[:-n]) / n
    return out

def week_key(dt):
    iso = dt.isocalendar()
    return iso[0] * 100 + iso[1]

def month_key(dt):
    return dt.year * 100 + dt.month

def kline_features(i, o, h, l, c, v, ma10, ma20):
    """K线止跌信号检测, 返回 (长下影, 阳线/十字星, 阳包阴)"""
    body = c[i] - o[i]
    rng = h[i] - l[i]
    lower = min(o[i], c[i]) - l[i]
    long_lower = (rng > 0 and lower > abs(body) * 2)
    yang_or_doji = (body > 0) or (rng > 0 and abs(body) / rng < 0.1)
    engulf = False
    if i >= 1 and body > 0 and (c[i-1] < o[i-1]):
        engulf = (c[i] >= o[i-1]) and (o[i] <= c[i-1])
    return long_lower, yang_or_doji, engulf

def score_pullback(i, o, h, l, c, v, ma5, ma10, ma20,
                   wcloses, wi, target="ma10"):
    """强势回踩评分 0~100. target: 'ma10' 或 'ma20'"""
    if target == "ma10":
        tgt = ma10[i]
        touch = (l[i] <= tgt * 1.01)          # 盘中触及MA10
        shrink = 0.8                          # 缩量阈值
    else:
        tgt = ma20[i]
        touch = (l[i] <= tgt * 1.02)          # 盘中触及MA20
        shrink = 0.7                          # 20日线要求更严格缩量
    if np.isnan(tgt):
        return 0.0
    score = 0.0
    # --- 1. 前期涨幅 (0-20) ---
    if i >= 20:
        ret20 = (c[i] / c[i-20] - 1) * 100
        if ret20 >= 15: score += 20
        elif ret20 >= 10: score += 15
        elif ret20 >= 5: score += 8
        # <0 不给分
    # --- 2. 均线多头 (0-20) ---
    if (not np.isnan(ma5[i]) and not np.isnan(ma10[i]) and not np.isnan(ma20[i])
            and ma5[i] > ma10[i] > ma20[i]):
        score += 10
    if i >= 1 and not np.isnan(ma10[i]) and not np.isnan(ma10[i-1]) and ma10[i] > ma10[i-1]:
        score += 5
    if i >= 1 and not np.isnan(ma20[i]) and not np.isnan(ma20[i-1]) and ma20[i] > ma20[i-1]:
        score += 5
    # --- 3. 回踩深度 (0-15) ---
    if touch: score += 10
    if c[i] > tgt: score += 5
    # --- 4. 缩量确认 (0-15) ---
    vma5 = sma(v, 5)[i]
    if not np.isnan(vma5) and vma5 > 0:
        vr = v[i] / vma5
        if vr < shrink: score += 15
        elif vr < 1.0: score += 10
        elif vr < 1.2: score += 5
        elif vr >= 1.5: score -= 10
    # --- 5. K线止跌 (0-15) ---
    ll, yd, eg = kline_features(i, o, h, l, c, v, ma10, ma20)
    if ll: score += 6
    if yd: score += 4
    if eg: score += 5
    # --- 6. 收回速度 (0-15) ---
    if c[i] > ma5[i]: score += 8
    if c[i] > tgt: score += 7
    # --- 7. 大周期配合 (0-10) ---
    if wi >= 4:
        w5 = sum(wcloses[wi-4:wi+1]) / 5
        if c[i] > w5: score += 6
    if wi >= 9:
        w10 = sum(wcloses[wi-9:wi+1]) / 10
        if c[i] > w10: score += 4
    # --- 8. 回踩节奏 (突破回踩有效性: 大阴线否决 / 动能衰竭加分) ---
    body = c[i] - o[i]
    if i >= 1:
        p_body = c[i-1] - o[i-1]
        if body < 0 and c[i] > 0 and body / c[i] <= -0.032:
            score -= 20                          # 当日大阴线: 空头力量极强, 大概率假突破
        elif body < 0 and p_body < 0 and body > p_body * 0.5:
            score += 4                           # 阴线实体较昨日收窄过半: 下跌动能衰竭
    # --- 9. 深度极限 (不能深入前期震荡箱体下半部) ---
    if l[i] < tgt * 0.97:
        score -= 15                              # 盘中深破均线3%以上: 突破宣告失败
    # --- 10. 时间过滤 (有效回踩3-5根K线内企稳, 久盘必跌) ---
    pull_days = 0
    j = i
    while j >= 0 and j > i - 12:
        m5v = ma5[j]
        if not np.isnan(m5v) and c[j] < m5v:
            pull_days += 1
            j -= 1
        else:
            break
    if pull_days >= 6:
        score -= 20                              # 连续6日以上站不回MA5: 久盘横盘
    elif pull_days <= 2:
        score += 5                               # 快速企稳
    # --- 11. 突破放量→回踩缩量 对比 (放量突破是前提, 缩量回踩是过程) ---
    if i >= 5:
        v_brk = float(np.max(v[max(0, i - 20):i]))   # 近20日峰值量≈突破日量
        if v_brk > 0:
            if v[i] < v_brk * 0.55:
                score += 5                           # 较突破日显著缩量
            elif v[i] >= v_brk * 0.85:
                score -= 5                           # 回踩量接近突破日: 抛压未消化
    return round(max(min(score, 100), 0), 1)

def process_stock(fp):
    sym = os.path.basename(fp)[:-5]
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        bars = d["bars"]
        if len(bars) < 60:
            return sym, None
        dates = [b[0] for b in bars]
        o = np.array([float(b[1]) for b in bars])
        c = np.array([float(b[2]) for b in bars])
        h = np.array([float(b[3]) for b in bars])
        l = np.array([float(b[4]) for b in bars])
        v = np.array([float(b[5]) for b in bars])
        n = len(closes) if False else len(c)
        ma5d = sma(c, 5)
        ma10 = sma(c, 10)
        ma20 = sma(c, 20)
        ma250 = sma(c, 250)

        # 完整周序列
        wkeys, wcloses, wlast = [], [], []
        cur = None
        for i in range(n):
            dt = datetime.strptime(dates[i], "%Y-%m-%d").date()
            wk = week_key(dt)
            if wk != cur:
                wkeys.append(wk); wcloses.append(c[i]); wlast.append(dt); cur = wk
            else:
                wcloses[-1] = c[i]; wlast[-1] = dt
        # 完整月序列
        mkeys, mcloses, mlast = [], [], []
        cur = None
        for i in range(n):
            dt = datetime.strptime(dates[i], "%Y-%m-%d").date()
            mk = month_key(dt)
            if mk != cur:
                mkeys.append(mk); mcloses.append(c[i]); mlast.append(dt); cur = mk
            else:
                mcloses[-1] = c[i]; mlast[-1] = dt

        out = {}
        for i in range(n):
            if not dates[i].startswith("2026"):
                continue
            # 日线
            day_ok = (not np.isnan(ma5d[i])) and c[i] > ma5d[i]
            day_bias = (c[i] / ma5d[i] - 1) * 100 if not np.isnan(ma5d[i]) else 0
            ma5v = ma5d[i]; ma10v = ma10[i]; ma20v = ma20[i]; ma250v = ma250[i]
            bull = (not np.isnan(ma5v) and not np.isnan(ma10v) and not np.isnan(ma20v)
                    and ma5v > ma10v > ma20v)
            above_year = (not np.isnan(ma250v)) and c[i] > ma250v
            mom5 = (c[i] / c[i-5] - 1) * 100 if i >= 5 else 0.0
            day_pct = (c[i] / c[i-1] - 1) * 100 if i >= 1 else 0.0
            dt = datetime.strptime(dates[i], "%Y-%m-%d").date()
            wk = week_key(dt)
            wi = len(wkeys) - 1
            for j in range(len(wkeys) - 1, -1, -1):
                if wkeys[j] <= wk:
                    wi = j
                    break
            week_ok = False
            week_bias = 0
            if wi >= 4:
                seg = list(wcloses[wi-4:wi]) + [c[i]]
                ma5w = sum(seg) / 5
                week_ok = c[i] > ma5w
                week_bias = (c[i] / ma5w - 1) * 100
            mk = month_key(dt)
            mi = len(mkeys) - 1
            for j in range(len(mkeys) - 1, -1, -1):
                if mkeys[j] <= mk:
                    mi = j
                    break
            month_ok = False
            month_bias = 0
            if mi >= 4:
                seg = list(mcloses[mi-4:mi]) + [c[i]]
                ma5m = sum(seg) / 5
                month_ok = c[i] > ma5m
                month_bias = (c[i] / ma5m - 1) * 100
            strength = round(day_bias + week_bias + month_bias, 2)
            # 日线 MA10/MA20 偏离度
            bias10 = (c[i] / ma10[i] - 1) * 100 if not np.isnan(ma10[i]) else None
            bias20 = (c[i] / ma20[i] - 1) * 100 if not np.isnan(ma20[i]) else None
            # 基础回踩判定: 收盘0~2.5%上均线 且 盘中触及
            pull10 = (bias10 is not None and 0 <= bias10 <= 2.5
                      and l[i] <= ma10[i] * 1.01)
            pull20 = (bias20 is not None and 0 <= bias20 <= 2.5
                      and l[i] <= ma20[i] * 1.02)
            # 强势回踩评分
            pull10_score = score_pullback(i, o, h, l, c, v, ma5d, ma10, ma20,
                                          wcloses, wi, "ma10") if pull10 else 0.0
            pull20_score = score_pullback(i, o, h, l, c, v, ma5d, ma10, ma20,
                                          wcloses, wi, "ma20") if pull20 else 0.0
            # 形态强势分 (保留, 主列表排序用)
            form = strength
            if bull: form += 8
            if above_year: form += 6
            form += max(min(mom5 * 0.5, 5), 0)
            if 0 <= day_pct < 5: form += 3
            elif day_pct >= 9: form -= 3
            form_score = round(form, 1)
            # 近20日涨幅 (用于上涨逻辑描述)
            ret20 = round((c[i] / c[i-20] - 1) * 100, 1) if i >= 20 else 0.0
            # 周线持续强势: 最近10周中 收盘>周MA5 的周数 (当前周=部分周, 收盘用c[i])
            wk_up10 = 0
            if wi >= 13:
                wseq = wcloses[wi-13:wi] + [c[i]]   # 14根, 前4根用于MA5预热
                for j in range(4, 14):
                    if wseq[j] > sum(wseq[j-4:j+1]) / 5:
                        wk_up10 += 1
            # 月线持续强势: 最近12月中 收盘>月MA5 的月数 (当前月=部分月)
            mo_up12 = 0
            if mi >= 15:
                mseq = mcloses[mi-15:mi] + [c[i]]   # 16根, 前4根用于MA5预热
                for j in range(4, 16):
                    if mseq[j] > sum(mseq[j-4:j+1]) / 5:
                        mo_up12 += 1
            # 周线连续站上周MA5的周数 (从当前周往回连续计数)
            wk_streak = 0
            if wi >= 13:
                wseq = wcloses[wi-13:wi] + [c[i]]
                for j in range(13, 3, -1):
                    if wseq[j] > sum(wseq[j-4:j+1]) / 5:
                        wk_streak += 1
                    else:
                        break
            # 月线连续站上月MA5的月数 (从当前月往回连续计数)
            mo_streak = 0
            if mi >= 15:
                mseq = mcloses[mi-15:mi] + [c[i]]
                for j in range(15, 3, -1):
                    if mseq[j] > sum(mseq[j-4:j+1]) / 5:
                        mo_streak += 1
                    else:
                        break
            out[dates[i]] = [int(day_ok), int(week_ok), int(month_ok), strength,
                             round(bias10, 2) if bias10 is not None else None,
                             round(bias20, 2) if bias20 is not None else None,
                             int(pull10), int(pull20), form_score,
                             pull10_score, pull20_score,
                             int(bull), int(above_year), ret20,
                             round(day_pct, 2), wk_up10, mo_up12,
                             wk_streak, mo_streak]
        return sym, out
    except Exception:
        return sym, None

def main():
    files = glob.glob("data/kline/*.json")
    print("stocks:", len(files), flush=True)
    t0 = time.time()
    results = {}
    n_ok = 0
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        for k, (sym, out) in enumerate(ex.map(process_stock, files, chunksize=20)):
            if out:
                results[sym] = out
                n_ok += 1
            if (k + 1) % 500 == 0:
                print(f"  {k+1}/{len(files)} ok={n_ok} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"computed ok={n_ok} elapsed={time.time()-t0:.0f}s", flush=True)

    by_date = {}
    for sym, dmap in results.items():
        for date, rec in dmap.items():
            by_date.setdefault(date, {})[sym] = rec

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/strong_2026.json", "w", encoding="utf-8") as f:
        json.dump(by_date, f, ensure_ascii=False)

    last = sorted(by_date.keys())[-1]
    day = by_date[last]
    # 强势池 = 周月持续强势(规则D) ∪ 日周月全站上
    pool = {s: r for s, r in day.items()
            if ((r[15] >= 7 and (r[16] >= 6 or r[3] >= 50)) or (r[0] and r[1] and r[2]))}
    p10 = {s: r for s, r in pool.items() if r[6] == 1}
    p20 = {s: r for s, r in pool.items() if r[7] == 1}
    print(f"dates={len(by_date)} latest={last} 池={len(pool)} 回踩10={len(p10)} 回踩20={len(p20)}")
    print("回踩10 TOP5(强势评分):", [(s, r[9]) for s, r in sorted(p10.items(), key=lambda x: -x[1][9])[:5]])
    print("回踩20 TOP5(强势评分):", [(s, r[10]) for s, r in sorted(p20.items(), key=lambda x: -x[1][10])[:5]])
    print("DONE")

if __name__ == "__main__":
    main()
