# -*- coding: utf-8 -*-
"""抓取A股全市场个股所属板块（东方财富接口），输出 data/out/stock_blocks.json
结构: {sym: {"industry": "白酒", "concepts": ["白酒概念","贵州板块",...]}}
"""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

def fetch_blocks(secid, sym):
    """东方财富: 个股所属板块(行业+概念)"""
    u = (f"https://push2.eastmoney.com/api/qt/slist/get?secid={secid}"
         f"&spt=3&fields=f12,f14&po=1&pn=1&pz=50")
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode("utf-8"))
        diff = ((d.get("data") or {}).get("diff") or {})
        blocks = [v.get("f14", "") for v in diff.values() if v.get("f14")]
        # 行业: 优先取含"板块"之外的行业名, 东方财富行业板块是 f14 里的行业名
        return sym, blocks
    except Exception:
        return sym, None

def secid_of(sym):
    """sh600519 -> 1.600519, sz000001 -> 0.000001"""
    mkt, code = sym[:2], sym[2:]
    return ("1." if mkt == "sh" else "0.") + code

def main():
    with open("data/stock_list.json", encoding="utf-8") as f:
        sl = json.load(f)["stocks"]
    syms = [s["symbol"] for s in sl]
    print("stocks:", len(syms))

    blocks = {}
    n_ok = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for k, (sym, blk) in enumerate(ex.map(
                lambda s: fetch_blocks(secid_of(s), s), syms, chunksize=16)):
            if blk:
                blocks[sym] = blk
                n_ok += 1
            if (k + 1) % 500 == 0:
                print(f"  {k+1}/{len(syms)} ok={n_ok}", flush=True)
            time.sleep(0.02)

    import os
    os.makedirs("data/out", exist_ok=True)
    with open("data/out/stock_blocks.json", "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False)
    print(f"OK total={len(blocks)}")

if __name__ == "__main__":
    main()
