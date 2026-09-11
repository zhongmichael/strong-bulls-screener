# -*- coding: utf-8 -*-
"""
补拉 K 线末日滞后的股票 (update_all.sh 第 1/9 步的补救工具)

用途: 每日全量拉取时个别股票会因网络抖动/接口限流失败而残留旧数据,
      本脚本专门把这些"掉队"的股票重新拉回来并**合并**进本地历史。

用法:
    python fetch_kline_incremental.py                 # 自动扫描滞后股并补拉
    python fetch_kline_incremental.py --dry-run        # 只看有哪些滞后, 不写盘
    python fetch_kline_incremental.py --days 120       # 加大回溯窗口
    python fetch_kline_incremental.py --file list.json # 指定待补拉清单

要点:
  - 按日期**合并**, 绝不整体覆盖: 早期版本直接 json.dump(arr) 会把本地 640 根历史
    打成窗口内的几十根, 导致 250 日年线等长周期指标全部失效。
  - END 取当天, 不再硬编码; 路径以脚本自身位置为准, 不依赖 cwd。
  - 滞后判定基准 = 全市场 K 线末日的**众数**, 避免被个别退市股带偏。
"""
import argparse
import collections
import glob
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
KLINE_DIR = os.path.join(BASE, "data", "kline")


def fetch_kline(symbol, start, end, count):
    """拉取单只股票K线, 失败重试5次; 返回 (symbol, bars)"""
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={symbol},day,{start},{end},{count},qfq")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://gu.qq.com/"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            item = (d.get("data") or {}).get(symbol) or {}
            arr = item.get("qfqday") or item.get("day") or []
            if arr:
                return symbol, arr
        except Exception:
            pass
        time.sleep(1.0 + attempt * 1.5)
    return symbol, []


def merge_bars(old, arr):
    """按日期合并: 同日以新数据为准(覆盖除权/修正), 再按日期排序"""
    idx = {b[0]: b for b in old}
    before = len(idx)
    for b in arr:
        idx[b[0]] = b
    merged = [idx[k] for k in sorted(idx.keys())]
    return merged, before


def scan_lagging():
    """扫描本地K线, 返回 (滞后股清单, 众数末日, 末日分布)

    基准取"众数"而非"最大值": 最大值会被个别异常文件带偏,
    众数才代表市场真实的最新交易日。
    """
    last_map = {}
    for fp in glob.glob(os.path.join(KLINE_DIR, "*.json")):
        sym = os.path.basename(fp)[:-5]
        try:
            bars = json.load(open(fp, encoding="utf-8"))["bars"]
        except Exception:
            continue
        if bars:
            last_map[sym] = bars[-1][0]
    if not last_map:
        return [], "", {}
    dist = collections.Counter(last_map.values())
    latest = dist.most_common(1)[0][0]
    todo = sorted(s for s, d in last_map.items() if d < latest)
    return todo, latest, dist


def main():
    ap = argparse.ArgumentParser(description="补拉K线末日滞后的股票")
    ap.add_argument("--days", type=int, default=60,
                    help="回溯窗口天数(默认60, 调大可修复更久的缺口)")
    ap.add_argument("--count", type=int, default=800,
                    help="接口单次返回的最大K线根数(默认800)")
    ap.add_argument("--workers", type=int, default=24, help="并发数(默认24)")
    ap.add_argument("--file", help="指定待补拉清单(json数组), 缺省自动扫描")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写盘")
    args = ap.parse_args()

    end = date.today().isoformat()
    start = (date.today() - timedelta(days=args.days)).isoformat()

    if args.file:
        todo = json.load(open(args.file, encoding="utf-8"))
        latest = ""
        print(f"从清单载入 {len(todo)} 只: {args.file}")
    else:
        todo, latest, dist = scan_lagging()
        print(f"扫描 {len(dist) and sum(dist.values())} 只 | 市场最新交易日(众数)={latest}")
        print(f"  末日分布 Top3: {dist.most_common(3)}")
        if not todo:
            print("  无滞后股票, 无需补拉")
            return

    print(f"待补拉 {len(todo)} 只 | 窗口 {start}~{end} | count={args.count}"
          + ("  [DRY-RUN]" if args.dry_run else ""))
    if args.dry_run:
        print("  滞后清单(前30):", todo[:30])
        return

    ok = fail = unchanged = truncated = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_kline, sym, start, end, args.count): sym for sym in todo}
        for i, fut in enumerate(as_completed(futs)):
            sym, arr = fut.result()
            if not arr:
                fail += 1
                continue
            fp = os.path.join(KLINE_DIR, f"{sym}.json")
            old = []
            if os.path.exists(fp):
                try:
                    old = json.load(open(fp, encoding="utf-8"))["bars"]
                except Exception:
                    old = []
            merged, before = merge_bars(old, arr)
            # 护栏: 合并后历史绝不能变短
            if old and len(merged) < before:
                truncated += 1
                print(f"  !! {sym} 合并后变短({before}->{len(merged)}), 跳过写入")
                continue
            if old and len(merged) == before and merged == old:
                unchanged += 1
                continue
            with open(fp, "w", encoding="utf-8") as f:
                json.dump({"symbol": sym, "bars": merged}, f, ensure_ascii=False)
            ok += 1
            if (i + 1) % 200 == 0:
                print(f"  progress {i+1}/{len(todo)} ok={ok} fail={fail} "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)

    print("=" * 46)
    print(f"补拉完成 ok={ok} 无变化={unchanged} 失败={fail} 护栏拦截={truncated} "
          f"耗时 {time.time()-t0:.0f}s")
    if truncated:
        print("  !! 有股票被护栏拦截, 请检查接口是否返回了截断数据")
    if fail:
        print(f"  {fail} 只拉取失败(多为退市/长期停牌股), 可重跑本脚本重试")


if __name__ == "__main__":
    main()
