# -*- coding: utf-8 -*-
"""
backtest_s10.py — S10 策略: 科技股 × 非妖 × 强趋势 (冰点日)
==========================================================
用户命题: 把妖股都剔除, 尽量选强趋势的科技股。
承接 S9 教训: 近月涨幅TOP50 = 妖股集中营(胜率48%), 剔妖+科技白名单。

口径:
  · 科技白名单: 一级板块 ∈ {电子, 计算机, 通信} (申万一级, meta[5])
  · 妖股剔除: 近20日涨幅 > 50% 或 近5日涨幅 > 20% → 剔除
  · 强趋势: 收盘 >= MA20 且 >= MA60 且 MA20 上行
  · S10a: S9科技去妖版 — 另要求近5日在调整(ret5<0), 当日>=-5%
  · S10b: 强趋势抗跌版 — 不要求调整, 当日>=-3%, 均线多头(MA5>MA10>MA20)优先
  · S10c: S10a + 近20日涨幅>=10%(要求"真强过", 排除长期阴跌)
  · 评分 = 近20日涨幅×0.1 + 相对大盘×1.5 + 多头排列+10 + 贴MA20(<=6%)+8 + 细分行业板块超额×4
  · 非ST, 细分行业配额2
交易: 触发日收盘等权买 TOP10 → 次日收盘卖。
"""
import json, sys

sys.path.insert(0, '/Users/michael/Documents/golden-system/td9-screener')
from backtest_bingdian import build, BD_TH  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS, industry  # noqa

TECH = {'电子', '计算机', '通信'}


def is_fairy(r):
    """妖股: 近20日>50% 或 近5日>20%"""
    if r['ret20'] is not None and r['ret20'] > 50: return True
    if r['ret5'] is not None and r['ret5'] > 20: return True
    return False


def pick_s10(bt, sc, mode):
    rows = [r for r in sc['rows'].values()
            if 'ST' not in r['name'] and 'st' not in r['name']
            and industry(bt.meta, r['sym']) in TECH and not is_fairy(r)]
    # 细分行业超额 (科技内部)
    sec = {}
    for r in rows:
        a = sec.setdefault(r['ind'], [0.0, 0]); a[0] += r['pct']; a[1] += 1
    sec_avg = {k: v[0] / v[1] for k, v in sec.items() if v[1] >= 3}
    mkt = sc['mkt_avg']
    cand = []
    for r in rows:
        if r['ma20'] is None or r['ma60'] is None or r['ma20p'] is None: continue
        if not (r['c'] >= r['ma20'] and r['c'] >= r['ma60'] and r['ma20'] > r['ma20p']): continue
        if mode in ('S10a', 'S10c'):
            if r['ret5'] is None or r['ret5'] >= 0: continue      # 近5日在调整
            if r['pct'] < -5: continue
            if mode == 'S10c' and (r['ret20'] is None or r['ret20'] < 10): continue
        else:  # S10b 强趋势抗跌
            if r['pct'] < -3: continue
            if r['ret20'] is None or r['ret20'] < 3: continue
        score = (r['ret20'] or 0) * 0.1 + r['rel'] * 1.5
        tags = []
        if r['ma5'] and r['ma10'] and r['ma20'] and r['ma5'] > r['ma10'] > r['ma20']:
            score += 10; tags.append('多头')
        dev20 = (r['c'] / r['ma20'] - 1) * 100
        if dev20 <= 6: score += 8; tags.append('贴MA20')
        sa = sec_avg.get(r['ind'])
        if sa is not None and sa > mkt:
            score += (sa - mkt) * 4; tags.append('强细分')
        cand.append((score, r, '+'.join(tags) or '趋势'))
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


S10_STRATS = [
    ('S10a', '科技×非妖×趋势×5日调整', '电子/计算机/通信 × 剔妖(20日≤50%,5日≤20%) × MA20/60上 × 近5日<0'),
    ('S10b', '科技×非妖×强趋势抗跌', '同白名单, 不要求调整, 当日≥-3%, 多头排列优先'),
    ('S10c', '科技×非妖×趋势×调整×20日≥10%', 'S10a + 近20日涨幅≥10%(要求真强过)'),
]


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    triggers = [d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH]
    print('冰点触发日: %d 天' % len(triggers))

    all_strats = [(c, n, d) for c, n, d in STRATS] + S10_STRATS
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
        picks['S10a'] = pick_s10(bt, sc, 'S10a')
        picks['S10b'] = pick_s10(bt, sc, 'S10b')
        picks['S10c'] = pick_s10(bt, sc, 'S10c')
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

    print('\n========== S10 科技×非妖×强趋势 (冰点日收盘买TOP10 → 次日收盘卖) ==========')
    print('窗口: %s -> %s | 冰点触发 %d 天\n' % (dates[0], dates[-1], len(triggers)))
    hdr = '%-5s %-24s %-5s %-5s %-8s %-6s %-9s %-9s %-9s %-8s'
    print(hdr % ('策略', '名称', '天数', '笔数', '单笔均值', '胜率', '日均超额', '剔最佳3笔', '最差单日', '26后均值'))
    for s in sorted(summary, key=lambda x: -(x.get('excess') or -99)):
        if s['n'] == 0:
            print('%-5s %-24s 无交易' % (s['code'], s['name'])); continue
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
    with open('/Users/michael/Documents/golden-system/td9-screener/backtest_s10_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s10_data.json / backtest_s10.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    t10a = json.dumps(out['trades']['S10a'], ensure_ascii=False)
    t10b = json.dumps(out['trades']['S10b'], ensure_ascii=False)
    t10c = json.dumps(out['trades']['S10c'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S10 策略 · 科技×非妖×强趋势</title>
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
<h1>🧊 S10 · 冰点日买「科技股 × 剔妖 × 强趋势」</h1>
<div class="sub">共同口径: 情绪温度 &lt; 30 触发日 <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（触发 __ND__ 天）· 基准: 全市场等权次日涨幅<br>
<b>公共条件</b>: 一级板块 ∈ {电子, 计算机, 通信}（申万一级，约950只）× 剔妖股（近20日涨幅&gt;50% 或 近5日&gt;20% 即剔除）× 收盘≥MA20 且 ≥MA60 且 MA20上行 × 非ST × 细分行业配额≤2<br>
<b>S10a</b>: 保留回调要素 — 近5日涨幅&lt;0（近一周在调整）× 当日≥-5%<br>
<b>S10b</b>: 强趋势抗跌版 — 不要求调整，当日≥-3%，均线多头(MA5&gt;MA10&gt;MA20)优先<br>
<b>S10c</b>: S10a + 近20日涨幅≥10%（要求"真强过"，排除长期阴跌股）<br>
__SDESC__</div>
<div class="panel"><h2>策略总览（按日均超额降序，S10 系加粗背景）</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>逐触发日 TOP10 次日均值（%）</h2><div id="chart" style="width:100%;height:420px"></div></div>
<div class="panel"><h2>S10a 逐笔明细</h2><div class="tblbox"><table id="t10a"></table></div></div>
<div class="panel"><h2>S10b 逐笔明细</h2><div class="tblbox"><table id="t10b"></table></div></div>
<div class="panel"><h2>S10c 逐笔明细</h2><div class="tblbox"><table id="t10c"></table></div></div>
<div class="panel note">口径说明: ① 各策略共用同一触发日与基准，差异仅在选股画像; ② 妖股定义为纯动量口径(无换手/龙虎榜数据); ③ 年K仅收盘价; ④ 细分行业超额取科技内部均值; ⑤ 仅为策略研究，不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, STLIST = __ST__, T10A = __T10A__, T10B = __T10B__, T10C = __T10C__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
var h = '<tr><th>策略</th><th>画像</th><th>天数</th><th>空仓</th><th>笔数</th><th>单笔均值</th><th>胜率</th><th>日均超额</th><th>剔最佳3笔</th><th>最差单日</th><th>复利(示意)</th><th>26后均值</th><th>最佳/最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  var hl = (c==='S10a'||c==='S10b'||c==='S10c');
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
var focus = ['S10a','S10b','S10c','S5','S1'].filter(function(c){ return order.indexOf(c)>=0; });
var series = focus.map(function(c){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  var col = c==='S10a' ? '#e8590c' : c==='S10b' ? '#d9480f' : c==='S10c' ? '#f76707' : c==='S5' ? '#9c36b5' : '#495057';
  return {name: c + ' ' + byCode[c].name, type: c==='S1'?'line':'bar', data: cats.map(function(dt){ return m[dt]!=null?m[dt]:null; }),
          barMaxWidth: 10, itemStyle:{color:col}, lineStyle:{width:2,color:col}};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d=(DAYS['S10a']||[]).find(function(x){return x.date===dt;}) || (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d?d.bench:null; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
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
tradeTable('t10a', T10A); tradeTable('t10b', T10B); tradeTable('t10c', T10C);
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'] if c in ('S1', 'S5'))
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days)
            .replace('__ST__', strats).replace('__T10A__', t10a).replace('__T10B__', t10b).replace('__T10C__', t10c))
    p = '/Users/michael/Documents/golden-system/td9-screener/backtest_s10.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
