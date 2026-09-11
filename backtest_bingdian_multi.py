# -*- coding: utf-8 -*-
"""
backtest_bingdian_multi.py — 冰点日 TOP10 多策略对比回测
========================================================
共同口径: 温度分 < 30 触发冰点 → 触发日收盘等权买入 TOP10 → 下一交易日收盘卖出。
5 套策略(全部基于全市场年K收盘序列, 无量能/盘中字段):
  S1 趋势股(现行线上版): 抗跌>=-2% × 近5日<=50% × 站上MA20+MA20上行 × 20日涨幅3%~50%
     评分=均线多头+12/MA60上方+8/贴近MA20+6/乖离>20%-6/板块超额x6/相对大盘x2/强势池+10, 每板块<=2只
  S2 逆势红盘动量(原版): 冰点日红盘(>0.05%) × 非ST, 评分=相对大盘x3+板块超额x6+池+10, 每板块<=2只
  S3 趋势内超跌反弹: 长期趋势完好(站上MA30且MA30上行, 20日涨幅<=30%)但当日深跌-9%~-3%, 越跌分越高
  S4 强势池抗跌: 最近一次强势池成员(<=回看3个交易日) ∩ 当日抗跌>=-2%, 按相对大盘超额排序(池数据2026-01起)
  S5 冰点日涨停(最强票): 当日触及涨停( lim-0.02 ), 偏好低位首启动(近5日涨幅小)+强势板块
"""
import json, sys

BD_TH = 30
ROOT = '/Users/michael/Documents/golden-system/td9-screener/dist_strong'
sys.path.insert(0, '/Users/michael/Documents/golden-system/td9-screener')
from backtest_bingdian import build, BD_TH, zt_limit  # noqa

def ma_of(closes, nn):
    if len(closes) < nn: return None
    return sum(closes[-nn:]) / nn

def industry(meta, sym):
    m = meta.get(sym) or []
    ind = (m[5] if len(m) > 5 and m[5] else (m[3] if len(m) > 3 and m[3] else ''))
    return ind or '—'

def name_of(meta, sym):
    return (meta.get(sym) or [None])[0] or sym

class MultiBacktest(object):
    def __init__(self, yk, meta, dates, day_idx, scores, strong_pool):
        self.yk, self.meta, self.dates, self.day_idx = yk, meta, dates, day_idx
        self.scores, self.strong_pool = scores, strong_pool
        print('预建K线索引…')
        self.idx = {sym: {b[0]: j for j, b in enumerate(bars)} for sym, bars in yk.items()}

    # ---- 公共扫描: 一次性算好当日每只票的 pct/closes/均线, 各策略复用 ----
    def scan(self, target):
        di = self.day_idx[target]
        prev_date = self.dates[di - 1]
        mkt_sum = 0.0; mkt_n = 0; sec = {}
        rows = {}
        for sym, ix in self.idx.items():
            j = ix.get(target)
            if j is None or j < 30: continue
            bars = self.yk[sym]
            if bars[j-1][0] != prev_date: continue
            pc = bars[j-1][1]
            if not pc > 0: continue
            c = bars[j][1]
            pct = (c/pc - 1) * 100
            mkt_sum += pct; mkt_n += 1
            ind = industry(self.meta, sym)
            if ind != '—':
                a = sec.get(ind)
                if a is None: a = sec[ind] = [0.0, 0]
                a[0] += pct; a[1] += 1
            closes = [b[1] for b in bars[max(0, j-64):j+1]]
            ma5, ma10, ma20 = ma_of(closes, 5), ma_of(closes, 10), ma_of(closes, 20)
            ma30 = ma_of(closes, 30)
            ma20p = ma_of(closes[:-1], 20)
            ma30p = ma_of(closes[:-1], 30)
            ma60 = ma_of(closes, 60)
            ret5 = (c/bars[j-5][1] - 1) * 100 if j >= 5 else None
            ret20 = (c/bars[j-20][1] - 1) * 100 if j >= 20 else None
            rows[sym] = dict(sym=sym, name=name_of(self.meta, sym), pct=pct, c=c, ind=ind,
                             ma5=ma5, ma10=ma10, ma20=ma20, ma30=ma30, ma60=ma60,
                             ma20p=ma20p, ma30p=ma30p, ret5=ret5, ret20=ret20, j=j)
        if not mkt_n: return None
        mkt_avg = mkt_sum / mkt_n
        sec_avg = {k: v[0]/v[1] for k, v in sec.items()}
        hot = [k for k, v in sec.items() if v[1] >= 3 and sec_avg[k] > mkt_avg]
        hot.sort(key=lambda k: -sec_avg[k])
        hot_set = set(hot)
        for r in rows.values():
            r['rel'] = r['pct'] - mkt_avg
            r['secRel'] = (sec_avg[r['ind']] - mkt_avg) if r['ind'] in hot_set else None
            r['hot'] = r['ind'] in hot_set
        return dict(mkt_avg=mkt_avg, sec_avg=sec_avg, hot=hot, rows=rows)

    def pick(self, target, strat, sc):
        rows = [r for r in sc['rows'].values() if 'ST' not in r['name'] and 'st' not in r['name']]
        pool_day = None
        if strat in ('S1', 'S2', 'S4', 'S5'):
            di = self.day_idx[target]
            for back in range(0, 4):   # 池数据回看最多3个交易日
                pool_day = self.strong_pool.get(self.dates[di-back])
                if pool_day: break
        if strat == 'S1':
            cand = []
            for r in rows:
                if r['pct'] < -2 or r['ret5'] is None or r['ret5'] > 50: continue
                if r['ret20'] is None or not (3 <= r['ret20'] <= 50): continue
                if r['ma20'] is None or r['ma20p'] is None: continue
                if not (r['c'] >= r['ma20'] and r['ma20'] > r['ma20p']): continue
                score = r['rel'] * 2 + (r['secRel'] * 6 if r['secRel'] is not None else 0)
                tags = []
                if r['ma5'] and r['ma10'] and r['ma20'] and r['ma5'] > r['ma10'] > r['ma20']:
                    score += 12; tags.append('多头')
                elif r['ma10'] and r['c'] >= r['ma10']: score += 4
                if r['ma60'] and r['c'] >= r['ma60']: score += 8; tags.append('MA60上')
                dev20 = (r['c']/r['ma20'] - 1) * 100
                if dev20 <= 8: score += 6; tags.append('贴MA20')
                elif dev20 > 20: score -= 6
                if pool_day and pool_day.get(r['sym']): score += 10
                cand.append((score, r, '+'.join(tags)))
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
        if strat == 'S2':
            cand = []
            for r in rows:
                if r['j'] < 42 or r['pct'] <= 0.05: continue
                score = r['rel'] * 3 + (r['secRel'] * 6 if r['secRel'] is not None else 0)
                if pool_day and pool_day.get(r['sym']): score += 10
                cand.append((score, r, '红盘'))
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
        if strat == 'S3':
            cand = []
            for r in rows:
                if not (-9 <= r['pct'] <= -3): continue          # 当日深跌
                if r['ret20'] is None or r['ret20'] > 30: continue  # 非高标
                if r['ma30'] is None or r['ma30p'] is None: continue
                if not (r['c'] >= r['ma30'] and r['ma30'] > r['ma30p']): continue  # 长期趋势完好
                score = -r['pct'] * 2 + (r['secRel'] if r['secRel'] is not None else 0) + 6
                cand.append((score, r, 'MA30上深跌'))
            cand.sort(key=lambda x: -x[0])
            return cand[:10]
        if strat == 'S4':
            if not pool_day: return []
            cand = []
            for r in rows:
                if r['pct'] < -2: continue
                if not pool_day.get(r['sym']): continue
                score = r['rel'] * 3 + (r['secRel'] * 6 if r['secRel'] is not None else 0)
                cand.append((score, r, '池成员'))
            cand.sort(key=lambda x: -x[0])
            return cand[:10]
        if strat == 'S5':
            cand = []
            for r in rows:
                m = self.meta.get(r['sym']) or []
                lim = (zt_limit(r['sym'], m[0] if m else None) - 0.02) * 100
                if r['pct'] < lim: continue                       # 当日触及涨停
                if r['ret5'] is None: continue
                score = -r['ret5'] * 1.5 + (12 if r['hot'] else 0) + r['rel'] * 0.5
                cand.append((score, r, '涨停·5日%+.0f%%' % r['ret5']))
            cand.sort(key=lambda x: -x[0])
            return cand[:10]
        raise ValueError(strat)

STRATS = [
    ('S1', '趋势股(现行版)', '抗跌×近5日≤50%×MA20上趋势×20日3~50%, 板块配额2'),
    ('S2', '逆势红盘动量(原版)', '冰点日红盘, 相对大盘/板块超额打分, 板块配额2'),
    ('S3', '趋势内超跌反弹', 'MA30上方趋势完好×当日深跌-9~-3%, 博大反弹'),
    ('S4', '强势池抗跌', '强势池成员(回看3日)×当日抗跌, 按超额排序'),
    ('S5', '冰点日涨停', '当日涨停股, 偏好低位首启动(5日涨幅小)+强势板块'),
]

def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('冰点触发日: %d 天' % len(triggers))

    results = {}   # strat -> dict(days=[], trades=[], bench_by_day={})
    for code, sname, sdesc in STRATS:
        results[code] = dict(days=[], trades=[], skipped=0)
    for t in triggers:
        sc = bt.scan(t)
        if not sc: continue
        ni = day_idx[t] + 1
        nd = dates[ni]
        # 全市场等权基准(当日与次日都有bar)
        bsum = 0.0; bn = 0
        for sym, ix in bt.idx.items():
            je, jx = ix.get(t), ix.get(nd)
            if je is None or jx is None: continue
            if yk[sym][je][1] <= 0: continue
            bsum += (yk[sym][jx][1]/yk[sym][je][1] - 1) * 100; bn += 1
        bench = bsum/bn if bn else 0.0
        for code, sname, sdesc in STRATS:
            picked = bt.pick(t, code, sc)
            if not picked: continue
            rets = []
            for s, r, tag in picked:
                ix = bt.idx[r['sym']]
                je, jx = ix.get(t), ix.get(nd)
                if je is None or jx is None:
                    results[code]['skipped'] += 1; continue
                ret = (yk[r['sym']][jx][1]/yk[r['sym']][je][1] - 1) * 100
                rets.append(ret)
                results[code]['trades'].append(dict(date=t, code=r['sym'][2:], name=r['name'],
                    pct=round(r['pct'], 2), ind=r['ind'], ret=round(ret, 2), tag=tag))
            if not rets: continue
            results[code]['days'].append(dict(date=t, score=scores[t], nd=nd,
                mkt_avg=round(sc['mkt_avg'], 2), n=len(rets),
                avg=round(sum(rets)/len(rets), 2),
                win=round(sum(1 for x in rets if x > 0)/len(rets), 2),
                bench=round(bench, 2)))

    # ---- 汇总 ----
    summary = []
    for code, sname, sdesc in STRATS:
        R = results[code]
        rets = [x for d in R['days'] for x in []]  # placeholder
        all_rets = []
        # trades 已含每笔 ret
        all_rets = [tr['ret'] for tr in R['trades']]
        n = len(all_rets)
        if n == 0:
            summary.append(dict(code=code, name=sname, desc=sdesc, ndays=0, n=0))
            continue
        mean = sum(all_rets)/n
        srt = sorted(all_rets)
        med = srt[n//2] if n % 2 else (srt[n//2-1]+srt[n//2])/2
        win = sum(1 for x in all_rets if x > 0)/n
        day_avg = sum(d['avg'] for d in R['days'])/len(R['days'])
        bench_avg = sum(d['bench'] for d in R['days'])/len(R['days'])
        comp = 1.0; bcomp = 1.0
        for d in R['days']:
            comp *= (1 + d['avg']/100); bcomp *= (1 + d['bench']/100)
        # 2026年后子窗口(池数据齐全)
        d26 = [d for d in R['days'] if d['date'] >= '2026-01-05']
        t26 = [tr for tr in R['trades'] if tr['date'] >= '2026-01-05']
        m26 = sum(tr['ret'] for tr in t26)/len(t26) if t26 else None
        w26 = (sum(1 for tr in t26 if tr['ret'] > 0)/len(t26)) if t26 else None
        best = max(R['trades'], key=lambda x: x['ret'])
        worst = min(R['trades'], key=lambda x: x['ret'])
        summary.append(dict(code=code, name=sname, desc=sdesc, ndays=len(R['days']), n=n,
                            mean=round(mean, 2), med=round(med, 2), win=round(win, 3),
                            day_avg=round(day_avg, 2), bench_avg=round(bench_avg, 2),
                            excess=round(day_avg - bench_avg, 2),
                            comp=round((comp-1)*100, 1), bcomp=round((bcomp-1)*100, 1),
                            n26=len(t26), mean26=(round(m26, 2) if m26 is not None else None),
                            win26=(round(w26, 3) if w26 is not None else None),
                            best='%s %s %+.1f%% (%s)' % (best['name'], best['date'][5:], best['ret'], best['tag']),
                            worst='%s %s %+.1f%% (%s)' % (worst['name'], worst['date'][5:], worst['ret'], worst['tag']),
                            skipped=R['skipped']))

    print('\n================ 多策略对比 (冰点日收盘买TOP10 → 次日收盘卖) ================')
    print('窗口: %s -> %s | 冰点触发 %d 天\n' % (dates[0], dates[-1], len(triggers)))
    hdr = '%-4s %-14s %-5s %-5s %-8s %-8s %-6s %-9s %-9s %-8s %-8s'
    print(hdr % ('策略', '名称', '天数', '笔数', '单笔均值', '中位数', '胜率', '日均超额', '复利(示意)', '26后均值', '26后胜率'))
    for s in summary:
        if s['n'] == 0:
            print('%-4s %-14s 无交易' % (s['code'], s['name'])); continue
        print(hdr % (s['code'], s['name'], s['ndays'], s['n'],
                     '%+.2f%%' % s['mean'], '%+.2f%%' % s['med'], '%.0f%%' % (s['win']*100),
                     '%+.2f%%' % s['excess'], '%+.1f%%' % s['comp'],
                     ('%+.2f%%' % s['mean26']) if s['mean26'] is not None else '--',
                     ('%.0f%%' % (s['win26']*100)) if s['win26'] is not None else '--'))
        print('     最佳: %s | 最差: %s' % (s['best'], s['worst']))

    out = dict(window=[dates[0], dates[-1]], ndays_trigger=len(triggers), bd_th=BD_TH,
               strats=[dict(code=c, name=n, desc=d) for c, n, d in STRATS],
               summary=summary,
               days={c: results[c]['days'] for c, _, _ in STRATS},
               trades={c: results[c]['trades'] for c, _, _ in STRATS})
    with open('/Users/michael/Documents/golden-system/td9-screener/backtest_bingdian_multi_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_bingdian_multi_data.json / backtest_bingdian_multi.html')

def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    trades = json.dumps(out['trades'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>冰点策略 · 5套选股策略对比回测</title>
<script src="./echarts.min.js"></script>
<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f1f3f6;margin:0;padding:18px;color:#212529}
.wrap{max-width:1240px;margin:0 auto}
h1{font-size:19px;margin:2px 0 4px}
.sub{font-size:12px;color:#868e96;margin-bottom:14px;line-height:1.7}
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
<h1>🧊 冰点策略 · 5 套选股思路对比回测</h1>
<div class="sub">共同口径: 情绪温度 &lt; 30 的触发日 <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（触发 __ND__ 天）· K线源: 全市场年K收盘序列 · 基准: 全市场等权次日涨幅<br>
__SDESC__</div>
<div class="panel"><div style="font-size:13px;font-weight:600;margin-bottom:6px">策略总览（按日均超额降序）</div><table id="sumtbl"></table></div>
<div class="panel"><div style="font-size:13px;font-weight:600;margin-bottom:4px">逐触发日 TOP10 次日均值（%）· 每策略一柱</div><div id="chart" style="width:100%;height:400px"></div></div>
<div class="panel"><div style="font-size:13px;font-weight:600;margin-bottom:6px">逐触发日 × 策略明细</div><div class="tblbox"><table id="daytbl"></table></div></div>
<div class="panel note">口径说明: ① 五套策略共用同一触发日与基准, 差异仅在选股画像; ② S4 强势池数据 2026-01-05 起才有, 之前的触发日 S4 空仓(未计入), "26后"列为 2026-01-05 后子窗口的公平对比; ③ 复利为逐触发日示意累乘, 连续触发日持仓实际重叠, 非可执行账户; ④ 次日停牌无报价的笔已剔除; ⑤ 年K仅收盘价, 无量能/最高最低/盘中字段, 涉及量价的过滤均未纳入; ⑥ 仅为策略研究, 不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, TRD = __TRD__, STLIST = __ST__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
// 总览表
var h = '<tr><th>策略</th><th>画像</th><th>触发天数</th><th>笔数</th><th>单笔均值</th><th>中位数</th><th>胜率</th><th>日均超额</th><th>复利(示意)</th><th>26后均值</th><th>26后胜率</th><th>最佳单笔</th><th>最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  if(!s.n){ h += '<tr><td><b>'+c+'</b> '+s.name+'</td><td colspan="12" style="color:#868e96">无交易</td></tr>'; return; }
  h += '<tr'+(i===0?' class="best"':'')+'><td><b>'+c+'</b> '+s.name+'</td><td style="font-size:11px;color:#868e96">'+s.desc+'</td>'
    + '<td>'+s.ndays+'</td><td>'+s.n+'</td>'
    + '<td class="'+(s.mean>=0?'up':'dn')+'">'+(s.mean>0?'+':'')+s.mean.toFixed(2)+'%</td>'
    + '<td class="'+(s.med>=0?'up':'dn')+'">'+(s.med>0?'+':'')+s.med.toFixed(2)+'%</td>'
    + '<td>'+Math.round(s.win*100)+'%</td>'
    + '<td class="'+(s.excess>=0?'up':'dn')+'">'+(s.excess>0?'+':'')+s.excess.toFixed(2)+'%</td>'
    + '<td class="'+(s.comp>=s.bcomp?'up':'dn')+'">'+(s.comp>0?'+':'')+s.comp.toFixed(1)+'%</td>'
    + '<td>'+(s.mean26!=null?((s.mean26>0?'+':'')+s.mean26.toFixed(2)+'%'):'--')+'</td>'
    + '<td>'+(s.win26!=null?Math.round(s.win26*100)+'%':'--')+'</td>'
    + '<td style="font-size:11px" class="up">'+s.best+'</td>'
    + '<td style="font-size:11px" class="dn">'+s.worst+'</td></tr>';
});
document.getElementById('sumtbl').innerHTML = h;
// 分组柱状图
var cats = [], ser = {};
STLIST.forEach(function(s){ ser[s.code] = []; });
var allDays = {};
STLIST.forEach(function(s){ (DAYS[s.code]||[]).forEach(function(d){ allDays[d.date] = d.score; }); });
cats = Object.keys(allDays).sort();
var series = order.map(function(c, i){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  return {name: c + ' ' + byCode[c].name, type: 'bar', data: cats.map(function(dt){ return m[dt] != null ? m[dt] : null; }), barMaxWidth: 12};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d = (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d ? d.bench : null; }), symbol: 'circle', symbolSize: 5, itemStyle: {color: '#1c7ed6'}, lineStyle: {width: 2}});
var ch = echarts.init(document.getElementById('chart'));
ch.setOption({tooltip:{trigger:'axis'},legend:{top:0,type:'scroll',textStyle:{fontSize:11}},
  grid:{left:44,right:20,top:40,bottom:56},
  xAxis:{type:'category',data:cats.map(function(d){return d.slice(2);}),axisLabel:{rotate:45,fontSize:10,color:'#868e96'}},
  yAxis:{type:'value',axisLabel:{formatter:'{value}%'},splitLine:{lineStyle:{color:'#f0f2f7'}}},
  series: series});
// 逐日明细
var t1 = '<tr><th>触发日</th><th>温度</th><th>次日大盘</th>' + order.map(function(c){ return '<th>'+c+'</th>'; }).join('') + '</tr>';
cats.forEach(function(dt){
  var row = '<tr><td>'+dt+'</td><td><b>'+allDays[dt]+'</b></td>';
  var bench = null;
  order.forEach(function(c, i){
    var d = (DAYS[c]||[]).find(function(x){ return x.date === dt; });
    if(d && bench == null) bench = d.bench;
    row += d ? '<td class="'+(d.avg>=0?'up':'dn')+'">'+(d.avg>0?'+':'')+d.avg.toFixed(2)+'%</td>' : '<td style="color:#ced4da">—</td>';
  });
  t1 += row + '</tr>';
});
document.getElementById('daytbl').innerHTML = t1;
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'])
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days).replace('__TRD__', trades)
            .replace('__ST__', strats))
    p = '/Users/michael/Documents/golden-system/td9-screener/backtest_bingdian_multi.html'
    open(p, 'w', encoding='utf-8').write(html)

if __name__ == '__main__':
    main()
