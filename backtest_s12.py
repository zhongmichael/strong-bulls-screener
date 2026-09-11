# -*- coding: utf-8 -*-
"""
backtest_s12.py — S12 策略: 大冰点日 × 红盘(0<pct<4%) × 剔弱势板块
====================================================================
用户命题: 选大冰点日 红盘但涨幅<4% 的个股, 剔除目前短期弱势的大消费/白酒/地产/银行。

口径:
  · 大冰点日: 情绪温度 < 20 (全部冰点日为 <30, 26天; <20 的 8 天为最冷一批)
  · 红盘窄幅: 0 < 当日涨幅 < 4% (冰点日仍红 = 有资金护盘; <4% 排除涨停/大阳, 找未加速的)
  · 剔弱势板块: 一级板块 ∈ {食品饮料(含白酒), 农林牧渔, 商贸零售, 纺织服饰, 家用电器,
    轻工制造, 社会服务, 美容护理, 房地产, 银行} → 剔除
  · 非ST, 一级板块配额2
  · 评分 = 相对大盘×3 + 强势板块超额×4 + 强势池+10 (红盘动量的冰点日适配版)

变体隔离:
  · S12 : 主策略 — 大冰点(<20) × 红盘<4% × 剔弱势板块
  · S12b: 阈值对照 — 同画像但全部冰点日(<30)都跑, 隔离"大冰点"本身的价值
  · S12c: 剔除对照 — 大冰点但"不剔"弱势板块, 隔离板块剔除的贡献
交易: 触发日收盘等权买 TOP10 → 次日收盘卖。
"""
import json, sys

sys.path.insert(0, '/Users/michael/Documents/golden-system/td9-screener')
from backtest_bingdian import build, BD_TH  # noqa
from backtest_bingdian_multi import MultiBacktest, STRATS  # noqa

BIG_BD_TH = 20   # 大冰点线

# 短期弱势剔除集: 大消费(含白酒) + 地产 + 银行
WEAK = {'食品饮料', '农林牧渔', '商贸零售', '纺织服饰', '家用电器',
        '轻工制造', '社会服务', '美容护理', '房地产', '银行'}


def pick_s12(bt, sc, big_bd, exclude_weak):
    """红盘窄幅画像。big_bd: 只在温度<BIG_BD_TH 的日子生效(由调用方控制触发日),
    exclude_weak: 是否剔除弱势板块。"""
    rows = [r for r in sc['rows'].values()
            if 'ST' not in r['name'] and 'st' not in r['name']]
    if exclude_weak:
        rows = [r for r in rows if r['ind'] not in WEAK]
    pool_day = None
    di = bt.day_idx[sc['target']]
    for back in range(0, 4):
        pool_day = bt.strong_pool.get(bt.dates[di - back])
        if pool_day: break
    cand = []
    for r in rows:
        if not (0 < r['pct'] < 4): continue                  # 红盘但涨幅<4%
        score = r['rel'] * 3 + (r['secRel'] * 4 if r['secRel'] is not None else 0)
        tags = ['红盘窄幅']
        if pool_day and pool_day.get(r['sym']):
            score += 10; tags.append('强势池')
        if r['hot']:
            tags.append('强板块')
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


S12_STRATS = [
    ('S12',  '大冰点×红盘<4%×剔弱势', '温度<20日 × 红盘0~4% × 剔大消费/白酒/地产/银行 × 池+超额打分'),
    ('S12b', '全部冰点×红盘<4%×剔弱势', '同画像但全部冰点日(<30)参与, 隔离"大冰点"阈值的价值'),
    ('S12c', '大冰点×红盘<4%×不剔板块', '同画像但不剔弱势板块, 隔离板块剔除的贡献'),
]


def main():
    sd, yk, meta, sd_dates, strong_pool, dates, day_idx, scores, st = build()
    bt = MultiBacktest(yk, meta, dates, day_idx, scores, strong_pool)
    ice_all = sorted(d for d in dates[1:-1] if scores.get(d) is not None and scores[d] < BD_TH)
    big_bd = [d for d in ice_all if scores[d] < BIG_BD_TH]
    print('冰点日 %d 天, 其中大冰点(<%d) %d 天: %s' % (
        len(ice_all), BIG_BD_TH, len(big_bd), ','.join(d[5:] for d in big_bd)))

    all_strats = [(c, n, d) for c, n, d in STRATS] + S12_STRATS
    results = {c: dict(days=[], trades=[], skipped=0) for c, _, _ in all_strats}

    for t in ice_all:
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
        is_big = scores[t] < BIG_BD_TH
        picks = {}
        for code, _, _ in STRATS:
            picks[code] = bt.pick(t, code, sc)
        if is_big:
            picks['S12'] = pick_s12(bt, sc, True, True)
            picks['S12c'] = pick_s12(bt, sc, True, False)
        else:
            picks['S12'] = []; picks['S12c'] = []
        picks['S12b'] = pick_s12(bt, sc, False, True)
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
                            empty=(len(ice_all) - len(R['days'])) if code in ('S12', 'S12c') else 0,
                            skipped=R['skipped']))

    print('\n========== S12 大冰点×红盘<4%%×剔弱势 (收盘买TOP10 → 次日收盘卖) ==========')
    print('窗口: %s -> %s | 冰点 %d 天(大冰点 %d 天)\n' % (dates[0], dates[-1], len(ice_all), len(big_bd)))
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

    out = dict(window=[dates[0], dates[-1]], ndays_trigger=len(ice_all), bd_th=BD_TH,
               big_bd_th=BIG_BD_TH, big_days=big_bd,
               strats=[dict(code=c, name=n, desc=d) for c, n, d in all_strats],
               summary=summary,
               days={c: results[c]['days'] for c, _, _ in all_strats},
               trades={c: results[c]['trades'] for c, _, _ in all_strats})
    with open('/Users/michael/Documents/golden-system/td9-screener/backtest_s12_data.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    render_report(out)
    print('\n已导出 backtest_s12_data.json / backtest_s12.html')


def render_report(out):
    sm = json.dumps(out['summary'], ensure_ascii=False)
    days = json.dumps(out['days'], ensure_ascii=False)
    strats = json.dumps(out['strats'], ensure_ascii=False)
    bigdays = json.dumps(out['big_days'], ensure_ascii=False)
    t12 = json.dumps(out['trades']['S12'], ensure_ascii=False)
    t12b = json.dumps(out['trades']['S12b'], ensure_ascii=False)
    html = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>S12 策略 · 大冰点×红盘窄幅×剔弱势板块</title>
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
<h1>🧊 S12 · 大冰点日买「红盘窄幅 × 剔弱势板块」</h1>
<div class="sub">共同口径: 冰点日(温度&lt;30) <b>收盘等权买入 TOP10 → 下一交易日收盘卖出</b> · 窗口 __W0__ → __W1__（冰点 __ND__ 天, 其中大冰点&lt;20 共 __NB__ 天）· 基准: 全市场等权次日涨幅<br>
<b>画像</b>: 0 &lt; 当日涨幅 &lt; 4%（冰点日仍红 = 有资金护盘, 但排除涨停/大阳的已加速票）× 非ST × 一级板块配额≤2 × 评分=相对大盘×3 + 强势板块超额×4 + 强势池+10<br>
<b>剔除集</b>: 大消费{食品饮料(含白酒)、农林牧渔、商贸零售、纺织服饰、家用电器、轻工制造、社会服务、美容护理} + 房地产 + 银行<br>
<b>S12</b>: 主策略 — 仅在大冰点日(温度&lt;20)持仓<br>
<b>S12b</b>: 阈值对照 — 同画像但全部 26 个冰点日参与, 隔离"大冰点"的价值<br>
<b>S12c</b>: 剔除对照 — 大冰点但<b>不</b>剔弱势板块, 隔离板块剔除的贡献<br>
__SDESC__</div>
<div class="panel"><h2>策略总览（按日均超额降序，S12 系加粗背景）</h2><table id="sumtbl"></table></div>
<div class="panel"><h2>逐触发日 TOP10 次日均值（%）</h2><div id="chart" style="width:100%;height:420px"></div></div>
<div class="panel"><h2>S12 逐笔明细</h2><div class="tblbox"><table id="t12"></table></div></div>
<div class="panel"><h2>S12b 逐笔明细（全部冰点日版）</h2><div class="tblbox"><table id="t12b"></table></div></div>
<div class="panel note">口径说明: ① 各策略共用同一触发日集与基准, 差异仅在选股画像与触发阈值; ② S12/S12c 在温度≥20 的冰点日空仓(计入"空仓"列); ③ 年K仅收盘价; ④ 复利为逐触发日示意累乘; ⑤ 仅为策略研究, 不构成投资建议。</div>
</div>
<script>
var SM = __SM__, DAYS = __DAYS__, STLIST = __ST__, BIGD = __BIGD__;
var order = SM.slice().sort(function(a,b){ return (b.excess||-99) - (a.excess||-99); }).map(function(s){ return s.code; });
var byCode = {}; SM.forEach(function(s){ byCode[s.code] = s; });
var h = '<tr><th>策略</th><th>画像</th><th>天数</th><th>空仓</th><th>笔数</th><th>单笔均值</th><th>胜率</th><th>日均超额</th><th>剔最佳3笔</th><th>最差单日</th><th>复利(示意)</th><th>26后均值</th><th>最佳/最差单笔</th></tr>';
order.forEach(function(c, i){
  var s = byCode[c];
  var hl = (c==='S12'||c==='S12b'||c==='S12c');
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
var focus = ['S12','S12b','S12c','S2','S5'].filter(function(c){ return order.indexOf(c)>=0; });
var series = focus.map(function(c){
  var m = {}; (DAYS[c]||[]).forEach(function(d){ m[d.date] = d.avg; });
  var col = c==='S12' ? '#d6336c' : c==='S12b' ? '#e64980' : c==='S12c' ? '#f06595' : c==='S5' ? '#9c36b5' : '#495057';
  return {name: c + ' ' + byCode[c].name, type: c==='S2'?'line':'bar', data: cats.map(function(dt){ return m[dt]!=null?m[dt]:null; }),
          barMaxWidth: 10, itemStyle:{color:col}, lineStyle:{width:2,color:col}};
});
series.push({name: '次日大盘等权', type: 'line', data: cats.map(function(dt){ var d=(DAYS['S12b']||[]).find(function(x){return x.date===dt;}) || (DAYS[order[0]]||[]).find(function(x){return x.date===dt;}); return d?d.bench:null; }), symbol:'circle', symbolSize:5, itemStyle:{color:'#1c7ed6'}, lineStyle:{width:2}});
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
tradeTable('t12', __T12__); tradeTable('t12b', __T12B__);
window.addEventListener('resize', function(){ ch.resize(); });
</script></body></html>"""
    sdesc = '<br>'.join('<span class="tag">%s %s</span>%s' % (c, n, d) for c, n, d in out['strats'] if c in ('S2', 'S5'))
    html = (html.replace('__W0__', out['window'][0]).replace('__W1__', out['window'][1])
            .replace('__ND__', str(out['ndays_trigger'])).replace('__NB__', str(len(out['big_days'])))
            .replace('__BIGD__', bigdays).replace('__SDESC__', sdesc)
            .replace('__SM__', sm).replace('__DAYS__', days)
            .replace('__ST__', strats).replace('__T12__', t12).replace('__T12B__', t12b))
    p = '/Users/michael/Documents/golden-system/td9-screener/backtest_s12.html'
    open(p, 'w', encoding='utf-8').write(html)


if __name__ == '__main__':
    main()
