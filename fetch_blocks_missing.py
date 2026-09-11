# -*- coding: utf-8 -*-
"""补抓 stock_blocks.json 中缺失的个股板块（东财接口），与既有数据合并写回。
只处理缺失 symbol，避免打扰已有数据。用法: python3 fetch_blocks_missing.py
"""
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = os.path.join("data", "out", "stock_blocks.json")


def fetch_blocks(secid, sym):
    """东方财富: 个股所属板块(行业层级+概念)"""
    u = (f"https://push2.eastmoney.com/api/qt/slist/get?secid={secid}"
         f"&spt=3&fields=f12,f14&po=1&pn=1&pz=50")
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            diff = ((d.get("data") or {}).get("diff") or {})
            blocks = [v.get("f14", "") for v in diff.values() if v.get("f14")]
            return sym, blocks
        except Exception:
            time.sleep(0.8 + a * 1.0)
    return sym, None


def secid_of(sym):
    mkt, code = sym[:2], sym[2:]
    return ("1." if mkt == "sh" else "0.") + code


def main():
    blocks = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    with open("data/stock_list.json", encoding="utf-8") as f:
        sl = json.load(f)["stocks"]
    syms = [s["symbol"] for s in sl]
    missing = [s for s in syms if s not in blocks]
    print(f"既有 {len(blocks)} 只, 全市场 {len(syms)} 只, 缺失 {len(missing)} 只")

    added = {}
    n_ok = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        for k, (sym, blk) in enumerate(ex.map(
                lambda s: fetch_blocks(secid_of(s), s), missing, chunksize=12)):
            if blk:
                added[sym] = blk
                n_ok += 1
            if (k + 1) % 200 == 0:
                print(f"  {k+1}/{len(missing)} ok={n_ok}", flush=True)
    blocks.update(added)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False)
    print(f"补抓完成: 本次新增 {len(added)} 只, 仍缺 {len(missing) - n_ok} 只, 总 {len(blocks)} 只")


if __name__ == "__main__":
    main()
