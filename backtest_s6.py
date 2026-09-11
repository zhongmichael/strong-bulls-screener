# -*- coding: utf-8 -*-
"""
backtest_s6.py — 用户命题策略 S6 回测: 强势板块回调贴线股
==========================================================
命题: 买「近期强势的板块, 最近一周左右在调整, 个股没跌破20日线,
      当日调整幅度不特别大」的票, 博次日修复。

S6 口径(与 S1~S5 同触发/同交易规则):
  板块层: 板块20日均值涨幅排名前1/3(成员>=5) = 近期强势;
          板块5日均值涨幅 < 0 = 近一周在调整。
  个股层: 属于该板块 × 收盘 >= MA20(未跌破) × MA20仍在上行 × 当日 -3%<=pct<=2%(浅调) × 非ST。
  评分  = 板块20日涨幅x0.5 + 当日相对大盘超额x1.5 + 贴近MA20(乖离<=6%)+6 + 站上MA60+4 + 强势池+8
  S6b: S6 基础上再加「个股自身近5日也在调整」(ret5<0), 看板块/个股共振回调是否更好。
交易: 触发日收盘等权买 TOP10 → 次日收盘卖。
"""
import json, sys

import os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from backtest_bingdian import build, BD_TH  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS  # noqa


def pick_s6(bt, sc, require_stock_ret5_neg, require_adj=True):
    rows = [r for r in sc['rows'].values() if 'ST' not in r['name'] and 'st' not in r['name']]
    # ---- 板块聚合: 5日/20日均值涨幅 ----
    sec5, sec20 = {}, {}
    for r in rows:
        if r['ret20'] is None: continue
        a = sec20.setdefault(r['ind'], [0.0, 0]); a[0] += r['ret20']; a[1] += 1
        if r['ret5'] is not None:
            b = sec5.setdefault(r['ind'], [0.0, 0]); b[0] += r['ret5']; b[1] += 1
    elig = [k for k, v in sec20.items() if v[1] >= 5]
    if not elig: return []
    elig.sort(key=lambda k: -sec20[k][0] / sec20[k][1])
    top_n = max(3, len(elig) // 3)
    strong_secs = set(elig[:top_n])          # 近期强势板块(20日动量前1/3)
    adj_secs = set()
    for k in strong_secs:
        b = sec5.get(k)
        if b and b[1] >= 3:
            v = b[0] / b[1]
            if (v < 0) if require_adj else (v >= 0):
                adj_secs.add(k)              # 近一周在调整(S6/S6b) / 未调整(S6c对照)
    if not adj_secs: return []
    pool_day = None
    di = bt.day_idx[sc['target']]
    for back in range(0, 4):
        pool_day = bt.strong_pool.get(bt.dates[di - back])
        if pool_day: break
    cand = []
    for r in rows:
        if r['ind'] not in adj_secs: continue
        if r['ma20'] is None or r['ma20p'] is None: continue
        if not (r['c'] >= r['ma20'] and r['ma20'] > r['ma20p']): continue   # 未破20日线且MA20上行
        if not (-3 <= r['pct'] <= 2): continue                              # 当日浅调
        if require_stock_ret5_neg and (r['ret5'] is None or r['ret5'] >= 0): continue
        s20 = sec20[r['ind']][0] / sec20[r['ind']][1]
        score = s20 * 0.5 + r['rel'] * 1.5
        tags = []
        dev20 = (r['c'] / r['ma20'] - 1) * 100
        if dev20 <= 6: score += 6; tags.append('贴MA20')
        if r['ma60'] and r['c'] >= r['ma60']: score += 4; tags.append('MA60上')
        if pool_day and pool_day.get(r['sym']): score += 8; tags.append('池')
        cand.append((score, r, '%s 5日%+.1f%%' % (r['ind'], r['ret5'] or 0)))
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


S6_STRATS = [
    ('S6', '强势板块回调贴线股', '板块20日强前1/3×板块5日<0调整×个股MA20上且上行×当日-3~2%浅调'),
    ('S6b', '板块+个股共振回调', 'S6 + 个股自身近5日也在调整(ret5<0)'),
    ('S6c', '对照:强势板块未调整', '同S6但板块5日>=0(未调整), 隔离"调整"因子'),
]


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('冰点触发日: %d 天' % len(triggers))

    all_strats = [(c, n, d) for c, n, d in STRATS] + S6_STRATS
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
        picks['S6'] = pick_s6(bt, sc, False)
        picks['S6b'] = pick_s6(bt, sc, True)
        picks['S6c'] = pick_s6(bt, sc, False, require_adj=False)
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
        mean = sum(all_rets) / n
        srt = sorted(all_rets)
        med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
        win = sum(1 for x in all_rets if x > 0) / n
        day_avg = sum(d['avg'] for d in R['days']) / len(R['days'])
        bench_avg = sum(d['bench'] for d in R['days']) / len(R['days'])
        comp = 1.0
        for d in R['days']: comp *= (1 + d['avg'] / 100)
        t26 = [tr for tr in R['trades'] if tr['date'] >= '2026-01-05']
        m26 = sum(tr['ret'] for tr in t26) / len(t26) if t26 else None
        w26 = (sum(1 for tr in t26 if tr['ret'] > 0) / len(t26)) if t26 else None
        best = max(R['trades'], key=lambda x: x['ret'])
        worst = min(R['trades'], key=lambda x: x['ret'])
        # S6 专属诊断: 有候选的触发日占比 / 空仓日
        empty_days = len(triggers) - len(R['days'])
        summary.append(dict(code=code, name=sname, desc=sdesc, ndays=len(R['days']), n=n,
                            mean=round(mean, 2), med=round(med, 2), win=round(win, 3),
                            day_avg=round(day_avg, 2), bench_avg=round(bench_avg, 2),
                            excess=round(day_avg - bench_avg, 2),
                            comp=round((comp - 1) * 100, 1),
                            n26=len(t26), mean26=(round(m26, 2) if m26 is not None else None),
                            win26=(round(w26, 3) if w26 is not None else None),
                            best='%s %s %+.1f%% (%s)' % (best['name'], best['date'][5:], best['ret'], best['tag']),
                            worst='%s %s %+.1f%% (%s)' % (worst['name'], worst['date'][5:], worst['ret'], worst['tag']),
                            empty=empty_days, skipped=R['skipped']))

    print('\n========== S6 命题验证: 强势板块回调贴线股 (冰点日收盘买TOP10 → 次日收盘卖) ==========')
    print('窗口: %s -> %s | 冰点触发 %d 天\n' % (dates[0], dates[-1], len(triggers)))
    hdr = '%-5s %-16s %-5s %-5s %-8s %-6s %-9s %-9s %-8s %-8s'
    print(hdr % ('策略', '名称', '天数', '笔数', '单笔均值', '胜率', '日均超额', '复利(示意)', '26后均值', '26后胜率'))
    for s in sorted(summary, key=lambda x: -(x.get('excess') or -99)):
        if s['n'] == 0:
            print('%-5s %-16s 无交易' % (s['code'], s['name'])); continue
        print(hdr % (s['code'], s['name'], s['ndays'], s['n'],
                     '%+.2f%%' % s['mean'], '%.0f%%' % (s['win'] * 100),
                     '%+.2f%%' % s['excess'], '%+.1f%%' % s['comp'],
                     ('%+.2f%%' % s['mean26']) if s['mean26'] is not None else '--',
                     ('%.0f%%' % (s['win26'] * 100)) if s['win26'] is not None else '--'))
        print('      最佳: %s | 最差: %s' % (s['best'], s['worst']))

    out = dict(window=[dates[0], dates[-1]], ndays_trigger=len(triggers), bd_th=BD_TH,
               strats=[dict(code=c, name=n, desc=d) for c, n, d in all_strats],
               summary=summary,
               days={c: results[c]['days'] for c, _, _ in all_strats},
               trades={c: results[c]['trades'] for c, _, _ in all_strats})
    with open(BASE + '/backtest_s6_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s6_data.json / backtest_s6.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    trades = json.dumps(out['trades'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    s6tr = json.dumps([tr for tr in out['trades']['S6']], ensure_ascii=False)
    s6btr = json.dumps([tr for tr in out['trades']['S6b']], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S6 命题验证 · 强势板块回调贴线股</title>
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
<h1>🧊 S6 命题验证 · 买「强势板块 + 近一周调整 + 未破20日线 + 当日浅调」的票，次日容易修复吗？</h1>
<div class="sub">共同口径: 情绪温度 &lt; 30 的触发日 <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（触发 __ND__ 天）· 基准: 全市场等权次日涨幅<br>
<b>S6 画像</b>: 板块20日均值涨幅排名前1/3（近期强势）× 板块5日均值涨幅&lt;0（近一周在调整）× 个股收盘≥MA20 且 MA20 上行（未跌破支撑）× 当日涨跌幅 -3%~+2%（调整幅度不特别大）× 非ST<br>
<b>S6b</b>: S6 + 个股自身近5日也调整（板块/个股共振回调）<br>
__SDESC__</div>
<div class="panel"><h2>策略总览（按日均超额降序，S6 两行加粗背景）</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>逐触发日 TOP10 次日均值（%）· 重点看 S6 / S6b</h2><div id="chart" style="width:100%;height:400px"></div></div>
<div class="panel"><h2>S6 逐笔明细</h2><div class="tblbox"><table id="t6"></table></div></div>
<div class="panel"><h2>S6b 逐笔明细</h2><div class="tblbox"><table id="t6b"></table></div></div>
<div class="panel note">口径说明: ① 七套策略共用同一触发日与基准，差异仅在选股画像; ② 强势池数据 2026-01-05 起才有; ③ 年K仅收盘价，无量能字段; ④ S6 板块=一级板块(meta[5]||meta[3])，成员≥5 才参与排名，避免小板块噪声; ⑤ 复利为逐触发日示意累乘; ⑥ 仅为策略研究，不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, TRD = __TRD__, STLIST = __ST__, T6 = __T6__, T6B = __T6B__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
var h = '<tr><th>策略</th><th>画像</th><th>持仓天数</th><th>空仓天数</th><th>笔数</th><th>单笔均值</th><th>中位数</th><th>胜率</th><th>日均超额</th><th>复利(示意)</th><th>26后均值</th><th>26后胜率</th><th>最佳单笔</th><th>最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  var hl = (c==='S6'||c==='S6b');
  if(!s.n){ h += '<tr'+(hl?' class="best"':'')+'><td><b>'+c+'</b> '+s.name+'</td><td colspan="13" style="color:#868e96">无交易</td></tr>'; return; }
  h += '<tr'+(hl?' class="best"':'')+'><td><b>'+c+'</b> '+s.name+'</td><td style="font-size:11px;color:#868e96">'+s.desc+'</td>'
    + '<td>'+s.ndays+'</td><td>'+(s.empty!=null?s.empty:'—')+'</td><td>'+s.n+'</td>'
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
var cats = [];
var allDays = {};
STLIST.forEach(function(s){ (DAYS[s.code]||[]).forEach(function(d){ allDays[d.date] = d.score; }); });
cats = Object.keys(allDays).sort();
var focus = ['S6','S6b','S1','S5','S4'].filter(function(c){ return order.indexOf(c)>=0; });
var series = focus.map(function(c){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  var col = c==='S6' ? '#e8590c' : c==='S6b' ? '#d9480f' : c==='S5' ? '#9c36b5' : c==='S4' ? '#f59f00' : '#495057';
  return {name: c + ' ' + byCode[c].name, type: c==='S1'?'line':'bar', data: cats.map(function(dt){ return m[dt]!=null?m[dt]:null; }),
          barMaxWidth: 10, itemStyle:{color:col}, lineStyle:{width:2,color:col}};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d=(DAYS['S6']||[]).find(function(x){return x.date===dt;}) || (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d?d.bench:null; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
var ch = echarts.init(document.getElementById('chart'));
ch.setOption({tooltip:{trigger:'axis'},legend:{top:0,type:'scroll',textStyle:{fontSize:11}},
  grid:{left:44,right:20,top:40,bottom:56},
  xAxis:{type:'category',data:cats.map(function(d){return d.slice(2);}),axisLabel:{rotate:45,fontSize:10,color:'#868e96'}},
  yAxis:{type:'value',axisLabel:{formatter:'{value}%'},splitLine:{lineStyle:{color:'#f0f2f7'}}},
  series: series});
function tradeTable(el, T, code){
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
tradeTable('t6', T6, 'S6');
tradeTable('t6b', T6B, 'S6b');
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'])
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days).replace('__TRD__', '{}')
            .replace('__ST__', strats).replace('__T6__', s6tr).replace('__T6B__', s6btr))
    p = BASE + '/backtest_s6.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
