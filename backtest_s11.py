# -*- coding: utf-8 -*-
"""
backtest_s11.py — S11 最终综合策略: 三桶 TOP10 (S1~S10c 全部结论合成)
====================================================================
三桶:
  弹性桶 ← S5: 冰点日触及涨停 × 低位首启动(5日≤20%), 评分=-5日涨幅×1.5+强势板块12+超额0.5+池8
  趋势桶 ← S1: 20日3~50% × MA20上且上行, 评分=超额×2+板块超额×6+多头12+MA60上8+贴线6+池10
  回调桶 ← S9d+S10c: 近5日调整[-10,0) × 近20日≥10% × MA20上且上行, 评分=20日×0.1+贴线8+超额1.5+强板块6
统一风控(趋势/回调桶全量, 弹性桶仅剔高标):
  非ST × 次新剔除(<60根K) × 深跌剔除(当日<-3%) × 板块5日≥0(未走弱, S6教训) × 妖股剔除(5日>20%或20日>50%) × 每板块≤2
配额变体: S11=5弹+3趋+2调 | S11b=7弹+3趋(S7c+风控) | S11c=6弹+2趋+2调
交易: 触发日收盘等权买 TOP10 → 次日收盘卖; 弹性不足依次由趋势/回调桶补足。
"""
import json, sys

sys.path.insert(0, '/Users/michael/Documents/golden-system/td9-screener')
from backtest_bingdian import build, BD_TH, zt_limit  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS  # noqa


def sec5_map(sc):
    agg = {}
    for r in sc['rows'].values():
        if r['ret5'] is None: continue
        a = agg.setdefault(r['ind'], [0.0, 0]); a[0] += r['ret5']; a[1] += 1
    return {k: v[0] / v[1] for k, v in agg.items() if v[1] >= 3}


def pick_s11(bt, sc, ela_q, trd_q, adj_q):
    rows = [r for r in sc['rows'].values()
            if 'ST' not in r['name'] and 'st' not in r['name'] and r['j'] >= 60]
    s5 = sec5_map(sc)
    pool_day = None
    di = bt.day_idx[sc['target']]
    for back in range(0, 4):
        pool_day = bt.strong_pool.get(bt.dates[di - back])
        if pool_day: break

    def sec_ok(r):                       # 板块未走弱(S6教训)
        v = s5.get(r['ind'])
        return v is None or v >= 0

    ela, trd, adj = [], [], []
    for r in rows:
        if r['ret5'] is None: continue
        # ---- 弹性桶候选 ----
        m = bt.meta.get(r['sym']) or []
        lim = (zt_limit(r['sym'], m[0] if m else None) - 0.02) * 100
        if r['pct'] >= lim and r['ret5'] <= 20:
            score = -r['ret5'] * 1.5 + (12 if r['hot'] else 0) + r['rel'] * 0.5
            if pool_day and pool_day.get(r['sym']): score += 8
            ela.append((score, r, '弹性·涨停'))
        # ---- 风控层(趋势/回调桶) ----
        if r['pct'] < -3: continue
        if r['ret5'] > 20: continue                       # 妖股
        if r['ret20'] is not None and r['ret20'] > 50: continue
        if not sec_ok(r): continue
        if r['ma20'] is None or r['ma20p'] is None: continue
        ma20up = r['ma20'] > r['ma20p']
        # ---- 趋势桶候选 ----
        if r['ret20'] is not None and 3 <= r['ret20'] <= 50 and r['c'] >= r['ma20'] and ma20up:
            score = r['rel'] * 2 + (r['secRel'] * 6 if r['secRel'] is not None else 0)
            if r['ma5'] and r['ma10'] and r['ma5'] > r['ma10'] > r['ma20']: score += 12
            if r['ma60'] and r['c'] >= r['ma60']: score += 8
            dev20 = (r['c'] / r['ma20'] - 1) * 100
            if dev20 <= 6: score += 6
            elif dev20 > 20: score -= 6
            if pool_day and pool_day.get(r['sym']): score += 10
            trd.append((score, r, '趋势·多头'))
        # ---- 回调桶候选 ----
        if r['ret20'] is not None and r['ret20'] >= 10 and -10 <= r['ret5'] < 0 \
                and r['c'] >= r['ma20'] and ma20up:
            score = r['ret20'] * 0.1 + r['rel'] * 1.5
            dev20 = (r['c'] / r['ma20'] - 1) * 100
            if dev20 <= 6: score += 8
            if r['hot']: score += 6
            adj.append((score, r, '回调·贴线'))
    ela.sort(key=lambda x: -x[0]); trd.sort(key=lambda x: -x[0]); adj.sort(key=lambda x: -x[0])

    picked, cnt = [], {}
    def take(cand, quota):
        n = 0
        for s, r, tag in cand:
            if n >= quota or len(picked) >= 10: break
            if cnt.get(r['ind'], 0) >= 2: continue
            if any(r['sym'] == p[1]['sym'] for p in picked): continue
            cnt[r['ind']] = cnt.get(r['ind'], 0) + 1
            picked.append((s, r, tag)); n += 1
    take(ela, ela_q)
    take(trd, trd_q)
    take(adj, adj_q)
    take(ela, 10); take(trd, 10); take(adj, 10)   # 不足依次回填
    return picked[:10]


S11_STRATS = [
    ('S11', '最终版: 5弹+3趋+2调', '涨停5 + 趋势3 + 回调贴线2, 统一风控层'),
    ('S11b', '最终版: 7弹+3趋', 'S7c配额+风控层(剔妖/板块未走弱/剔次新)'),
    ('S11c', '最终版: 6弹+2趋+2调', '弹性略增, 趋势减1'),
]


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('冰点触发日: %d 天' % len(triggers))

    all_strats = [(c, n, d) for c, n, d in STRATS] + S11_STRATS
    results = {c: dict(days=[], trades=[], skipped=0) for c, _, _ in all_strats}

    for t in triggers:
        sc = bt.scan(t)
        if not sc: continue
        sc['target'] = t
        ni = day_idx[t] + 1
        nd = dates[ni]
        bsum = 0.0; bn = 0
        for sym, ix in bt.idx.items():
            je, jx = ix.get(t), ix.get(nd)
            if je is None or jx is None: continue
            if yk[sym][je][1] <= 0: continue
            bsum += (yk[sym][jx][1] / yk[sym][je][1] - 1) * 100; bn += 1
        bench = bsum / bn if bn else 0.0
        picks = {}
        for code, sname, sdesc in STRATS:
            picks[code] = bt.pick(t, code, sc)
        picks['S11'] = pick_s11(bt, sc, 5, 3, 2)
        picks['S11b'] = pick_s11(bt, sc, 7, 3, 0)
        picks['S11c'] = pick_s11(bt, sc, 6, 2, 2)
        for code, _, _ in all_strats:
            rets = []
            for s, r, tag in picks[code]:
                ix = bt.idx[r['sym']]
                je, jx = ix.get(t), ix.get(nd)
                if je is None or jx is None:
                    results[code]['skipped'] += 1; continue
                ret = (yk[r['sym']][jx][1] / yk[r['sym']][je][1] - 1) * 100
                rets.append(ret)
                results[code]['trades'].append(dict(date=t, code=r['sym'][2:], name=r['name'],
                    pct=round(r['pct'], 2), ind=r['ind'], ret=round(ret, 2), tag=tag))
            if not rets: continue
            results[code]['days'].append(dict(date=t, score=scores[t], nd=nd,
                mkt_avg=round(sc['mkt_avg'], 2), n=len(rets),
                avg=round(sum(rets) / len(rets), 2),
                win=round(sum(1 for x in rets if x > 0) / len(rets), 2),
                bench=round(bench, 2)))

    summary = []
    for code, sname, sdesc in all_strats:
        R = results[code]
        all_rets = [tr['ret'] for tr in R['trades']]
        n = len(all_rets)
        if n == 0:
            summary.append(dict(code=code, name=sname, desc=sdesc, ndays=0, n=0)); continue
        srt = sorted(all_rets, reverse=True)
        mean = sum(all_rets) / n
        med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
        win = sum(1 for x in all_rets if x > 0) / n
        day_avg = sum(d['avg'] for d in R['days']) / len(R['days'])
        bench_avg = sum(d['bench'] for d in R['days']) / len(R['days'])
        comp = 1.0
        for d in R['days']: comp *= (1 + d['avg'] / 100)
        t26 = [tr for tr in R['trades'] if tr['date'] >= '2026-01-05']
        m26 = sum(tr['ret'] for tr in t26) / len(t26) if t26 else None
        w26 = (sum(1 for tr in t26 if tr['ret'] > 0) / len(t26)) if t26 else None
        drop3 = sum(srt[3:]) / (n - 3) if n > 3 else None
        worst_day = min(R['days'], key=lambda d: d['avg'])
        best = max(R['trades'], key=lambda x: x['ret'])
        worst = min(R['trades'], key=lambda x: x['ret'])
        summary.append(dict(code=code, name=sname, desc=sdesc, ndays=len(R['days']), n=n,
                            mean=round(mean, 2), med=round(med, 2), win=round(win, 3),
                            day_avg=round(day_avg, 2), bench_avg=round(bench_avg, 2),
                            excess=round(day_avg - bench_avg, 2),
                            comp=round((comp - 1) * 100, 1),
                            n26=len(t26), mean26=(round(m26, 2) if m26 is not None else None),
                            win26=(round(w26, 3) if w26 is not None else None),
                            drop3=(round(drop3, 2) if drop3 is not None else None),
                            worst_day='%s %+.2f%%' % (worst_day['date'][5:], worst_day['avg']),
                            best='%s %s %+.1f%%' % (best['name'], best['date'][5:], best['ret']),
                            worst='%s %s %+.1f%%' % (worst['name'], worst['date'][5:], worst['ret']),
                            empty=len(triggers) - len(R['days']), skipped=R['skipped']))

    print('\n========== S11 最终综合 TOP10 (冰点日收盘买 → 次日收盘卖) ==========')
    print('窗口: %s -> %s | 冰点触发 %d 天\n' % (dates[0], dates[-1], len(triggers)))
    hdr = '%-5s %-22s %-5s %-5s %-8s %-6s %-9s %-9s %-9s %-8s %-8s'
    print(hdr % ('策略', '名称', '天数', '笔数', '单笔均值', '胜率', '日均超额', '剔最佳3笔', '最差单日', '26后均值', '复利'))
    for s in sorted(summary, key=lambda x: -(x.get('excess') or -99)):
        if s['n'] == 0:
            print('%-5s %-22s 无交易' % (s['code'], s['name'])); continue
        print(hdr % (s['code'], s['name'], s['ndays'], s['n'], '%+.2f%%' % s['mean'],
                     '%.0f%%' % (s['win'] * 100), '%+.2f%%' % s['excess'],
                     ('%+.2f%%' % s['drop3']) if s['drop3'] is not None else '--',
                     s['worst_day'],
                     ('%+.2f%%' % s['mean26']) if s['mean26'] is not None else '--',
                     '%+.1f%%' % s['comp']))
        print('      最佳: %s | 最差: %s' % (s['best'], s['worst']))

    out = dict(window=[dates[0], dates[-1]], ndays_trigger=len(triggers), bd_th=BD_TH,
               strats=[dict(code=c, name=n, desc=d) for c, n, d in all_strats],
               summary=summary,
               days={c: results[c]['days'] for c, _, _ in all_strats},
               trades={c: results[c]['trades'] for c, _, _ in all_strats})
    with open('/Users/michael/Documents/golden-system/td9-screener/backtest_s11_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s11_data.json / backtest_s11.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    t11 = json.dumps(out['trades']['S11'], ensure_ascii=False)
    t11b = json.dumps(out['trades']['S11b'], ensure_ascii=False)
    t11c = json.dumps(out['trades']['S11c'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S11 · 最终综合 TOP10 策略</title>
<script src="./echarts.min.js"></script>
<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f1f3f6;margin:0;padding:18px;color:#212529}
.wrap{max-width:1240px;margin:0 auto}
h1{font-size:19px;margin:2px 0 4px}
.sub{font-size:12px;color:#868e96;margin-bottom:14px;line-height:1.8}
.panel{background:#fff;border:1px solid #e9ecef;border-radius:8px;padding:12px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{padding:6px 8px;text-align:left;color:#495057;border-bottom:2px solid #dee2e6;background:#f8f9fa}
td{padding:5px 8px;border-bottom:1px solid #f0f2f7}
.up{color:#e03131;font-weight:700}.dn{color:#0ca678;font-weight:700}
.best{background:#fff5f5}
.note{font-size:11px;color:#868e96;line-height:1.8}
.tag{display:inline-block;border-radius:4px;padding:0 6px;font-size:10.5px;margin-right:4px}
.tblbox{max-height:400px;overflow:auto}
h2{font-size:14px;margin:0 0 6px}
.b1{background:#fff0e6;color:#d9480f}.b2{background:#e7f5ff;color:#1971c2}.b3{background:#f3f0ff;color:#6741d9}
</style></head><body><div class="wrap">
<h1>🧊 S11 · 最终综合策略 · 三桶 TOP10（S1~S10c 全部回测结论合成）</h1>
<div class="sub">共同口径: 情绪温度 &lt; 30 触发日 <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（触发 __ND__ 天）· 基准: 全市场等权次日涨幅<br>
<b>结构</b>: <span class="tag b1">弹性桶 5只</span>冰点日触及涨停×低位首启动(5日≤20%) ← S5 结论 ｜ <span class="tag b2">趋势桶 3只</span>20日3~50%×MA20上且上行×相对强度打分 ← S1 结论 ｜ <span class="tag b3">回调桶 2只</span>近5日调整[-10,0)×近20日≥10%×贴MA20 ← S9d/S10c 结论 ｜ 弹性不足依次回填<br>
<b>统一风控层</b>（趋势/回调桶全量适用）: 剔妖(5日&gt;20%或20日&gt;50%) × 板块5日≥0(未走弱, S6教训) × 剔深跌(当日&lt;-3%) × 剔次新(&lt;60根K) × 非ST × 每板块≤2<br>
<b>配额变体</b>: S11=5/3/2 · S11b=7/3/0(即S7c+风控层) · S11c=6/2/2<br>
__SDESC__</div>
<div class="panel"><h2>策略总览（按日均超额降序，S11 系加粗背景）</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>逐触发日 TOP10 次日均值（%）· 三档配额 + 主要参照</h2><div id="chart" style="width:100%;height:430px"></div></div>
<div class="panel"><h2>S11 逐日持仓结构（弹性/趋势/回调 计数）</h2><div class="tblbox"><table id="mix"></table></div></div>
<div class="panel"><h2>S11 逐笔明细</h2><div class="tblbox"><table id="t11"></table></div></div>
<div class="panel"><h2>S11b 逐笔明细</h2><div class="tblbox"><table id="t11b"></table></div></div>
<div class="panel note">口径说明: ① 各策略共用同一触发日与基准，差异仅在选股画像; ② 年K仅收盘价，无量能/盘中字段; ③ 强势池数据 2026-01-05 起; ④ 复利为逐触发日示意累乘; ⑤ 样本仅 26 个触发日，配额参数存在后视镜风险; ⑥ 仅为策略研究，不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, STLIST = __ST__, T11 = __T11__, T11B = __T11B__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
var h = '<tr><th>策略</th><th>画像</th><th>天数</th><th>笔数</th><th>单笔均值</th><th>胜率</th><th>日均超额</th><th>剔最佳3笔</th><th>最差单日</th><th>复利(示意)</th><th>26后均值</th><th>26后胜率</th><th>最佳/最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  var hl = (c==='S11'||c==='S11b'||c==='S11c');
  if(!s.n){ h += '<tr><td><b>'+c+'</b> '+s.name+'</td><td colspan="12" style="color:#868e96">无交易</td></tr>'; return; }
  h += '<tr'+(hl?' class="best"':'')+'><td><b>'+c+'</b> '+s.name+'</td><td style="font-size:11px;color:#868e96">'+s.desc+'</td>'
    + '<td>'+s.ndays+'</td><td>'+s.n+'</td>'
    + '<td class="'+(s.mean>=0?'up':'dn')+'">'+(s.mean>0?'+':'')+s.mean.toFixed(2)+'%</td>'
    + '<td>'+Math.round(s.win*100)+'%</td>'
    + '<td class="'+(s.excess>=0?'up':'dn')+'">'+(s.excess>0?'+':'')+s.excess.toFixed(2)+'%</td>'
    + '<td>'+(s.drop3!=null?((s.drop3>0?'+':'')+s.drop3.toFixed(2)+'%'):'--')+'</td>'
    + '<td class="'+(s.worst_day.indexOf('+')>=0?'up':'dn')+'">'+s.worst_day+'</td>'
    + '<td>'+(s.comp>0?'+':'')+s.comp.toFixed(1)+'%</td>'
    + '<td>'+(s.mean26!=null?((s.mean26>0?'+':'')+s.mean26.toFixed(2)+'%'):'--')+'</td>'
    + '<td>'+(s.win26!=null?Math.round(s.win26*100)+'%':'--')+'</td>'
    + '<td style="font-size:11px"><span class="up">'+s.best+'</span> / <span class="dn">'+s.worst+'</span></td></tr>';
});
document.getElementById('sumtbl').innerHTML = h;
var cats = [];
var allDays = {};
STLIST.forEach(function(s){ (DAYS[s.code]||[]).forEach(function(d){ allDays[d.date] = d.score; }); });
cats = Object.keys(allDays).sort();
var focus = ['S11','S11b','S11c','S5','S1'].filter(function(c){ return order.indexOf(c)>=0; });
var series = focus.map(function(c){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  var col = c==='S11' ? '#e8590c' : c==='S11b' ? '#d9480f' : c==='S11c' ? '#f76707' : c==='S5' ? '#9c36b5' : '#495057';
  return {name: c + ' ' + byCode[c].name, type: c==='S1'?'line':'bar', data: cats.map(function(dt){ return m[dt]!=null?m[dt]:null; }),
          barMaxWidth: 11, itemStyle:{color:col}, lineStyle:{width:2,color:col}};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d=(DAYS['S11']||[]).find(function(x){return x.date===dt;}) || (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d?d.bench:null; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
var ch = echarts.init(document.getElementById('chart'));
ch.setOption({tooltip:{trigger:'axis'},legend:{top:0,type:'scroll',textStyle:{fontSize:11}},
  grid:{left:44,right:20,top:40,bottom:56},
  xAxis:{type:'category',data:cats.map(function(d){return d.slice(2);}),axisLabel:{rotate:45,fontSize:10,color:'#868e96'}},
  yAxis:{type:'value',axisLabel:{formatter:'{value}%'},splitLine:{lineStyle:{color:'#f0f2f7'}}},
  series: series});
// 持仓结构
var mix = '<tr><th>触发日</th><th>温度</th><th>S11均值</th><th>弹性·涨停</th><th>趋势·多头</th><th>回调·贴线</th></tr>';
var byDate = {};
T11.forEach(function(x){ (byDate[x.date]=byDate[x.date]||[]).push(x); });
Object.keys(byDate).sort().reverse().forEach(function(dt){
  var arr = byDate[dt];
  var c1=0,c2=0,c3=0;
  arr.forEach(function(x){ if(x.tag==='弹性·涨停')c1++; else if(x.tag==='趋势·多头')c2++; else c3++; });
  var d7 = (DAYS['S11']||[]).find(function(x){ return x.date===dt; });
  mix += '<tr><td>'+dt+'</td><td><b>'+(d7?d7.score:'—')+'</b></td>'
    + '<td class="'+(d7&&d7.avg>=0?'up':'dn')+'">'+(d7?(d7.avg>0?'+':'')+d7.avg.toFixed(2)+'%':'—')+'</td>'
    + '<td>'+(c1||'—')+'</td><td>'+(c2||'—')+'</td><td>'+(c3||'—')+'</td></tr>';
});
document.getElementById('mix').innerHTML = mix;
function tradeTable(el, T){
  var t = '<tr><th>触发日</th><th>代码</th><th>名称</th><th>板块</th><th>当日涨幅</th><th>次日收益</th><th>仓位</th></tr>';
  var bd = {};
  T.forEach(function(x){ (bd[x.date]=bd[x.date]||[]).push(x); });
  Object.keys(bd).sort().reverse().forEach(function(dt){
    bd[dt].forEach(function(x, i){
      var cls = x.tag==='弹性·涨停'?'b1':x.tag==='趋势·多头'?'b2':'b3';
      t += '<tr'+(i===0?' style="border-top:2px solid #dee2e6"':'')+'><td>'+x.date.slice(2)+'</td><td>'+x.code+'</td><td>'+x.name+'</td><td style="font-size:11px">'+x.ind+'</td>'
        + '<td class="'+(x.pct>=0?'up':'dn')+'">'+(x.pct>0?'+':'')+x.pct.toFixed(2)+'%</td>'
        + '<td class="'+(x.ret>=0?'up':'dn')+'">'+(x.ret>0?'+':'')+x.ret.toFixed(2)+'%</td>'
        + '<td><span class="tag '+cls+'">'+x.tag+'</span></td></tr>';
    });
  });
  document.getElementById(el).innerHTML = t;
}
tradeTable('t11', T11); tradeTable('t11b', T11B);
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'] if c in ('S1', 'S4', 'S5'))
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days)
            .replace('__ST__', strats).replace('__T11__', t11).replace('__T11B__', t11b))
    p = '/Users/michael/Documents/golden-system/td9-screener/backtest_s11.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
