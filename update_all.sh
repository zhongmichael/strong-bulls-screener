#!/bin/bash
# 至善选股器 每日自动数据更新脚本 (收盘后运行)
# 流程: 增量拉K线 -> 重算强势 -> 生成全部数据 -> gzip -> 同步dist
set -e
# 路径: 以脚本自身位置为准, 不硬编码任何机器相关目录
cd "$(dirname "$0")"
# 解释器: 优先环境变量 -> 托管venv -> 系统python3
if [ -z "$PY" ]; then
  for cand in \
    "${HOME}/.workbuddy/binaries/python/envs/default/bin/python" \
    "${HOME}/.workbuddy/binaries/python/versions/3.13.12/bin/python3" \
    "$(command -v python3 || true)"
  do
    if [ -n "$cand" ] && [ -x "$cand" ]; then PY="$cand"; break; fi
  done
fi
if [ -z "$PY" ]; then echo "找不到可用的 python 解释器"; exit 1; fi
echo "工作目录: $PWD"
echo "解释器  : $PY ($("$PY" -V 2>&1))"
echo "==== [1/9] 增量拉取最新K线 ===="
$PY - << 'PYEOF'
import json, os, time, urllib.request, glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
KLINE_DIR="data/kline"
end = date.today().isoformat()
start = (date.today() - timedelta(days=45)).isoformat()
symbols = [os.path.basename(f)[:-5] for f in glob.glob(KLINE_DIR+"/*.json")]
print(f"  更新 {len(symbols)} 只, 窗口 {start}~{end}")
def fetch(sym):
    url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?param={sym},day,{start},{end},60,qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://gu.qq.com/"})
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            item = (d.get("data") or {}).get(sym) or {}
            arr = item.get("qfqday") or item.get("day") or []
            if arr: return sym, arr
        except Exception: pass
        time.sleep(1.0+a*1.5)
    return sym, []
ok=0; skipped=0
t0=time.time()
with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(fetch,s):s for s in symbols}
    for i,fut in enumerate(as_completed(futs)):
        sym, arr = fut.result()
        if arr:
            fp = os.path.join(KLINE_DIR, sym+".json")
            old = json.load(open(fp,encoding="utf-8"))["bars"] if os.path.exists(fp) else []
            # 关键: 只读回窗口内的30根, 必须与本地历史"合并", 绝不能直接覆盖,
            # 否则每次跑完历史K线(约640根)会被打成30根, 250日年线等长周期指标全部失效
            idx = {b[0]: b for b in old}
            before = len(idx)
            for b in arr: idx[b[0]] = b          # 同日以新数据为准(覆盖除权/修正)
            merged = [idx[k] for k in sorted(idx.keys())]
            if len(merged) != before or any(a is not b for a, b in zip(merged, old)):
                json.dump({"symbol":sym,"bars":merged}, open(fp,"w",encoding="utf-8"), ensure_ascii=False)
                ok += 1
            else:
                skipped += 1
        if (i+1)%1000==0: print(f"    {i+1}/{len(symbols)} ok={ok} {time.time()-t0:.0f}s", flush=True)
# 安全护栏: 若合并后历史被截断(少于200根), 说明本地数据异常, 立即中止后续计算
import random
short = 0
for sym in random.sample(symbols, min(200, len(symbols))):
    try:
        n = len(json.load(open(os.path.join(KLINE_DIR, sym+".json"),encoding="utf-8"))["bars"])
        if n < 200: short += 1
    except Exception: pass
if short > 20:
    raise SystemExit(f"  !! 抽检发现 {short}/200 只历史K线不足200根, 数据异常, 中止后续步骤")
print(f"  新增/更新 {ok} 只 (无变化 {skipped}), 耗时 {time.time()-t0:.0f}s")
PYEOF
echo "==== [2/9] 检查当日K线覆盖率(接口镜像延迟兜底) ===="
# 腾讯K线接口的镜像在收盘后需要一段时间才同步完毕。若覆盖率不足就直接重算,
# 会静默产出一个记录数腰斩的强势池(曾出现 2192/5258 只、池仅705只而非正常的1700只), 且没有任何报错。
# 因此这里先判断目标交易日是否已大面积同步, 不足则用实时行情接口补全当日bar。
CHECK_OUT=$($PY - << 'PYEOF'
import json, glob, os, sys, collections, urllib.request
from datetime import date
def log(*a): print(*a, file=sys.stderr, flush=True)   # 日志走stderr, stdout只留给结果行
today = date.today().isoformat()
TS = today.replace('-', '')
def trading_day():
    try:
        url = "https://qt.gtimg.cn/q=sh000001,sh600519,sz000001,sz399001"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://gu.qq.com/"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "ignore")
        hit = 0
        for line in raw.strip().split(";"):
            if "~" not in line: continue
            p = line.split("~")
            if len(p) < 35: continue
            try: vol = float(p[6])
            except Exception: vol = 0
            if p[30].startswith(TS) and vol > 0: hit += 1
        return hit >= 2
    except Exception as e:
        log(f"  行情探测失败(按非交易日处理): {str(e)[:60]}")
        return False
cnt = collections.Counter()
for fp in glob.glob("data/kline/*.json"):
    try:
        bars = json.load(open(fp, encoding="utf-8"))["bars"]
        if bars: cnt[bars[-1][0]] += 1
    except Exception: pass
total = sum(cnt.values())
if not total:
    raise SystemExit("  !! data/kline 为空, 中止")
latest = max(cnt)
is_trading = trading_day()
target = today if is_trading else latest   # 非交易日则以最后一个交易日为准
have = cnt.get(target, 0)
cover = have / total
lag = total - have
log(f"  最新日期分布: {cnt.most_common(3)}")
log(f"  目标交易日 {target}: 覆盖 {have}/{total} = {cover*100:.1f}%")
# 滞后股诊断: 市场里总有一批退市/长期停牌股是永远补不回来的, 占比通常 ~1%,
# 属正常现象, 不必报警; 但若明显超过这个量级, 说明是拉取环节出了问题, 需人工介入。
if lag > 0 and lag <= total * 0.02:
    log(f"  滞后 {lag} 只({lag/total*100:.1f}%), 多为退市/停牌股, 属正常")
elif lag > total * 0.02:
    log(f"  !! 滞后 {lag} 只({lag/total*100:.1f}%), 超出正常水平, "
        f"建议补拉: python fetch_kline_incremental.py")
# 是否补全当日bar: 只要今天是交易日 且 存在滞后股就补。
# 绝不能用覆盖率阈值(旧版 cover<0.85)做开关 —— 腾讯K线接口每天稳定漏同步几十只票
# (2026-09-03 漏了 22 只: 生益科技/行云科技/工业富联等), 此时覆盖率高达 99.5%,
# 阈值永不触发, 漏掉的票就永远补不回来(与 refresh_core.js 曾犯的同款错误)。
# fill_today_bar.py 内部已有三重校验(vol<=0 停牌 / 时间戳非当日 / 昨收衔接异常),
# 退市停牌股会被自然跳过, 无需外层再用覆盖率兜底。
need_fill = 1 if (is_trading and lag > 0) else 0
print(f"{need_fill} {target}")
PYEOF
)
NEED_FILL=$(echo "$CHECK_OUT" | head -1 | awk '{print $1}')
TARGET=$(echo "$CHECK_OUT" | head -1 | awk '{print $2}')
if [ "$NEED_FILL" = "1" ]; then
  echo "  覆盖率不足, 用实时行情补全 ${TARGET} 的当日bar…"
  $PY fill_today_bar.py "$TARGET" 2>&1 | tail -4
else
  echo "  覆盖率充足, 跳过补全"
fi
echo "==== [3/9] 重算强势股数据 ===="
$PY compute_strong.py 2>&1 | tail -3
echo "==== [4/9] 重建meta(含新股) ===="
$PY - << 'PYEOF'
import json, glob, os
sl = {s['symbol']: s['name'] for s in json.load(open('data/stock_list.json', encoding='utf-8'))['stocks']}
old = json.load(open('data/out/meta.json', encoding='utf-8'))
meta = {}
for fp in glob.glob('data/kline/*.json'):
    sym = os.path.basename(fp)[:-5]
    try:
        bars = json.load(open(fp, encoding='utf-8'))['bars']
        if not bars: continue
        last = bars[-1]
        close = float(last[2])
        prev = float(bars[-2][2]) if len(bars)>=2 else close
        meta[sym] = {'name': sl.get(sym, old.get(sym,{}).get('name','')),
                     'last_close': round(close,2),
                     'last_pct': round((close/prev-1)*100,2),
                     'last_date': last[0]}
    except Exception: continue
json.dump(meta, open('data/out/meta.json','w',encoding='utf-8'), ensure_ascii=False)
print('  meta:', len(meta), '只')
PYEOF
echo "==== [5/9] 生成 strong_data.js ===="
$PY - << 'PYEOF'
import json, os
strong = json.load(open('data/out/strong_2026.json'))
meta = json.load(open('data/out/meta.json'))
td = sorted(strong.keys())
try: blocks = json.load(open('data/out/stock_blocks.json'))
except Exception: blocks = {}
GENERIC = set(['融资融券','深股通','沪股通','创业板综','央国企改革','富时罗素','标准普尔','机构重仓','小盘股','破增发价股','QFII重仓','MSCI中国','HS300_','上证50_','上证180_','深证100R','深成500','创业成份','央视50_','茅指数','百元股','东方财富热股','行业龙头','权重股','大盘股','消费风格','乡村振兴','AH股','证金持股','破净股','红利破净股','周期股','红利股','大盘价值','大盘成长','先进制造风格','金融地产风格','参股券商','参股银行','IPO受益','独角兽','区块链','深圳特区','电商概念','西部大开发','超级品牌','宁组合','储能概念','昨日涨停_含一字','昨日涨停','昨日高振幅','昨日高换手','近期新高','百日新高','历史新高','趋势股','题材股','高市净率','贬值受益','昨涨停_含一字','今破新高','均线多头'])
IND_NAMES = set(['医药生物','基础化工','电力设备','食品饮料','非银金融','银行','电子','计算机','机械设备','汽车','有色金属','钢铁','煤炭','石油石化','公用事业','交通运输','房地产','建筑装饰','建筑材料','家用电器','纺织服饰','轻工制造','商贸零售','社会服务','农林牧渔','国防军工','通信','传媒','环保','美容护理','综合','其他塑料制品','其他生物制品','塑料','电池','酿酒','白酒','化学制药','生物制品'])
# 一级行业白名单(申万2021版31个): 从东财板块列表里匹配出该股票的一级归属
L1_ORDER = ['农林牧渔','基础化工','钢铁','有色金属','电子','汽车','家用电器','食品饮料','纺织服饰','轻工制造','医药生物','公用事业','交通运输','房地产','商贸零售','社会服务','综合','建筑材料','建筑装饰','电力设备','国防军工','计算机','传媒','通信','银行','非银金融','美容护理','煤炭','石油石化','环保','机械设备']
L1_SET = set(L1_ORDER)
def l1_of(blk):
    """一级行业: 板块列表中出现最早的申万一级词; 无则空"""
    if not blk: return ''
    for x in blk:
        if x in L1_SET: return x
    return ''
def pb(blk):
    if not blk: return '', ''
    ind = blk[0]; cons = []
    for x in blk[1:]:
        if x in GENERIC or x in IND_NAMES: continue
        if x in cons or x == ind: continue
        if x.endswith('板块') and len(x) <= 6: continue
        cons.append(x)
        if len(cons) >= 3: break
    return ind, ','.join(cons[:3])
meta2 = {}
# 停牌/数据滞后的股票, 其 last_pct 实际是"上一交易日相对再前一日的涨幅", 不是最新日的。
# 照抄会让页面把它当成最新交易日的涨跌幅展示 —— 例如 2026-09-03 有研硅(8/28 起停牌)
# 会显示 -1.67%, 属静默误导。这里对日期不等于最新日的置 None, 让页面统一显示 "--"。
max_last = max((m.get('last_date') or '' for m in meta.values()), default='')
stale = 0
for sym, m in meta.items():
    blk = blocks.get(sym, [])
    ind, cons = pb(blk)
    pct = m['last_pct'] if (m.get('last_date') == max_last) else None
    if pct is None: stale += 1
    # meta2 结构: [名称, 收盘, 当日pct, 细分行业(blk[0]), 概念串, 一级行业]
    # 索引5=一级行业: 前端涨幅榜饼图/板块列按一级归类, 少很多"未分类/其他"; 细分仍留索引3
    meta2[sym] = [m['name'], m['last_close'], pct, ind, cons, l1_of(blk)]
print(f'  strong_data 最新日={max_last}, 停牌/滞后置空的涨跌幅: {stale} 只, 一级行业覆盖: {sum(1 for v in meta2.values() if v[5])} 只')
summary = {}
for date, day in strong.items():
    nP = nD = n1 = 0
    for s, r in day.items():
        if r[15] >= 7 and (r[16] >= 6 or r[3] >= 50): nP += 1
        if r[0] and r[1] and r[2]: nD += 1
        if r[0]: n1 += 1
    summary[date] = [nP, nD, n1]
data = {'dates': td, 'strong': strong, 'meta': meta2, 'sum': summary, 'gen': 'auto-'+__import__('datetime').date.today().isoformat()}
with open('strong_data.js', 'w', encoding='utf-8') as f:
    f.write('window.STRONG_DATA = ')
    json.dump(data, f, ensure_ascii=False, separators=(',',':'))
    f.write(';')
print('  strong_data.js:', os.path.getsize('strong_data.js')//1024, 'KB')
PYEOF
echo "==== [6/9] 生成 gain_board + year_kline ===="
$PY gen_gain_board.py 2>&1 | tail -2
echo "==== [7/9] 生成 V2.1 买点数据 ===="
$PY compute_buydian_v21.py 2>&1 | tail -1
$PY gen_buydian_v21_page.py 2>&1 | tail -1
echo "==== [8/9] 生成 kline_ref ===="
$PY - << 'PYEOF'
import json, glob, os
from datetime import datetime
def iso_week(dstr):
    dt = datetime.strptime(dstr, '%Y-%m-%d')
    return dt.isocalendar()[0:2]
out = {}
for fp in glob.glob('data/kline/*.json'):
    sym = os.path.basename(fp)[:-5]
    try: bars = json.load(open(fp, encoding='utf-8'))['bars']
    except Exception: continue
    if not bars: continue
    d = bars[-130:]
    w_map = {}
    for b in bars:
        w_map[iso_week(b[0])] = float(b[2])
    w = [w_map[k] for k in sorted(w_map.keys())]
    m_map = {}
    for b in bars: m_map[b[0][:7]] = float(b[2])
    m = [m_map[k] for k in sorted(m_map.keys())]
    out[sym] = {'d': d, 'w': w, 'm': m, 'ld': bars[-1][0]}
with open('kline_ref.js', 'w', encoding='utf-8') as f:
    f.write('window.KLINE_REF = ')
    json.dump(out, f, ensure_ascii=False, separators=(',',':'))
    f.write(';')
print('  kline_ref.js:', os.path.getsize('kline_ref.js')//1024, 'KB,', len(out), '只')
PYEOF
echo "==== [9/9] 同步 dist + gzip ===="
# 先同步未压缩文件与页面, 再统一打包 —— 顺序很重要:
# 历史上的故障就是只更新了 .js 却没重新 gzip, 而页面优先加载 .gz, 导致线上一直读到旧包
rm -f dist_strong/*.gz
cp -f strong_screener.html buydian_v21.html \
      strong_data.js buydian_v21_data.js year_kline.js kline_ref.js gain_board.js sector_ref.js \
      echarts.min.js echarts.min.js.gz dist_strong/
"$PY" rebuild_gz.py --targets . dist_strong

echo "---- 发布自检: 校验 .gz 内容日期与 .js 一致 ----"
"$PY" - << 'CHKEOF'
import gzip, json, os, sys
def load(p):
    # 用 magic bytes 判断, 不能靠扩展名, 更不能先按明文读一遍(.gz 会直接抛 UnicodeDecodeError)
    with open(p, 'rb') as f:
        head = f.read(2)
    if head == b'\x1f\x8b':
        raw = gzip.open(p, 'rt', encoding='utf-8').read()
    else:
        raw = open(p, encoding='utf-8').read()
    return json.loads(raw[raw.index('=') + 1:].rstrip().rstrip(';'))
ok = True
for d in ('.', 'dist_strong'):
    js = load(os.path.join(d, 'strong_data.js'))
    gz = load(os.path.join(d, 'strong_data.js.gz'))
    djs, dgz = js['dates'][-1], gz['dates'][-1]
    same = djs == dgz
    ok = ok and same
    print(f"  {d:12s} strong_data  js末日={djs}  gz末日={dgz}  {'OK' if same else '!! 不一致 -> 页面会读到旧数据'}")
if not ok:
    print("自检未通过: .gz 未跟上 .js")
    sys.exit(1)
print("  自检通过")
CHKEOF
echo "==== 全部完成 ===="
ls -lh dist_strong/*.gz | awk '{print $5, $9}'
