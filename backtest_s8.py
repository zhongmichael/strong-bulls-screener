# -*- coding: utf-8 -*-
"""
backtest_s8.py — S8 策略: 年度涨幅榜前50 × 近期调整 × 站稳重要均线
================================================================
用户命题: 冰点日选股必须是当日年度涨幅榜前 50, 近期在调整,
          还在重要均线位置没有跌破, 博修复。

S8  口径:
  · 年度涨幅 = 年初(上一自然年末收盘)至今涨幅, 与线上涨幅榜同口径
    (2025 年内触发日因 K 线数据 2025-06 起, 基准退化为首个可用收盘, 仅影响早期少量触发日)
  · 榜单: 触发当日全市场 YTD TOP50
  · 近期在调整: 近5日涨幅 < 0
  · 重要均线未跌破: 收盘 >= MA20 且 >= MA60 (20日线+半年线双不破)
  · 风控: 当日跌幅不深于 -5%, 非ST
  · 评分 = YTD×0.1 + 贴线加分(距MA20/30/60最近者≤5%: +10) + 当日相对大盘×1.5, 每板块≤2
S8b: "调整"改用 10日回撤(收盘/近10日最高收盘-1) 在 -20%~-5%, 更明确的回调
S8c: 榜单放宽为 TOP100, 看榜单宽度敏感性
交易: 触发日收盘等权买 TOP10 → 次日收盘卖。
"""
import json, sys

import os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from backtest_bingdian import build, BD_TH  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS  # noqa


def ytd_top(bt, target, topn):
    """触发当日全市场 YTD 涨幅 TOP N → {sym: ytd_pct}"""
    year = target[:4]
    base_need = '%s-01-01' % year
    res = []
    for sym, bars in bt.yk.items():
        base = None
        for b in bars:
            if b[0] >= base_need: break
            base = b[1]
        if base is None or base <= 0:
            base = bars[0][1] if bars and bars[0][1] > 0 else None   # 数据起点回退(仅2025年内)
        if base is None or base <= 0: continue
        ix = bt.idx[sym].get(target)
        if ix is None: continue
        res.append((sym, (bt.yk[sym][ix][1] / base - 1) * 100))
    res.sort(key=lambda x: -x[1])
    return {sym: y for sym, y in res[:topn]}


def pick_s8(bt, sc, target, mode, topn=50, min_pct=-5):
    rows = [r for r in sc['rows'].values() if 'ST' not in r['name'] and 'st' not in r['name']]
    tops = ytd_top(bt, target, topn)
    cand = []
    for r in rows:
        y = tops.get(r['sym'])
        if y is None: continue                       # 必须在年度涨幅榜前 N
        if r['pct'] < min_pct: continue              # 当日不接深跌刀
        if r['ma20'] is None or r['ma60'] is None: continue
        if not (r['c'] >= r['ma20'] and r['c'] >= r['ma60']): continue   # 双均线未破
        if mode == 'ret5':
            if r['ret5'] is None or r['ret5'] >= 0: continue          # 近5日在调整
            adj_tag = '5日%+.1f%%' % r['ret5']
        else:
            bars = bt.yk[r['sym']]
            hi10 = max(b[1] for b in bars[max(0, r['j']-10):r['j']])
            dd = (r['c'] / hi10 - 1) * 100                            # 10日回撤
            if not (-20 <= dd <= -5): continue
            adj_tag = '回撤%.1f%%' % dd
        score = y * 0.1 + r['rel'] * 1.5
        dev20 = (r['c'] / r['ma20'] - 1) * 100
        dev30 = (r['c'] / r['ma30'] - 1) * 100 if r['ma30'] else 99
        dev60 = (r['c'] / r['ma60'] - 1) * 100
        devmin = min(abs(dev20), abs(dev30), abs(dev60))
        if devmin <= 5:
            score += 10                                               # 正贴在重要均线上
        cand.append((score, r, 'YTD%+.0f%% %s' % (y, adj_tag)))
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


S8_STRATS = [
    ('S8', '年榜TOP50×5日调整×双均线', 'YTD TOP50 × 近5日<0 × 收盘≥MA20且≥MA60 × 当日≥-5%'),
    ('S8b', '年榜TOP50×10日回撤×双均线', '调整改用10日回撤-20%~-5%(从高点回调), 其余同S8'),
    ('S8c', '年榜TOP100×5日调整×双均线', '榜单放宽到TOP100, 看宽度敏感性, 其余同S8'),
    ('S8d', '年榜TOP50×5日调整×当日浅调', 'S8 + 当日跌幅≥-2%(结合此前"当日调整幅度不特别大"偏好)'),
]


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('冰点触发日: %d 天' % len(triggers))

    all_strats = [(c, n, d) for c, n, d in STRATS] + S8_STRATS
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
        picks['S8'] = pick_s8(bt, sc, t, 'ret5', 50)
        picks['S8b'] = pick_s8(bt, sc, t, 'dd10', 50)
        picks['S8c'] = pick_s8(bt, sc, t, 'ret5', 100)
        picks['S8d'] = pick_s8(bt, sc, t, 'ret5', 50, min_pct=-2)
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

    print('\n========== S8 年度涨幅榜前50 回调贴线 (冰点日收盘买TOP10 → 次日收盘卖) ==========')
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
    with open(BASE + '/backtest_s8_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s8_data.json / backtest_s8.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    t8 = json.dumps(out['trades']['S8'], ensure_ascii=False)
    t8b = json.dumps(out['trades']['S8b'], ensure_ascii=False)
    t8c = json.dumps(out['trades']['S8c'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S8 策略 · 年度涨幅榜前50 回调贴线</title>
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
<h1>🧊 S8 命题验证 · 冰点日买「年度涨幅榜前50 + 近期调整 + 未破重要均线」</h1>
<div class="sub">共同口径: 情绪温度 &lt; 30 触发日 <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（触发 __ND__ 天）· 基准: 全市场等权次日涨幅<br>
<b>S8 画像</b>: 当日全市场年度涨幅榜 TOP50（年初至今，与线上涨幅榜同口径）× 近5日调整（5日涨幅&lt;0）× 收盘≥MA20 且 ≥MA60（双均线未破）× 当日跌幅≥-5% × 非ST × 每板块≤2 · 贴线加分：收盘距 MA20/30/60 最近者 ≤5%<br>
<b>S8b</b>: 「调整」改用 10日回撤（收盘/近10日最高收盘-1）在 -20%~-5%，更明确的回调定义<br>
<b>S8c</b>: 榜单放宽为 TOP100，看榜单宽度敏感性<br>
__SDESC__</div>
<div class="panel"><h2>策略总览（按日均超额降序，S8 系加粗背景）</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>逐触发日 TOP10 次日均值（%）</h2><div id="chart" style="width:100%;height:420px"></div></div>
<div class="panel"><h2>S8 逐笔明细</h2><div class="tblbox"><table id="t8"></table></div></div>
<div class="panel"><h2>S8b 逐笔明细</h2><div class="tblbox"><table id="t8b"></table></div></div>
<div class="panel"><h2>S8c 逐笔明细</h2><div class="tblbox"><table id="t8c"></table></div></div>
<div class="panel note">口径说明: ① 各策略共用同一触发日与基准，差异仅在选股画像; ② 年度涨幅基准=上一自然年末收盘，2025年内触发日因K线数据2025-06起，基准退化为数据起点(仅影响早期触发日); ③ 次新股(年内无年初前收盘)天然不入榜; ④ 年K仅收盘价，无量能字段; ⑤ 强势池数据2026-01-05起; ⑥ 仅为策略研究，不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, STLIST = __ST__, T8 = __T8__, T8B = __T8B__, T8C = __T8C__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
var h = '<tr><th>策略</th><th>画像</th><th>天数</th><th>空仓</th><th>笔数</th><th>单笔均值</th><th>胜率</th><th>日均超额</th><th>剔最佳3笔</th><th>最差单日</th><th>复利(示意)</th><th>26后均值</th><th>最佳/最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  var hl = (c==='S8'||c==='S8b'||c==='S8c');
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
var focus = ['S8','S8b','S8c','S5','S1'].filter(function(c){ return order.indexOf(c)>=0; });
var series = focus.map(function(c){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  var col = c==='S8' ? '#e8590c' : c==='S8b' ? '#d9480f' : c==='S8c' ? '#f76707' : c==='S5' ? '#9c36b5' : '#495057';
  return {name: c + ' ' + byCode[c].name, type: c==='S1'?'line':'bar', data: cats.map(function(dt){ return m[dt]!=null?m[dt]:null; }),
          barMaxWidth: 10, itemStyle:{color:col}, lineStyle:{width:2,color:col}};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d=(DAYS['S8']||[]).find(function(x){return x.date===dt;}) || (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d?d.bench:null; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
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
tradeTable('t8', T8); tradeTable('t8b', T8B); tradeTable('t8c', T8C);
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'] if c in ('S1', 'S5'))
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days)
            .replace('__ST__', strats).replace('__T8__', t8).replace('__T8B__', t8b).replace('__T8C__', t8c))
    p = BASE + '/backtest_s8.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
