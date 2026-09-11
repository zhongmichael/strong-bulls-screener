# -*- coding: utf-8 -*-
"""计算全市场最新收盘价的 MA120(半年线) / MA250(年线)，更新 meta.json"""
import json
import glob
import os
from datetime import datetime

def compute_ma(symbol):
    """返回 (last_close, ma120, ma250, n)"""
    with open(f"data/kline/{symbol}.json", encoding="utf-8") as f:
        d = json.load(f)
    bars = d["bars"]
    closes = [float(b[2]) for b in bars]
    n = len(closes)
    if n == 0:
        return None, None, None, n
    last_close = closes[-1]
    ma120 = sum(closes[-120:]) / min(120, n) if n >= 1 else None
    ma250 = sum(closes[-250:]) / min(250, n) if n >= 1 else None
    return last_close, ma120, ma250, n

def main():
    with open("data/out/meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    files = glob.glob("data/kline/*.json")
    updated = 0
    for fp in files:
        sym = os.path.basename(fp)[:-5]
        if sym not in meta:
            continue
        last_close, ma120, ma250, n = compute_ma(sym)
        m = meta[sym]
        m["ma120"] = round(ma120, 3) if ma120 else None
        m["ma250"] = round(ma250, 3) if ma250 else None
        m["kline_n"] = n
        # 站上判定（股价 > 均线；数据不足120/250根时按可用均线计算但标注不足）
        m["above_ma120"] = (last_close > ma120) if ma120 else None
        m["above_ma250"] = (last_close > ma250) if ma250 else None
        m["ma120_ok"] = n >= 120   # 是否有足够数据计算真实半年线
        m["ma250_ok"] = n >= 250   # 是否有足够数据计算真实年线
        updated += 1
    with open("data/out/meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"updated={updated} total_meta={len(meta)}")

if __name__ == "__main__":
    main()
