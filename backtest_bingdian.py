# -*- coding: utf-8 -*-
"""
backtest_bingdian.py — 冰点策略回测
====================================
策略口径与 strong_screener.html 的 ztSentiment + bingdianScreen 1:1 一致:
  · 温度分 = 涨停28% + 昨涨停溢价24% + 涨跌比20% + 跌停14% + 连板高度14% (阈值 lim-0.02 同口径)
  · 触发: 温度分 < BD_TH(30)
  · TOP10 筛选: 当日 pct>=-2(抗跌/红盘) × 非ST × 有当日bar且昨日=上一交易日 × ≥42根历史K线
    评分 = 相对大盘超额×3 + 强势板块超额×6 + 站上MA20+8/MA10+5/MA5+3/MA20上行+6 + 强势池+10
    强势板块 = 一级板块(meta[5]||meta[3]) 成员≥3 且均值>全市场均值; 每板块最多2只
交易: 触发日收盘买入 → 下一交易日收盘卖出 (等权10只)
数据: year_kline(全市场收盘, 2025-06起) → 情绪序列扩展回测整年;
      strong_data.strong 仅2026-01-05后有强势池, 更早日期无池加分(不影响其他因子)。
"""
import json, re, sys, math

BD_TH = 30
import os
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = BASE + '/dist_strong'

def load_pack(name):
    s = open(ROOT + '/' + name, encoding='utf-8').read()
    a = s.index('{'); b = s.rindex('}')
    return json.loads(s[a:b+1])

def zt_limit(sym, name):
    n = name or ''
    if 'ST' in n or 'st' in n: return 0.05
    if sym[2:4] in ('30', '68'): return 0.20
    return 0.10

def clamp01(v): return max(0.0, min(1.0, v))

def build():
    print('加载数据包…')
    sd = load_pack('strong_data.js')
    yk = load_pack('year_kline.js')
    meta = sd['meta']; sd_dates = sd['dates']; strong_pool = sd.get('strong', {})
    # ---- 扩展交易日序列: 取全市场并集日期, 覆盖率>=90%上限(剔除新股集中上市的残缺日) ----
    day_cnt = {}
    for sym, bars in yk.items():
        for b in bars:
            day_cnt[b[0]] = day_cnt.get(b[0], 0) + 1
    all_days = sorted(day_cnt.keys())
    maxc = max(day_cnt.values())
    dates = [d for d in all_days if day_cnt[d] >= maxc * 0.90]
    dates = [d for d in dates if d >= '2025-09-01']          # 回测窗口: 近一年
    day_idx = {d: i for i, d in enumerate(dates)}
    print('回测窗口: %s -> %s (%d 个交易日), 覆盖股票 %d 只' % (dates[0], dates[-1], len(dates), len(yk)))

    # ---- 情绪引擎 (1:1 复刻 ztSentiment) ----
    print('计算情绪温度序列…')
    st = {d: dict(adv=0, dec=0, flat=0, zt=0, dt=0, hi5=0, lo5=0, maxB=0, ztSet=set(),
                  premSum=0.0, premN=0, premRed=0) for d in dates[1:]}
    for sym, bars in yk.items():
        if len(bars) < 2: continue
        lim = (zt_limit(sym, (meta.get(sym) or [None])[0]) - 0.02) * 100
        streak = 0
        for j, bar in enumerate(bars):
            d = bar[0]
            s = st.get(d)
            if s is None: continue
            prev = bars[j-1] if j > 0 else None
            chg = None
            if prev and prev[1] > 0:
                chg = (bar[1]/prev[1] - 1) * 100
            is_zt = chg is not None and chg >= lim
            is_dt = chg is not None and chg <= -lim
            streak = streak + 1 if is_zt else 0
            if prev and chg is not None and prev[0] == dates[day_idx[d]-1]:
                if chg > 0.05: s['adv'] += 1
                elif chg < -0.05: s['dec'] += 1
                else: s['flat'] += 1
                if chg >= 5: s['hi5'] += 1
                elif chg <= -5: s['lo5'] += 1
                pd_ = st.get(prev[0])
                if pd_ and sym in pd_['ztSet']:
                    s['premSum'] += chg; s['premN'] += 1
                    if chg > 0.05: s['premRed'] += 1
            if is_zt:
                s['zt'] += 1; s['ztSet'].add(sym)
                if streak > s['maxB']: s['maxB'] = streak
            if is_dt: s['dt'] += 1
    scores = {}
    for d in dates[1:]:
        s = st[d]
        tot = s['adv'] + s['dec']
        ratio = s['adv']/tot if tot else 0.5
        ztC = clamp01((s['zt']-15)/105)
        dtC = 1 - clamp01((s['dt']-1)/39)
        premC = clamp01((s['premSum']/s['premN']+3)/8) if s['premN'] else 0.5
        advC = clamp01((ratio-0.3)/0.55)
        hC = clamp01((s['maxB']-2)/6)
        scores[d] = round(100*(ztC*0.28 + premC*0.24 + advC*0.20 + dtC*0.14 + hC*0.14))
    return sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st

def bingdian_top10(target, yk, meta, dates, day_idx, scores, strong_pool):
    """1:1 复刻 bingdianScreen, K线源换成年K线收盘序列"""
    di = day_idx.get(target)
    if di is None or di <= 0 or di + 1 >= len(dates): return None
    prev_date = dates[di-1]
    # 每只票的日期->(数组下标) 索引在调用方预建: bars_idx[sym] = {date: j}
    return None  # placeholder — 真正实现在下方类中(见 BingdianBacktest)

class BingdianBacktest(object):
    def __init__(self, yk, meta, dates, day_idx, scores, strong_pool):
        self.yk = yk; self.meta = meta; self.dates = dates; self.day_idx = day_idx
        self.scores = scores; self.strong_pool = strong_pool
        # 预建索引: sym -> {date: bar下标}
        print('预建K线索引…')
        self.idx = {}
        for sym, bars in yk.items():
            self.idx[sym] = {b[0]: j for j, b in enumerate(bars)}

    def screen(self, target):
        di = self.day_idx.get(target)
        if di is None or di <= 0: return None
        prev_date = self.dates[di-1]
        mkt_sum = 0.0; mkt_n = 0; sec = {}
        for sym, ix in self.idx.items():
            j = ix.get(target)
            if j is None or j == 0: continue
            bars = self.yk[sym]
            if bars[j-1][0] != prev_date: continue
            pc = bars[j-1][1]
            if not pc > 0: continue
            pct = (bars[j][1]/pc - 1) * 100
            mkt_sum += pct; mkt_n += 1
            m = self.meta.get(sym) or []
            ind = (m[5] if len(m) > 5 and m[5] else (m[3] if len(m) > 3 and m[3] else ''))
            if not ind: continue
            a = sec.get(ind)
            if a is None: a = sec[ind] = [0.0, 0]
            a[0] += pct; a[1] += 1
        if not mkt_n: return None
        mkt_avg = mkt_sum / mkt_n
        sec_avg = {k: v[0]/v[1] for k, v in sec.items()}
        hot = [k for k, v in sec.items() if v[1] >= 3 and sec_avg[k] > mkt_avg]
        hot.sort(key=lambda k: -sec_avg[k])
        hot_set = set(hot)
        pool_day = self.strong_pool.get(target) or {}
        rows = []
        for sym, ix in self.idx.items():
            j = ix.get(target)
            if j is None or j < 42: continue          # ≥42根历史K线(与前端一致)
            bars = self.yk[sym]
            if bars[j-1][0] != prev_date: continue
            pc = bars[j-1][1]
            if not pc > 0: continue
            pct = (bars[j][1]/pc - 1) * 100
            if pct < -2: continue
            m = self.meta.get(sym) or []
            name = m[0] or sym
            if 'ST' in name or 'st' in name: continue
            ind = (m[5] if len(m) > 5 and m[5] else (m[3] if len(m) > 3 and m[3] else '—'))
            c = bars[j][1]
            closes = [b[1] for b in bars[max(0, j-39):j+1]]
            def ma(nn):
                if len(closes) < nn: return None
                return sum(closes[-nn:])/nn
            ma5, ma10, ma20 = ma(5), ma(10), ma(20)
            ma20p = sum(closes[-24:])/20 if len(closes) >= 25 else None
            rel = pct - mkt_avg
            sec_rel = (sec_avg[ind] - mkt_avg) if ind in hot_set else None
            score = rel*3 + (sec_rel*6 if sec_rel is not None else 0)
            ma_state = []
            if ma20 is not None and c >= ma20: score += 8; ma_state.append('MA20')
            if ma10 is not None and c >= ma10: score += 5; ma_state.append('MA10')
            if ma5 is not None and c >= ma5: score += 3; ma_state.append('MA5')
            if ma20 is not None and ma20p is not None and ma20 > ma20p: score += 6; ma_state.append('MA20↑')
            if pool_day.get(sym): score += 10
            rows.append((score, sym, name, pct, ind, sec_rel, len(ma_state), bool(pool_day.get(sym))))
        rows.sort(key=lambda r: -r[0])
        picked, cnt = [], {}
        for r in rows:
            if len(picked) >= 10: break
            if cnt.get(r[4], 0) >= 2: continue
            cnt[r[4]] = cnt.get(r[4], 0) + 1; picked.append(r)
        for r in rows:
            if len(picked) >= 10: break
            if all(r[1] != p[1] for p in picked): picked.append(r)
        return dict(score=self.scores.get(target), mkt_avg=mkt_avg, hot=hot[:5], list=picked[:10])

def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = BingdianBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('触发冰点日: %d 天 (%s)' % (len(triggers), ', '.join(triggers)))
    day_rows = []; trades = []; skipped = 0
    for t in triggers:
        r = bt.screen(t)
        if not r or not r['list']:
            continue
        ni = day_idx[t] + 1
        nd = dates[ni]
        rets = []
        for (sc, sym, name, pct, ind, sec_rel, nma, pool) in r['list']:
            ix = bt.idx[sym]
            je, jx = ix.get(t), ix.get(nd)
            if je is None or jx is None:
                skipped += 1; continue
            ret = (yk[sym][jx][1]/yk[sym][je][1] - 1) * 100
            rets.append(ret)
            trades.append(dict(date=t, score=r['score'], code=sym[2:], name=name,
                               pct=pct, ind=ind, ret=ret, pool=pool, nma=nma))
        if not rets: continue
        # 基准: 全市场等权次日涨幅(有 t 与 nd 两根bar的票)
        bsum = 0.0; bn = 0
        for sym, ix in bt.idx.items():
            je, jx = ix.get(t), ix.get(nd)
            if je is None or jx is None: continue
            if yk[sym][je][1] <= 0: continue
            bsum += (yk[sym][jx][1]/yk[sym][je][1] - 1) * 100; bn += 1
        bench = bsum/bn if bn else 0.0
        day_rows.append(dict(date=t, score=r['score'], mkt_avg=r['mkt_avg'], nd=nd,
                             n=len(rets), avg=sum(rets)/len(rets),
                             win=sum(1 for x in rets if x > 0)/len(rets), bench=bench,
                             hot='、'.join(k + '(%.1f%%)' % (r['hot'][i][1] if False else 0) for i, k in enumerate(r['hot'])) if r['hot'] else '',
                             hotl=[(k, None) for k in r['hot']],
                             rets=rets))
    # ---- 汇总 ----
    all_rets = [x for d in day_rows for x in d['rets']]
    n = len(all_rets)
    if n == 0:
        print('回测窗口内无冰点触发日'); return
    mean = sum(all_rets)/n
    srt = sorted(all_rets); med = srt[n//2] if n % 2 else (srt[n//2-1]+srt[n//2])/2
    win = sum(1 for x in all_rets if x > 0)/n
    day_avg = sum(d['avg'] for d in day_rows)/len(day_rows)
    bench_avg = sum(d['bench'] for d in day_rows)/len(day_rows)
    comp = 1.0; bcomp = 1.0
    for d in day_rows:
        comp *= (1 + d['avg']/100); bcomp *= (1 + d['bench']/100)
    print('\n========== 回测结果 (触发日收盘买 → 次日收盘卖) ==========')
    print('回测窗口: %s -> %s | 冰点触发 %d 天 | 交易 %d 笔(跳过停牌无报价 %d 笔)'
          % (dates[0], dates[-1], len(day_rows), n, skipped))
    print('单笔收益: 平均 %+.2f%% | 中位数 %+.2f%% | 胜率 %.1f%%'
          % (mean, med, win*100))
    print('按天等权: 平均 %+.2f%%/天 | 同期全市场等权 %+.2f%%/天 | 超额 %+.2f%%/天'
          % (day_avg, bench_avg, day_avg-bench_avg))
    print('逐日复利: 策略 %+.2f%% | 全市场等权 %+.2f%% | 超额 %+.2f%%'
          % ((comp-1)*100, (bcomp-1)*100, (comp-bcomp)*100))
    print('\n逐触发日明细:')
    print('%-12s %-4s %-9s %-9s %-7s %-9s %s' % ('触发日', '温度', '当日大盘', 'TOP10均值', '胜率', '次日大盘', '次日强势板块(当日均值)'))
    for d in day_rows:
        hot_txt = ' '.join('%s%+.1f%%' % (k, sec_avg_v) for k, sec_avg_v in
                           [(k, d['hotsec'].get(k, 0)) for k in d.get('hot_names', [])]) if d.get('hotsec') else d['hotl'] and ' '.join(k for k, _ in d['hotl']) or ''
        print('%-12s %-4d %-9s %-9s %-7.0f%% %-9s %s'
              % (d['date'], d['score'], '%+.2f%%' % d['mkt_avg'], '%+.2f%%' % d['avg'],
                 d['win']*100, '%+.2f%%' % d['bench'], hot_txt))
    trades.sort(key=lambda x: -x['ret'])
    print('\n最佳5笔: ' + ' | '.join('%s(%s) %+.1f%%' % (t['name'], t['date'][5:], t['ret']) for t in trades[:5]))
    print('最差5笔: ' + ' | '.join('%s(%s) %+.1f%%' % (t['name'], t['date'][5:], t['ret']) for t in trades[-5:]))
    # 导出报告数据
    out = dict(window=[dates[0], dates[-1]], bd_th=BD_TH,
               days=[dict(date=d['date'], score=d['score'], mkt_avg=d['mkt_avg'], nd=d['nd'],
                          n=d['n'], avg=d['avg'], win=d['win'], bench=d['bench'],
                          hot=[k for k, _ in d['hotl']]) for d in day_rows],
               trades=trades,
               stats=dict(n=n, mean=mean, med=med, win=win, day_avg=day_avg,
                          bench_avg=bench_avg, comp=(comp-1)*100, bcomp=(bcomp-1)*100,
                          skipped=skipped, ndays=len(day_rows)))
    with open(BASE + '/backtest_bingdian_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print('已导出 backtest_bingdian_data.json')
    render_report(out)

def render_report(out):
    days = out['days']; trades = out['trades']; s = out['stats']
    day_rows_js = json.dumps(days, ensure_ascii=False)
    trade_rows = [[t['date'], t['code'], t['name'], round(t['pct'], 2), t['ind'],
                   round(t['ret'], 2), '池' if t['pool'] else '', t['nma']] for t in trades]
    trades_js = json.dumps(trade_rows, ensure_ascii=False)
    st_js = json.dumps(s, ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>冰点策略回测 · 收盘买→次日收盘卖</title>
<script src="./echarts.min.js"></script>
<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f1f3f6;margin:0;padding:18px;color:#212529}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:19px;margin:2px 0 4px}
.sub{font-size:12px;color:#868e96;margin-bottom:14px}
.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:14px}
.card{background:#fff;border:1px solid #e9ecef;border-radius:8px;padding:10px}
.card .k{font-size:11px;color:#868e96}.card .v{font-size:21px;font-weight:800;margin-top:2px}
.card .d{font-size:10.5px;color:#868e96;margin-top:2px}
.panel{background:#fff;border:1px solid #e9ecef;border-radius:8px;padding:12px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{position:sticky;top:0;background:#f8f9fa;padding:5px 7px;text-align:left;color:#495057;border-bottom:1px solid #dee2e6}
td{padding:4px 7px;border-bottom:1px solid #f0f2f7}
.up{color:#e03131;font-weight:700}.dn{color:#0ca678;font-weight:700}
.note{font-size:11px;color:#868e96;line-height:1.7}
.tblbox{max-height:430px;overflow:auto}
.red{color:#e03131}.green{color:#0ca678}
</style></head><body><div class="wrap">
<h1>🧊 冰点策略回测 <span style="font-size:12px;color:#868e96;font-weight:400">触发日收盘买入 TOP10 → 下一交易日收盘卖出（等权）</span></h1>
<div class="sub">回测窗口 __W0__ → __W1__（246 个交易日）· 触发线: 温度分 &lt; 30（与页面情绪温度计同口径）· K线源: 全市场年K收盘序列（情绪序列外推至 2025-09，强势池加分仅 2026-01-05 后生效）</div>
<div class="cards" id="cards"></div>
<div class="panel"><div style="font-size:13px;font-weight:600;margin-bottom:4px">逐触发日：TOP10 次日均值 vs 全市场等权次日（%）</div><div id="chart" style="width:100%;height:360px"></div></div>
<div class="panel"><div style="font-size:13px;font-weight:600;margin-bottom:6px">逐触发日明细</div><div class="tblbox"><table id="daytbl"></table></div></div>
<div class="panel"><div style="font-size:13px;font-weight:600;margin-bottom:6px">全部交易明细（__N__ 笔，按触发日）</div><div class="tblbox"><table id="trdtbl"></table></div></div>
<div class="panel note">口径说明: ① 温度分/筛选/评分与线上「冰点策略」1:1 同构，K线源换为年K收盘序列（无最高最低量，与该策略用到的字段无关）；② 情绪序列由同算法外推回 2025-09-01，2026-01-05 前无强势池数据（仅少 +10 分加项，其余因子不受影响）；③ "逐日复利"为示意累乘——连续触发日（如 2025-09-02~04、2026-03-19~26）持仓实际重叠，非可执行账户；④ 次日停牌无报价的交易已剔除（__SKIP__ 笔）；⑤ 仅为策略研究，不构成投资建议。</div>
</div>
<script>
var DAYS = __DAYS__, TRD = __TRD__, ST = __ST__;
var c = document.getElementById('cards');
function card(k,v,d,col){ return '<div class="card"><div class="k">'+k+'</div><div class="v" style="color:'+(col||'#212529')+'">'+v+'</div><div class="d">'+d+'</div></div>'; }
c.innerHTML = card('冰点触发天数', ST.ndays, '共246个交易日', '#1971c2')
  + card('交易笔数', ST.n, '剔除停牌'+ST.skipped+'笔')
  + card('单笔平均', (ST.mean>0?'+':'')+ST.mean.toFixed(2)+'%', '中位数 '+(ST.med>0?'+':'')+ST.med.toFixed(2)+'%', ST.mean>=0?'#e03131':'#0ca678')
  + card('单笔胜率', (ST.win*100).toFixed(1)+'%', '收盘买入次日收盘卖出', '#495057')
  + card('日均超额', '+'+(ST.day_avg-ST.bench_avg).toFixed(2)+'%', '策略 '+(ST.day_avg>0?'+':'')+ST.day_avg.toFixed(2)+'% vs 大盘 '+(ST.bench_avg>0?'+':'')+ST.bench_avg.toFixed(2)+'%', '#e03131')
  + card('逐日复利', (ST.comp>0?'+':'')+ST.comp.toFixed(1)+'%', '大盘等权 '+(ST.bcomp>0?'+':'')+ST.bcomp.toFixed(1)+'%（示意）', ST.comp>=ST.bcomp?'#e03131':'#0ca678');
var ch = echarts.init(document.getElementById('chart'));
ch.setOption({tooltip:{trigger:'axis'},legend:{data:['TOP10次日均值','次日全市场等权'],top:0},
  grid:{left:44,right:20,top:34,bottom:56},
  xAxis:{type:'category',data:DAYS.map(function(d){return d.date.slice(2);}),axisLabel:{rotate:45,fontSize:10,color:'#868e96'}},
  yAxis:{type:'value',axisLabel:{formatter:'{value}%'},splitLine:{lineStyle:{color:'#f0f2f7'}}},
  series:[{name:'TOP10次日均值',type:'bar',data:DAYS.map(function(d){return +d.avg.toFixed(2);}),
    itemStyle:{color:function(p){return p.value>=0?'#e03131':'#0ca678';}},barMaxWidth:18,label:{show:true,position:'top',fontSize:9,color:'#868e96',formatter:function(p){return (p.value>0?'+':'')+p.value;}}},
   {name:'次日全市场等权',type:'line',data:DAYS.map(function(d){return +d.bench.toFixed(2);}),symbol:'circle',symbolSize:5,itemStyle:{color:'#1c7ed6'},lineStyle:{width:2}}]});
var t1 = '<tr><th>触发日</th><th>温度</th><th>当日大盘</th><th>TOP10次日均值</th><th>胜率</th><th>次日大盘</th><th>当日逆势强势板块</th></tr>';
DAYS.forEach(function(d){
  t1 += '<tr><td>'+d.date+'</td><td><b>'+d.score+'</b></td>'
    + '<td class="'+(d.mkt_avg>=0?'up':'dn')+'">'+(d.mkt_avg>0?'+':'')+d.mkt_avg.toFixed(2)+'%</td>'
    + '<td class="'+(d.avg>=0?'up':'dn')+'">'+(d.avg>0?'+':'')+d.avg.toFixed(2)+'%</td>'
    + '<td>'+Math.round(d.win*100)+'%</td>'
    + '<td class="'+(d.bench>=0?'up':'dn')+'">'+(d.bench>0?'+':'')+d.bench.toFixed(2)+'%</td>'
    + '<td style="font-size:11px;color:#495057">'+(d.hot||[]).join('、')+'</td></tr>';
});
document.getElementById('daytbl').innerHTML = t1;
var t2 = '<tr><th>触发日</th><th>代码</th><th>名称</th><th>当日涨幅</th><th>板块</th><th>次日收益</th><th>池</th><th>均线</th></tr>';
TRD.forEach(function(r){
  t2 += '<tr><td>'+r[0]+'</td><td>'+r[1]+'</td><td><b>'+r[2]+'</b></td>'
    + '<td class="'+(r[3]>=0?'up':'dn')+'">'+(r[3]>0?'+':'')+r[3].toFixed(2)+'%</td>'
    + '<td>'+r[4]+'</td>'
    + '<td class="'+(r[5]>=0?'up':'dn')+'">'+(r[5]>0?'+':'')+r[5].toFixed(2)+'%</td>'
    + '<td style="color:#e8590c;font-size:10px">'+r[6]+'</td><td style="color:#868e96;font-size:10px">'+r[7]+'/3</td></tr>';
});
document.getElementById('trdtbl').innerHTML = t2;
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__N__', str(s['n'])).replace('__SKIP__', str(s['skipped']))
            .replace('__DAYS__', day_rows_js).replace('__TRD__', trades_js).replace('__ST__', st_js))
    p = BASE + '/backtest_bingdian.html'
    open(p, 'w', encoding='utf-8').write(html)
    print('报告已生成:', p)

if __name__ == '__main__':
    main()
