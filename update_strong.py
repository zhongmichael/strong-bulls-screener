# -*- coding: utf-8 -*-
"""
强势股选股器 一键数据更新脚本
流程: 抓取最新K线 -> 重算强势/回踩/板块 -> 生成 strong_data.js -> 同步 dist
用法: python update_strong.py
说明: 全市场约4600只, 全量重抓约3-4分钟; 重算约10秒
"""
import json
import os
import sys
import time
import glob
import shutil
import urllib.request
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
KLINE_DIR = os.path.join(BASE, "data", "kline")
OUT_DIR = os.path.join(BASE, "data", "out")
DIST_DIR = os.path.join(BASE, "dist_strong")

def fetch_kline(symbol, start, end):
    # 镜像接口 (web.ifzq.gtimg.cn 会被WAF拦截返回501, 必须走 proxy.finance.qq.com)
    url = (f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?"
           f"param={symbol},day,{start},{end},900,qfq")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://gu.qq.com/"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode("utf-8"))
            item = (d.get("data") or {}).get(symbol) or {}
            arr = item.get("qfqday") or item.get("day") or []
            if arr:
                return symbol, arr
        except Exception:
            pass
        time.sleep(1.0 + attempt * 1.5)
    return symbol, []

def step1_fetch():
    """全市场增量抓取K线 (保留历史, 追加新交易日)"""
    print("=" * 50)
    print("[1/4] 抓取最新K线数据...")
    start = "2023-12-01"
    end = date.today().isoformat()
    # 已有股票直接增量更新
    files = glob.glob(os.path.join(KLINE_DIR, "*.json"))
    symbols = [os.path.basename(f)[:-5] for f in files]
    print(f"  已有 {len(symbols)} 只, 开始更新...")
    ok = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_kline, s, start, end): s for s in symbols}
        for k, fut in enumerate(as_completed(futs)):
            sym, arr = fut.result()
            if arr:
                with open(os.path.join(KLINE_DIR, sym + ".json"), "w", encoding="utf-8") as f:
                    json.dump({"symbol": sym, "bars": arr}, f)
                ok += 1
            if (k + 1) % 500 == 0:
                print(f"    {k+1}/{len(symbols)} ok={ok} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"  更新完成: {ok}/{len(symbols)} 只, 耗时 {time.time()-t0:.0f}s")
    return symbols

def step2_compute():
    """重算强势/回踩数据 + 刷新meta最新价"""
    print("[2/4] 重算强势股数据...")
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(BASE, "compute_strong.py")],
                       cwd=BASE, capture_output=True, text=True)
    print(r.stdout[-500:])
    if r.returncode != 0:
        print("ERROR:", r.stderr[-800:])
        sys.exit(1)
    # 刷新 meta.json 的 last_close/last_pct/last_date (从最新K线)
    print("  刷新meta最新价...")
    script = '''
import json, glob, os
kline_files = glob.glob('data/kline/*.json')
meta = json.load(open('data/out/meta.json', encoding='utf-8'))
fixed = 0
for fp in kline_files:
    sym = os.path.basename(fp)[:-5]
    if sym not in meta: continue
    try:
        d = json.load(open(fp, encoding='utf-8'))
        bars = d['bars']
        if not bars: continue
        last = bars[-1]
        close = float(last[2])
        prev_close = float(bars[-2][2]) if len(bars) >= 2 else close
        meta[sym]['last_close'] = round(close, 2)
        meta[sym]['last_pct'] = round((close/prev_close-1)*100, 2)
        meta[sym]['last_date'] = last[0]
        fixed += 1
    except Exception:
        pass
json.dump(meta, open('data/out/meta.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('  meta刷新:', fixed, '只')
'''
    r2 = subprocess.run([sys.executable, "-c", script], cwd=BASE,
                        capture_output=True, text=True)
    print(r2.stdout[-200:])
    if r2.returncode != 0:
        print("WARN meta refresh failed:", r2.stderr[-300:])

def step3_pack():
    """生成 strong_data.js"""
    print("[3/4] 打包网页数据...")
    import subprocess
    script = '''
import json, os
strong = json.load(open('data/out/strong_2026.json'))
meta = json.load(open('data/out/meta.json'))
td = sorted(strong.keys())   # 交易日动态从strong提取(避免旧文件不同步)
try:
    blocks = json.load(open('data/out/stock_blocks.json'))
except Exception:
    blocks = {}
GENERIC = {...} if False else set(['融资融券','深股通','沪股通','创业板综','央国企改革','富时罗素','标准普尔','机构重仓','小盘股','破增发价股','QFII重仓','MSCI中国','HS300_','上证50_','上证180_','深证100R','深成500','创业成份','央视50_','茅指数','百元股','东方财富热股','行业龙头','权重股','大盘股','消费风格','乡村振兴','AH股','证金持股','破净股','红利破净股','周期股','红利股','大盘价值','大盘成长','先进制造风格','金融地产风格','参股券商','参股银行','IPO受益','独角兽','区块链','深圳特区','电商概念','西部大开发','超级品牌','宁组合','储能概念','昨日涨停_含一字','昨日涨停','昨日高振幅','昨日高换手','近期新高','百日新高','历史新高','趋势股','题材股','高市净率','贬值受益','昨涨停_含一字','今破新高','均线多头'])
IND_NAMES = set(['医药生物','基础化工','电力设备','食品饮料','非银金融','银行','电子','计算机','机械设备','汽车','有色金属','钢铁','煤炭','石油石化','公用事业','交通运输','房地产','建筑装饰','建筑材料','家用电器','纺织服饰','轻工制造','商贸零售','社会服务','农林牧渔','国防军工','通信','传媒','环保','美容护理','综合','其他塑料制品','其他生物制品','塑料','电池','酿酒','白酒','化学制药','生物制品'])
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
for sym, m in meta.items():
    ind, cons = pb(blocks.get(sym, []))
    meta2[sym] = [m['name'], m['last_close'], m['last_pct'], ind, cons]
summary = {}
for date, day in strong.items():
    nP = nD = n1 = 0
    for s, r in day.items():
        if r[15] >= 7 and (r[16] >= 6 or r[3] >= 50): nP += 1
        if r[0] and r[1] and r[2]: nD += 1
        if r[0]: n1 += 1
    summary[date] = [nP, nD, n1]
data = {'dates': td, 'strong': strong, 'meta': meta2, 'sum': summary,
        'gen': 'auto-' + __import__('datetime').date.today().isoformat()}
with open('strong_data.js', 'w', encoding='utf-8') as f:
    f.write('window.STRONG_DATA = ')
    json.dump(data, f, ensure_ascii=False, separators=(',',':'))
    f.write(';')
print('strong_data.js:', os.path.getsize('strong_data.js')//1024, 'KB')
'''
    r = subprocess.run([sys.executable, "-c", script], cwd=BASE,
                       capture_output=True, text=True)
    print(r.stdout[-300:])
    if r.returncode != 0:
        print("ERROR:", r.stderr[-800:])
        sys.exit(1)

def step4_sync():
    """同步到 dist 目录"""
    print("[4/4] 同步到部署目录...")
    os.makedirs(DIST_DIR, exist_ok=True)
    for f in ["strong_screener.html", "strong_data.js", "echarts.min.js",
              "buydian_v21.html", "buydian_v21_data.js"]:
        src = os.path.join(BASE, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DIST_DIR, f))
    print("  同步完成:", ", ".join(os.listdir(DIST_DIR)))

def main():
    t0 = time.time()
    step1_fetch()
    step2_compute()
    step3_pack()
    step4_sync()
    print("=" * 50)
    print(f"✅ 全部完成! 总耗时 {time.time()-t0:.0f}s")
    print("下一步: 重新部署 dist_strong 目录即可上线最新数据")

if __name__ == "__main__":
    main()
