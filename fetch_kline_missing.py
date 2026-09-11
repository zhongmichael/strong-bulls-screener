# -*- coding: utf-8 -*-
"""补拉缺失股票的日K线(科创板/北交所等新增)"""
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

START = "2024-01-01"
END = "2026-08-31"
OUT_DIR = "data/kline"

def fetch_kline(symbol):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={symbol},day,{START},{END},640,qfq")
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

def main():
    todo = json.load(open("/tmp/missing_kline.json", encoding="utf-8"))
    print(f"to_fetch={len(todo)}")
    ok, fail = 0, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(fetch_kline, sym): sym for sym in todo}
        for i, fut in enumerate(as_completed(futs)):
            sym, arr = fut.result()
            if arr:
                with open(os.path.join(OUT_DIR, f"{sym}.json"), "w", encoding="utf-8") as f:
                    json.dump({"symbol": sym, "bars": arr}, f, ensure_ascii=False)
                ok += 1
            else:
                fail += 1
            if (i + 1) % 200 == 0:
                print(f"  progress {i+1}/{len(todo)} ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"DONE ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
