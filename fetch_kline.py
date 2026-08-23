# -*- coding: utf-8 -*-
"""抓取A股全市场日K线数据（腾讯自选股接口，并发，纯标准库）"""
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

START = "2024-01-01"   # 预热：月线红9需要约13根月K，2024至今够用
END = "2026-08-22"
OUT_DIR = "data/kline"

def fetch_kline(symbol):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={symbol},day,{START},{END},640,qfq")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://gu.qq.com/"})
    for attempt in range(4):
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

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open("data/stock_list.json", encoding="utf-8") as f:
        stocks = json.load(f)["stocks"]
    todo = [s["symbol"] for s in stocks
            if not os.path.exists(os.path.join(OUT_DIR, f"{s['symbol']}.json"))]
    print(f"total={len(stocks)} to_fetch={len(todo)}")
    ok, fail = 0, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=32) as ex:
        futs = {ex.submit(fetch_kline, sym): sym for sym in todo}
        for i, fut in enumerate(as_completed(futs)):
            sym, arr = fut.result()
            if arr:
                with open(os.path.join(OUT_DIR, f"{sym}.json"), "w") as f:
                    json.dump({"symbol": sym, "bars": arr}, f)
                ok += 1
            else:
                fail += 1
            if (i + 1) % 400 == 0:
                print(f"  progress {i+1}/{len(todo)} ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s")
    print(f"DONE ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
