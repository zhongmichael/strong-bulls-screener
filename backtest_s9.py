# -*- coding: utf-8 -*-
"""
backtest_s9.py — S9 策略: 近一月最强 × 冰点周回调 × 未破20日线
==============================================================
用户命题: 选近一个月最强的股, 冰点日近一周在调整, 但没跌破20日线, 博修复。
与 S8 的差异: "强"的锚从年度涨幅(过去一年)换成近20日涨幅(近一月) — S8 结论:
  冰点修复日要看"近期强度", 年榜强股=拥挤动量, 有高位补跌尾部。

S9  口径:
  · 榜单: 触发当日近20日涨幅(一个月)全市场 TOP50
  · 近一周在调整: 近5日涨幅 < 0
  · 未破20日线: 收盘 >= MA20
  · 风控: 当日跌幅 >= -5%, 非ST, 每板块 <= 2
  · 评分 = 20日涨幅×0.1 + 贴线(MA20乖离<=5%)+8 + 当日相对大盘×1.5
S9b: S9 + MA20 仍在上行(趋势保护)
S9c: 榜单放宽 TOP100(宽度敏感性)
交易: 触发日收盘等权买 TOP10 → 次日收盘卖。
"""
import json, sys

sys.path.insert(0, '/Users/michael/Documents/golden-system/td9-screener')
from backtest_bingdian import build, BD_TH  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS  # noqa


def pick_s9(bt, sc, topn=50, ma20_rising=False, min_ret5=None):
    rows = [r for r in sc['rows'].values() if 'ST' not in r['name'] and 'st' not in r['name']]
    ranked = sorted([r for r in rows if r['ret20'] is not None], key=lambda r: -r['ret20'])
    tops = {r['sym']: r['ret20'] for r in ranked[:topn]}
    cand = []
    for r in rows:
        m20 = tops.get(r['sym'])
        if m20 is None: continue                    # 必须近一月最强前 N
        if r['ret5'] is None or r['ret5'] >= 0: continue   # 近一周在调整
        if min_ret5 is not None and r['ret5'] < min_ret5: continue  # 调整不深于阈值
        if r['ma20'] is None: continue
        if r['c'] < r['ma20']: continue             # 未破20日线
        if ma20_rising and (r['ma20p'] is None or r['ma20'] <= r['ma20p']): continue
        if r['pct'] < -5: continue                  # 当日不接深跌刀
        score = m20 * 0.1 + r['rel'] * 1.5
        dev20 = (r['c'] / r['ma20'] - 1) * 100
        if dev20 <= 5: score += 8                   # 回调正贴在20日线上
        cand.append((score, r, '月%+.0f%% 5日%+.1f%%' % (m20, r['ret5'])))
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


S9_STRATS = [
    ('S9', '近月TOP50×5日调整×MA20上', '近20日涨幅TOP50 × 近5日<0 × 收盘≥MA20 × 当日≥-5%'),
    ('S9b', '近月TOP50×调整×MA20上行', 'S9 + MA20仍上行(趋势保护)'),
    ('S9c', '近月TOP100×5日调整×MA20上', '榜单放宽TOP100, 宽度敏感性'),
    ('S9d', '近月TOP100×调整≥-10%×MA20上', 'S9c + 近5日调整不深于-10%(剔深调补跌股)'),
]


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('冰点触发日: %d 天' % len(triggers))

    all_strats = [(c, n, d) for c, n, d in STRATS] + S9_STRATS
    results = {c: dict(days=[], trades=[], skipped=0) for c, _, _ in all_strats}

    for t in triggers:
        sc = bt.scan(t)
        if not sc: continue
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
        picks['S9'] = pick_s9(bt, sc, 50, False)
        picks['S9b'] = pick_s9(bt, sc, 50, True)
        picks['S9c'] = pick_s9(bt, sc, 100, False)
        picks['S9d'] = pick_s9(bt, sc, 100, False, min_ret5=-10)
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

    print('\n========== S9 近月最强回调贴线 (冰点日收盘买TOP10 → 次日收盘卖) ==========')
    print('窗口: %s -> %s | 冰点触发 %d 天\n' % (dates[0], dates[-1], len(triggers)))
    hdr = '%-5s %-22s %-5s %-5s %-8s %-6s %-9s %-9s %-9s %-8s'
    print(hdr % ('策略', '名称', '天数', '笔数', '单笔均值', '胜率', '日均超额', '剔最佳3笔', '最差单日', '26后均值'))
    for s in sorted(summary, key=lambda x: -(x.get('excess') or -99)):
        if s['n'] == 0:
            print('%-5s %-22s 无交易' % (s['code'], s['name'])); continue
        print(hdr % (s['code'], s['name'], s['ndays'], s['n'], '%+.2f%%' % s['mean'],
                     '%.0f%%' % (s['win'] * 100), '%+.2f%%' % s['excess'],
                     ('%+.2f%%' % s['drop3']) if s['drop3'] is not None else '--',
                     s['worst_day'],
                     ('%+.2f%%' % s['mean26']) if s['mean26'] is not None else '--'))
        print('      最佳: %s | 最差: %s' % (s['best'], s['worst']))

    out = dict(window=[dates[0], dates[-1]], ndays_trigger=len(triggers), bd_th=BD_TH,
               strats=[dict(code=c, name=n, desc=d) for c, n, d in all_strats],
               summary=summary,
               days={c: results[c]['days'] for c, _, _ in all_strats},
               trades={c: results[c]['trades'] for c, _, _ in all_strats})
    with open('/Users/michael/Documents/golden-system/td9-screener/backtest_s9_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s9_data.json / backtest_s9.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    t9 = json.dumps(out['trades']['S9'], ensure_ascii=False)
    t9b = json.dumps(out['trades']['S9b'], ensure_ascii=False)
    t9c = json.dumps(out['trades']['S9c'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S9 策略 · 近一月最强 × 冰点周回调 × 未破20日线</title>
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
.tag{display:inline-block;background:#edf2ff;color:#1c7ed6;border-radius:4px;padding:0 6px;font-size:10.5px;margin-right:4px}
.tblbox{max-height:380px;overflow:auto}
h2{font-size:14px;margin:0 0 6px}
</style></head><body><div class="wrap">
<h1>🧊 S9 命题验证 · 冰点日买「近一月最强 + 近一周调整 + 未破20日线」</h1>
<div class="sub">共同口径: 情绪温度 &lt; 30 触发日 <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（触发 __ND__ 天）· 基准: 全市场等权次日涨幅<br>
<b>S9 画像</b>: 当日近20日涨幅（一个月）全市场 <b>TOP50</b> × 近5日涨幅&lt;0（近一周在调整）× 收盘 ≥ MA20（未跌破）× 当日跌幅≥-5% × 非ST × 每板块≤2 · 贴线加分：MA20 乖离≤5% +8<br>
<b>S9b</b>: S9 + MA20 仍在上行（趋势保护）<br>
<b>S9c</b>: 榜单放宽 TOP100（宽度敏感性）<br>
对比锚点: S8 用「年度涨幅榜前50」+0.41%超额、尾部-6.5% → 本策略验证把"强"的锚换成近一月是否更好<br>
__SDESC__</div>
<div class="panel"><h2>策略总览（按日均超额降序，S9 系加粗背景）</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>逐触发日 TOP10 次日均值（%）</h2><div id="chart" style="width:100%;height:420px"></div></div>
<div class="panel"><h2>S9 逐笔明细</h2><div class="tblbox"><table id="t9"></table></div></div>
<div class="panel"><h2>S9b 逐笔明细</h2><div class="tblbox"><table id="t9b"></table></div></div>
<div class="panel"><h2>S9c 逐笔明细</h2><div class="tblbox"><table id="t9c"></table></div></div>
<div class="panel note">口径说明: ① 各策略共用同一触发日与基准，差异仅在选股画像; ② 近20日涨幅=收盘/20个交易日前收盘-1; ③ 年K仅收盘价，无量能字段; ④ 强势池数据2026-01-05起; ⑤ 复利为逐触发日示意累乘; ⑥ 仅为策略研究，不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, STLIST = __ST__, T9 = __T9__, T9B = __T9B__, T9C = __T9C__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
var h = '<tr><th>策略</th><th>画像</th><th>天数</th><th>空仓</th><th>笔数</th><th>单笔均值</th><th>胜率</th><th>日均超额</th><th>剔最佳3笔</th><th>最差单日</th><th>复利(示意)</th><th>26后均值</th><th>最佳/最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  var hl = (c==='S9'||c==='S9b'||c==='S9c');
  if(!s.n){ h += '<tr><td><b>'+c+'</b> '+s.name+'</td><td colspan="12" style="color:#868e96">无交易</td></tr>'; return; }
  h += '<tr'+(hl?' class="best"':'')+'><td><b>'+c+'</b> '+s.name+'</td><td style="font-size:11px;color:#868e96">'+s.desc+'</td>'
    + '<td>'+s.ndays+'</td><td>'+(s.empty!=null?s.empty:'—')+'</td><td>'+s.n+'</td>'
    + '<td class="'+(s.mean>=0?'up':'dn')+'">'+(s.mean>0?'+':'')+s.mean.toFixed(2)+'%</td>'
    + '<td>'+Math.round(s.win*100)+'%</td>'
    + '<td class="'+(s.excess>=0?'up':'dn')+'">'+(s.excess>0?'+':'')+s.excess.toFixed(2)+'%</td>'
    + '<td>'+(s.drop3!=null?((s.drop3>0?'+':'')+s.drop3.toFixed(2)+'%'):'--')+'</td>'
    + '<td class="'+(s.worst_day.indexOf('+')>=0?'up':'dn')+'">'+s.worst_day+'</td>'
    + '<td>'+(s.comp>0?'+':'')+s.comp.toFixed(1)+'%</td>'
    + '<td>'+(s.mean26!=null?((s.mean26>0?'+':'')+s.mean26.toFixed(2)+'%'):'--')+'</td>'
    + '<td style="font-size:11px"><span class="up">'+s.best+'</span> / <span class="dn">'+s.worst+'</span></td></tr>';
});
document.getElementById('sumtbl').innerHTML = h;
var cats = [];
var allDays = {};
STLIST.forEach(function(s){ (DAYS[s.code]||[]).forEach(function(d){ allDays[d.date] = d.score; }); });
cats = Object.keys(allDays).sort();
var focus = ['S9','S9b','S9c','S5','S1'].filter(function(c){ return order.indexOf(c)>=0; });
var series = focus.map(function(c){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  var col = c==='S9' ? '#e8590c' : c==='S9b' ? '#d9480f' : c==='S9c' ? '#f76707' : c==='S5' ? '#9c36b5' : '#495057';
  return {name: c + ' ' + byCode[c].name, type: c==='S1'?'line':'bar', data: cats.map(function(dt){ return m[dt]!=null?m[dt]:null; }),
          barMaxWidth: 10, itemStyle:{color:col}, lineStyle:{width:2,color:col}};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d=(DAYS['S9']||[]).find(function(x){return x.date===dt;}) || (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d?d.bench:null; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
var ch = echarts.init(document.getElementById('chart'));
ch.setOption({tooltip:{trigger:'axis'},legend:{top:0,type:'scroll',textStyle:{fontSize:11}},
  grid:{left:44,right:20,top:40,bottom:56},
  xAxis:{type:'category',data:cats.map(function(d){return d.slice(2);}),axisLabel:{rotate:45,fontSize:10,color:'#868e96'}},
  yAxis:{type:'value',axisLabel:{formatter:'{value}%'},splitLine:{lineStyle:{color:'#f0f2f7'}}},
  series: series});
function tradeTable(el, T){
  var t = '<tr><th>触发日</th><th>代码</th><th>名称</th><th>板块</th><th>当日涨幅</th><th>次日收益</th><th>备注</th></tr>';
  var byDate = {};
  T.forEach(function(x){ (byDate[x.date]=byDate[x.date]||[]).push(x); });
  Object.keys(byDate).sort().reverse().forEach(function(dt){
    byDate[dt].forEach(function(x, i){
      t += '<tr'+(i===0?' style="border-top:2px solid #dee2e6"':'')+'><td>'+x.date.slice(2)+'</td><td>'+x.code+'</td><td>'+x.name+'</td><td style="font-size:11px">'+x.ind+'</td>'
        + '<td class="'+(x.pct>=0?'up':'dn')+'">'+(x.pct>0?'+':'')+x.pct.toFixed(2)+'%</td>'
        + '<td class="'+(x.ret>=0?'up':'dn')+'">'+(x.ret>0?'+':'')+x.ret.toFixed(2)+'%</td>'
        + '<td style="font-size:11px;color:#868e96">'+x.tag+'</td></tr>';
    });
  });
  document.getElementById(el).innerHTML = t;
}
tradeTable('t9', T9); tradeTable('t9b', T9B); tradeTable('t9c', T9C);
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'] if c in ('S1', 'S5'))
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days)
            .replace('__ST__', strats).replace('__T9__', t9).replace('__T9B__', t9b).replace('__T9C__', t9c))
    p = '/Users/michael/Documents/golden-system/td9-screener/backtest_s9.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
