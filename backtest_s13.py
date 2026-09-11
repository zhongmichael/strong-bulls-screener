# -*- coding: utf-8 -*-
"""
backtest_s13.py — S13: 情绪周期"大冰点"策略框架回测
======================================================
用户命题(市场情绪周期理论框架):
  一、大冰点识别: 上涨家数<200 为大冰点(<500 小冰点); 跌停家数明显高于涨停; 连板高度压缩。
  二、冰点当天左侧试错:
      S13a 低吸前期强势股博弈反包 (近10日有过涨停/人气股, 当日未涨停且不深跌, 尾盘≈收盘买)
      S13b 空间板博弈弱转强 (最高连板股当日收盘仍封板; "尾盘回封"盘中过程无分时数据, 用收盘封板近似)
  三、冰点次日右侧确认:
      S13c 转势票 (次日市场修复=等权均值>0且强于冰点日时, 买入次日领涨股, 持有至次日次日收盘)
      (竞价/开盘确认需盘中数据, 不可测)
  四、风险: 冰点延伸概率与"连续下跌后 vs 横盘破位后"的环境区分 → 条件分析。

数据限制(诚实声明): 年K仅收盘价, 无开高低/分时/竞价 → 尾盘回封只能用"收盘仍封板"近似,
  转势票"率先与指数共振"用"次日涨幅榜前列"近似; 仓位管理/止损纪律不在回测范围。

口径: 冰点日=温度<30 (与前序 S1~S12 同源)。S13a/S13b 冰点日收盘买 → 次日收盘卖;
  S13c 确认日(T+1)收盘买 → T+2 收盘卖。
"""
import json, sys, collections

sys.path.insert(0, '/Users/michael/Documents/golden-system/td9-screener')
from backtest_bingdian import build, BD_TH, zt_limit  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS  # noqa


def lim_pct(bt, sym):
    m = bt.meta.get(sym) or []
    return (zt_limit(sym, m[0] if m else None) - 0.02) * 100


def conseq_zt(bt, bars, sym, j):
    """截至 j 的连板数(收盘价口径连续涨停)"""
    th = lim_pct(bt, sym)
    n = 0
    q = j
    while q >= 1:
        pc = bars[q - 1][1]
        if not pc > 0: break
        if (bars[q][1] / pc - 1) * 100 >= th: n += 1; q -= 1
        else: break
    return n


def recent_zt_cnt(bt, sym, j, days=10):
    """近 days 日涨停次数(含当日)"""
    bars = bt.yk[sym]
    th = lim_pct(bt, sym)
    c = 0
    for q in range(max(1, j - days + 1), j + 1):
        pc = bars[q - 1][1]
        if pc > 0 and (bars[q][1] / pc - 1) * 100 >= th: c += 1
    return c


def pick_s13a(bt, sc):
    """低吸前期强势股: 近10日有过涨停(人气) × 当日未涨停 × 当日≥-3%(不接刀)"""
    rows = [r for r in sc['rows'].values()
            if 'ST' not in r['name'] and 'st' not in r['name']]
    pool_day = None
    di = bt.day_idx[sc['target']]
    for back in range(0, 4):
        pool_day = bt.strong_pool.get(bt.dates[di - back])
        if pool_day: break
    cand = []
    for r in rows:
        th = lim_pct(bt, r['sym'])
        if r['pct'] >= th: continue                 # 当日涨停 → 属于S5, 这里低吸未封的
        if r['pct'] < -3: continue                  # 不接深跌刀
        zc = recent_zt_cnt(bt, r['sym'], r['j'], 10)
        if zc < 1: continue                         # 近10日须有过涨停(前期强势/人气)
        score = zc * 6 + r['rel'] * 2 + (r['secRel'] * 4 if r['secRel'] is not None else 0)
        tags = ['人气%d板' % zc] if zc else []
        if pool_day and pool_day.get(r['sym']): score += 10; tags.append('强势池')
        if r['hot']: tags.append('强板块')
        cand.append((score, r, '+'.join(tags) or '人气股'))
    cand.sort(key=lambda x: -x[0])
    picked, cnt = [], {}
    for s, r, tag in cand:
        if len(picked) >= 10: break
        if cnt.get(r['ind'], 0) >= 2: continue
        cnt[r['ind']] = cnt.get(r['ind'], 0) + 1; picked.append((s, r, tag))
    for s, r, tag in cand:
        if len(picked) >= 10: break
        if all(r['sym'] != p[1]['sym'] for p in picked): picked.append((s, r, tag))
    return picked[:10]


def pick_s13b(bt, sc):
    """空间板: 当日收盘仍封板的最高连板股(≥2板), 博弱转强"""
    rows = [r for r in sc['rows'].values()
            if 'ST' not in r['name'] and 'st' not in r['name']]
    cand = []
    for r in rows:
        th = lim_pct(bt, r['sym'])
        if r['pct'] < th: continue                  # 收盘封板
        h = conseq_zt(bt, bt.yk[r['sym']], r['sym'], r['j'])
        if h < 2: continue                          # 至少2连板(空间板属性)
        cand.append((h * 10, r, '%d连板' % h))
    cand.sort(key=lambda x: -x[0])
    return cand[:10]


def ret_between(bt, sym, d1, d2):
    ix = bt.idx[sym]
    j1, j2 = ix.get(d1), ix.get(d2)
    if j1 is None or j2 is None: return None
    c1 = bt.yk[sym][j1][1]
    if not c1 > 0: return None
    return (bt.yk[sym][j2][1] / c1 - 1) * 100


def mkt_avg_on(bt, d):
    s = 0.0; n = 0
    for sym, ix in bt.idx.items():
        j = ix.get(d)
        if j is None: continue
        c = bt.yk[sym][j][1]
        pj = j - 1 if j >= 1 else None
        if pj is None: continue
        pc = bt.yk[sym][pj][1]
        if not pc > 0: continue
        s += (c / pc - 1) * 100; n += 1
    return s / n if n else None


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    ice_days = sorted(d for d in dates[1:-2] if scores.get(d) is not None and scores[d] < BD_TH)

    # ---- 一、大冰点识别: 涨跌家数/涨跌停对比 vs 温度分 ----
    day_meta = []
    for t in ice_days:
        sc = bt.scan(t); sc['target'] = t
        rows = [r for r in sc['rows'].values()]
        adv = sum(1 for r in rows if r['pct'] > 0)
        zt = sum(1 for r in rows if r['pct'] >= lim_pct(bt, r['sym']))
        dt = 0
        for r in rows:
            th = lim_pct(bt, r['sym'])
            nm = r['name']
            # 跌停阈值近似对称(不考虑ST一字特殊)
            if r['pct'] <= -th: dt += 1
        day_meta.append(dict(date=t, score=scores[t], adv=adv, zt=zt, dt=dt,
                             mkt=round(sc['mkt_avg'], 2)))
    for dm in day_meta:
        dm['big'] = dm['adv'] < 200 or dm['dt'] > 2 * dm['zt']   # 校准大冰点: 家数<200(本窗口从未出现)或跌停>涨停×2
        dm['mid'] = 200 <= dm['adv'] < 500
    n_big = sum(1 for dm in day_meta if dm['big'])
    print('==== 大冰点识别对照 ====')
    print('温度<30共%d天; 其中校准大冰点(上涨<200 或 跌停>涨停×2)%d天' % (len(ice_days), n_big))
    for dm in day_meta:
        print('  %s 温度%2d 上涨%4d 涨停%3d 跌停%3d 均值%+.2f%% %s' % (
            dm['date'], dm['score'], dm['adv'], dm['zt'], dm['dt'], dm['mkt'],
            '★大冰点' if dm['big'] else ('小冰点' if dm['mid'] else '')))

    big_days = [dm['date'] for dm in day_meta if dm['big']]

    # ---- 二、左侧策略: S13a/S13b (冰点日收盘买 → 次日收盘卖) ----
    # ---- 三、右侧策略: S13c (确认日收盘买 → T+2收盘卖) ----
    res = {c: dict(days=[], trades=[], skipped=0) for c in ('S13a', 'S13b', 'S13c')}
    s13c_days = []   # (date=t, conf=nd, mkt_t, mkt_nd, picked)
    for dm in day_meta:
        t = dm['date']
        sc = bt.scan(t); sc['target'] = t
        ni = day_idx[t] + 1
        nd = dates[ni]
        bench = dm['mkt']
        nd_mkt = mkt_avg_on(bt, nd)
        # S13a
        rets = []
        for s, r, tag in pick_s13a(bt, sc):
            ret = ret_between(bt, r['sym'], t, nd)
            if ret is None: res['S13a']['skipped'] += 1; continue
            rets.append(ret)
            res['S13a']['trades'].append(dict(date=t, code=r['sym'][2:], name=r['name'],
                pct=round(r['pct'], 2), ind=r['ind'], ret=round(ret, 2), tag=tag))
        if rets:
            res['S13a']['days'].append(dict(date=t, score=dm['score'], nd=nd, n=len(rets),
                avg=round(sum(rets) / len(rets), 2),
                win=round(sum(1 for x in rets if x > 0) / len(rets), 2), bench=bench, big=dm['big']))
        # S13b
        rets = []
        for s, r, tag in pick_s13b(bt, sc):
            ret = ret_between(bt, r['sym'], t, nd)
            if ret is None: res['S13b']['skipped'] += 1; continue
            rets.append(ret)
            res['S13b']['trades'].append(dict(date=t, code=r['sym'][2:], name=r['name'],
                pct=round(r['pct'], 2), ind=r['ind'], ret=round(ret, 2), tag=tag))
        if rets:
            res['S13b']['days'].append(dict(date=t, score=dm['score'], nd=nd, n=len(rets),
                avg=round(sum(rets) / len(rets), 2),
                win=round(sum(1 for x in rets if x > 0) / len(rets), 2), bench=bench, big=dm['big']))
        # S13c: 次日修复确认(nd_mkt>0 且 > 冰点日均值) → 买次日领涨(涨停优先, 按涨幅排), 持有到T+2
        if nd_mkt is not None and nd_mkt > 0 and nd_mkt > dm['mkt'] and ni + 1 < len(dates):
            nd2 = dates[ni + 1]
            rows = [r for r in sc['rows'].values()
                    if 'ST' not in r['name'] and 'st' not in r['name']]
            cands = []
            for r in rows:
                ix = bt.idx[r['sym']]
                jx = ix.get(nd)
                if jx is None: continue
                pc = bt.yk[r['sym']][jx - 1][1] if jx >= 1 else None
                if not pc or not pc > 0: continue
                nd_pct = (bt.yk[r['sym']][jx][1] / pc - 1) * 100
                if nd_pct < lim_pct(bt, r['sym']): continue   # 次日涨停=被资金确认
                cands.append((nd_pct, r, '次日%.1f%%' % nd_pct))
            cands.sort(key=lambda x: -x[0])
            picked, cnt = [], {}
            for s, r, tag in cands:
                if len(picked) >= 10: break
                if cnt.get(r['ind'], 0) >= 2: continue
                cnt[r['ind']] = cnt.get(r['ind'], 0) + 1; picked.append((s, r, tag))
            pct_map = {r['sym']: s for s, r, _ in cands}
            rets = []
            for s, r, tag in picked:
                ret = ret_between(bt, r['sym'], nd, nd2)
                if ret is None: res['S13c']['skipped'] += 1; continue
                rets.append(ret)
                res['S13c']['trades'].append(dict(date=nd, code=r['sym'][2:], name=r['name'],
                    pct=round(pct_map.get(r['sym'], 0), 2), ind=r['ind'], ret=round(ret, 2), tag=tag))
            if rets:
                nd2_mkt = mkt_avg_on(bt, nd2)
                res['S13c']['days'].append(dict(date=t, score=dm['score'], nd=nd, nd2=nd2,
                    n=len(rets), avg=round(sum(rets) / len(rets), 2),
                    win=round(sum(1 for x in rets if x > 0) / len(rets), 2),
                    bench=round(nd2_mkt, 2) if nd2_mkt is not None else 0.0, big=dm['big']))
        s13c_days.append((t, nd, dm['mkt'], nd_mkt))

    # ---- 四、条件分析: 冰点延伸(次日市场<0)频率 + S5按修复/延伸分组 ----
    ext = [ (t, nd, m1, m2) for t, nd, m1, m2 in s13c_days if m2 is not None ]
    n_ext = sum(1 for _, _, _, m2 in ext if m2 < 0)
    n_rep = sum(1 for _, _, _, m2 in ext if 0 <= m2)
    sd_, yk2 = bt.yk, None
    # S5 逐笔按次日市场分组
    from backtest_bingdian_multi import STRATS as _S
    s5_trades = {}
    # 直接重算 S5 逐笔分组
    grp = {'rep': [], 'ext': []}
    for dm in day_meta:
        t = dm['date']; nd = dates[day_idx[t] + 1]
        sc = bt.scan(t)
        nd_mkt = mkt_avg_on(bt, nd)
        g = 'rep' if (nd_mkt is not None and nd_mkt >= 0) else 'ext'
        for s, r, tag in bt.pick(t, 'S5', sc):
            ret = ret_between(bt, r['sym'], t, nd)
            if ret is not None: grp[g].append(ret)
    print('\n==== 冰点延伸频率(次日全市场等权<0) ====')
    print('冰点日 %d 天: 次日修复 %d 天, 延续下跌(冰点延伸) %d 天 (%.0f%%)' % (
        len(ext), n_rep, n_ext, n_ext * 100.0 / len(ext) if ext else 0))
    for g, label in (('rep', '次日修复'), ('ext', '冰点延伸')):
        if grp[g]:
            print('S5(冰点日涨停) 在[%s]日买入: 笔数%d 均值%+.2f%% 胜率%.0f%%' % (
                label, len(grp[g]), sum(grp[g]) / len(grp[g]),
                100.0 * sum(1 for x in grp[g] if x > 0) / len(grp[g])))

    # ---- 汇总 ----
    summary = []
    NAME = {'S13a': '低吸前期强势股(反包)', 'S13b': '空间板收盘封板(弱转强)', 'S13c': '次日转势票(右侧确认)'}
    DESC = {
        'S13a': '近10日有过涨停×当日未涨停且≥-3%×人气/池/板块打分, 板块配额2',
        'S13b': '当日收盘仍封板的最高连板(≥2板), 按高度取前10',
        'S13c': '次日等权>0且强于冰点日时, 买次日涨停股(板块配额2), T+1收买→T+2收卖',
    }
    for c in ('S13a', 'S13b', 'S13c'):
        R = res[c]
        all_rets = [tr['ret'] for tr in R['trades']]
        n = len(all_rets)
        if n == 0:
            summary.append(dict(code=c, name=NAME[c], desc=DESC[c], ndays=0, n=0)); continue
        srt = sorted(all_rets, reverse=True)
        mean = sum(all_rets) / n
        win = sum(1 for x in all_rets if x > 0) / n
        day_avg = sum(d['avg'] for d in R['days']) / len(R['days'])
        bench_avg = sum(d['bench'] for d in R['days']) / len(R['days'])
        # 大冰点子集(校准定义): S13a/S13b 成交日=触发日t; S13c 成交日=确认日nd
        t_big = {dm['date']: dm['big'] for dm in day_meta}
        nd_big = {d['nd']: d.get('big', False) for c in ('S13a', 'S13b', 'S13c') for d in res[c]['days']}
        bd_tr = [tr for tr in R['trades'] if t_big.get(tr['date']) or nd_big.get(tr['date'])]
        m_bd = sum(tr['ret'] for tr in bd_tr) / len(bd_tr) if bd_tr else None
        w_bd = (sum(1 for tr in bd_tr if tr['ret'] > 0) / len(bd_tr)) if bd_tr else None
        best = max(R['trades'], key=lambda x: x['ret'])
        worst = min(R['trades'], key=lambda x: x['ret'])
        drop3 = sum(srt[3:]) / (n - 3) if n > 3 else None
        summary.append(dict(code=c, name=NAME[c], desc=DESC[c], ndays=len(R['days']), n=n,
                            mean=round(mean, 2), win=round(win, 3),
                            day_avg=round(day_avg, 2), bench_avg=round(bench_avg, 2),
                            excess=round(day_avg - bench_avg, 2),
                            drop3=(round(drop3, 2) if drop3 is not None else None),
                            nbig=len(bd_tr), mean_big=(round(m_bd, 2) if m_bd is not None else None),
                            win_big=(round(w_bd, 3) if w_bd is not None else None),
                            best='%s %s %+.1f%%' % (best['name'], best['date'][5:], best['ret']),
                            worst='%s %s %+.1f%%' % (worst['name'], worst['date'][5:], worst['ret']),
                            skipped=R['skipped']))

    print('\n========== S13 情绪周期框架回测 ==========')
    hdr = '%-5s %-22s %-5s %-5s %-8s %-6s %-9s %-9s %-12s %-8s'
    print(hdr % ('策略', '名称', '天数', '笔数', '单笔均值', '胜率', '日均超额', '剔最佳3笔', '大冰点子集均值', '26后--'))
    for s in summary:
        if s['n'] == 0:
            print('%-5s %-22s 无交易' % (s['code'], s['name'])); continue
        print(hdr % (s['code'], s['name'], s['ndays'], s['n'], '%+.2f%%' % s['mean'],
                     '%.0f%%' % (s['win'] * 100), '%+.2f%%' % s['excess'],
                     ('%+.2f%%' % s['drop3']) if s['drop3'] is not None else '--',
                     ('%+.2f%%/%d笔' % (s['mean_big'], s['nbig'])) if s['mean_big'] is not None else '--', ''))
        print('      最佳: %s | 最差: %s' % (s['best'], s['worst']))

    out = dict(window=[dates[0], dates[-1]], ndays_ice=len(ice_days), bd_th=BD_TH,
               day_meta=day_meta, n_big=n_big, big_days=big_days,
               summary=summary,
               ext_freq=dict(total=len(ext), rep=n_rep, ext=n_ext),
               s5_split=dict(rep_n=len(grp['rep']), rep_avg=round(sum(grp['rep']) / len(grp['rep']), 2) if grp['rep'] else None,
                             ext_n=len(grp['ext']), ext_avg=round(sum(grp['ext']) / len(grp['ext']), 2) if grp['ext'] else None),
               days=res, )
    with open('/Users/michael/Documents/golden-system/td9-screener/backtest_s13_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s13_data.json / backtest_s13.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    dm = json.dumps(out['day_meta'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    extf = json.dumps(out['ext_freq'], ensure_ascii=False)
    s5s = json.dumps(out['s5_split'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S13 · 情绪周期"大冰点"框架回测</title>
<script src="./echarts.min.js"></script>
<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f1f3f6;margin:0;padding:18px;color:#212529}
.wrap{max-width:1240px;margin:0 auto}
h1{font-size:19px;margin:2px 0 4px}
h2{font-size:14px;margin:0 0 6px}
.sub{font-size:12px;color:#868e96;margin-bottom:14px;line-height:1.8}
.panel{background:#fff;border:1px solid #e9ecef;border-radius:8px;padding:12px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{padding:6px 8px;text-align:left;color:#495057;border-bottom:2px solid #dee2e6;background:#f8f9fa}
td{padding:5px 8px;border-bottom:1px solid #f0f2f7}
.up{color:#e03131;font-weight:700}.dn{color:#0ca678;font-weight:700}
.best{background:#fff5f5}
.note{font-size:11px;color:#868e96;line-height:1.8}
.tag{display:inline-block;background:#edf2ff;color:#1c7ed6;border-radius:4px;padding:0 6px;font-size:10.5px;margin-right:4px}
.tblbox{max-height:420px;overflow:auto}
</style></head><body><div class="wrap">
<h1>🧊 S13 · 情绪周期「大冰点」框架回测</h1>
<div class="sub">框架来源: 市场情绪周期理论（大冰点识别 / 当天左侧试错 / 次日右侧确认 / 冰点延伸风控）· 窗口 __W0__ → __W1__ · 冰点日=温度&lt;30 共 __NI__ 天, 其中<b>校准大冰点（上涨家数&lt;200 或 跌停&gt;涨停×2）共 __NB__ 天</b><br>
<b>可测范围声明</b>: 年K仅收盘价（无开高低/分时/竞价/龙虎榜）→ "尾盘回封"用<b>收盘仍封板</b>近似; "率先与指数共振"用<b>次日涨停(被资金确认)</b>近似; 竞价/开盘确认、仓位梯度、止损纪律不在回测范围。</div>
<div class="panel"><h2>一、大冰点识别对照（温度分 vs 涨跌家数/涨跌停）</h2><div class="tblbox"><table id="dmtbl"></table></div></div>
<div class="panel"><h2>二、三套可测策略总览</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>三、冰点延伸频率与 S5 条件分组</h2><div id="extbox" style="font-size:13px;line-height:2"></div></div>
<div class="panel"><h2>逐日收益对比（%）</h2><div id="chart" style="width:100%;height:380px"></div></div>
<div class="panel note">口径说明: ① S13a/S13b 冰点日收盘买→次日收盘卖; S13c 需次日修复确认(次日全市场等权&gt;0且强于冰点日), 于确认日收盘买→T+2收盘卖; ② "大冰点子集"=上涨家数&lt;200 的冰点日; ③ 涨停判定=收盘涨幅≥(板块限价-0.02pp), 跌停对称近似, 未含一字开板细节; ④ 连板数按收盘价连续涨停口径; ⑤ 仅为策略研究, 不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DMD = __DMD__, DAYS = __DAYS__, EXT = __EXT__, S5S = __S5S__;
var h = '<tr><th>日期</th><th>温度</th><th>上涨家数</th><th>涨停</th><th>跌停</th><th>全市场均值</th><th>框架分级</th></tr>';
DMD.forEach(function(d){
  h += '<tr><td>'+d.date.slice(2)+'</td><td><b>'+d.score+'</b></td><td>'+d.adv+'</td><td class="up">'+d.zt+'</td><td class="dn">'+d.dt+'</td>'
    + '<td class="'+(d.mkt>=0?'up':'dn')+'">'+(d.mkt>0?'+':'')+d.mkt.toFixed(2)+'%</td>'
    + '<td>'+(d.big?'<b style="color:#d6336c">★大冰点</b>':(d.mid?'小冰点':''))+'</td></tr>';
});
document.getElementById('dmtbl').innerHTML = h;
var hh = '<tr><th>策略</th><th>画像</th><th>天数</th><th>笔数</th><th>单笔均值</th><th>胜率</th><th>日均超额</th><th>剔最佳3笔</th><th>大冰点子集</th><th>最佳/最差单笔</th></tr>';
SM.slice().sort(function(a,b){return (b.excess||-99)-(a.excess||-99);}).forEach(function(s, i){
  if(!s.n){ hh += '<tr><td><b>'+s.code+'</b> '+s.name+'</td><td colspan="9" style="color:#868e96">无交易</td></tr>'; return; }
  hh += '<tr'+(i===0?' class="best"':'')+'><td><b>'+s.code+'</b> '+s.name+'</td><td style="font-size:11px;color:#868e96">'+s.desc+'</td>'
    + '<td>'+s.ndays+'</td><td>'+s.n+'</td>'
    + '<td class="'+(s.mean>=0?'up':'dn')+'">'+(s.mean>0?'+':'')+s.mean.toFixed(2)+'%</td>'
    + '<td>'+Math.round(s.win*100)+'%</td>'
    + '<td class="'+(s.excess>=0?'up':'dn')+'">'+(s.excess>0?'+':'')+s.excess.toFixed(2)+'%</td>'
    + '<td>'+(s.drop3!=null?((s.drop3>0?'+':'')+s.drop3.toFixed(2)+'%'):'--')+'</td>'
    + '<td>'+(s.mean_big!=null?((s.mean_big>0?'+':'')+s.mean_big.toFixed(2)+'% /'+s.nbig+'笔 /胜'+Math.round(s.win_big*100)+'%'):'--')+'</td>'
    + '<td style="font-size:11px"><span class="up">'+s.best+'</span> / <span class="dn">'+s.worst+'</span></td></tr>';
});
document.getElementById('sumtbl').innerHTML = hh;
document.getElementById('extbox').innerHTML =
  '冰点延伸频率: 次日延续下跌 <b class="dn">'+EXT.ext+'</b> 天 / '+EXT.total+' 天（<b>'+Math.round(EXT.ext*100/EXT.total)+'%</b>），修复 '+EXT.rep+' 天 — 与框架"1/3 延伸"直觉对照<br>'
  + 'S5(冰点日涨停)按次日环境分组: <b>次日修复</b>日买入 均值 <b class="up">+'+S5S.rep_avg+'%</b>（'+S5S.rep_n+'笔） · <b>冰点延伸</b>日买入 均值 <b class="dn">'+S5S.ext_avg+'%</b>（'+S5S.ext_n+'笔）';
var cats = DMD.map(function(d){ return d.date.slice(2); });
var series = ['S13a','S13b'].map(function(c, i){
  var m = {}; (DAYS[c].days||[]).forEach(function(d){ m[d.date] = d.avg; });
  return {name: c, type: 'bar', data: cats.map(function(dt){ var k = DMD.find(function(x){return x.date.slice(2)===dt;}).date; return m[k]!=null?m[k]:null; }), barMaxWidth: 12};
});
series.push({name:'次日大盘等权', type:'line', data: DMD.map(function(d){ return d.mkt; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
var ch = echarts.init(document.getElementById('chart'));
ch.setOption({tooltip:{trigger:'axis'},legend:{top:0,textStyle:{fontSize:11}},
  grid:{left:44,right:20,top:40,bottom:56},
  xAxis:{type:'category',data:cats,axisLabel:{rotate:45,fontSize:10,color:'#868e96'}},
  yAxis:{type:'value',axisLabel:{formatter:'{value}%'},splitLine:{lineStyle:{color:'#f0f2f7'}}},
  series: series});
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__NI__', str(out['ndays_ice'])).replace('__NB__', str(out['n_big']))
            .replace('__SM__', sm).replace('__DMD__', dm).replace('__DAYS__', days)
            .replace('__EXT__', extf).replace('__S5S__', s5s))
    p = '/Users/michael/Documents/golden-system/td9-screener/backtest_s13.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
