# -*- coding: utf-8 -*-
"""
共振信号后短期收益回测（验证"追高"问题）
- 信号日 T0: 当日收盘触发信号
- 收益: 信号日收盘买入, T+N 收盘卖出 (N=5,10,20)
分组:
  1) 总体所有共振信号
  2) 按信号数档位 (3,4,5,6+)
  3) 按类别 (信号类别组合)
  4) 按当日涨幅分桶 (验证追高: 当日大涨的信号后市如何)
  5) 单信号后效 (每个信号码独立统计)
输出: data/out/bt_signal_short.json
"""
import json
import glob
import os
from statistics import mean, median

def load_price_map():
    """sym -> {date: close}"""
    dmap = {}
    files = glob.glob("data/kline/*.json")
    for fp in files:
        sym = os.path.basename(fp)[:-5]
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        dmap[sym] = {b[0]: float(b[2]) for b in d["bars"]}
    return dmap

def stats(vals):
    if not vals:
        return None
    n = len(vals)
    return {
        "n": n,
        "mean": round(mean(vals) * 100, 2),
        "median": round(median(vals) * 100, 2),
        "win": round(sum(1 for v in vals if v > 0) / n * 100, 1),
        "p25": round(sorted(vals)[int(n*0.25)] * 100, 2),
        "p75": round(sorted(vals)[int(n*0.75)] * 100, 2),
    }

CAT = {"t_": "趋势", "m_": "动量", "v_": "量价",
       "k_": "K线", "p_": "形态", "a_": "辅助"}

def cat_of(code):
    for k, v in CAT.items():
        if code.startswith(k):
            return v
    return "其他"

def main():
    sig = json.load(open("data/out/signals_2026.json"))
    pmap = load_price_map()
    print("price maps:", len(pmap))

    HORIZONS = [5, 10, 20]
    total = {h: [] for h in HORIZONS}
    by_sig_n = {}
    by_pct_bucket = {
        "<0": {h: [] for h in HORIZONS}, "0-3": {h: [] for h in HORIZONS},
        "3-6": {h: [] for h in HORIZONS}, "6-9": {h: [] for h in HORIZONS},
        "9+": {h: [] for h in HORIZONS},
    }
    by_cat = {c: {h: [] for h in HORIZONS} for c in set(CAT.values())}
    per_signal = {}   # code -> {h: [rets]}

    dates_sorted = sorted(sig.keys())
    for date in dates_sorted:
        for sym, codes in sig[date].items():
            closes = pmap.get(sym, {})
            c0 = closes.get(date)
            if c0 is None or c0 <= 0:
                continue
            # 找 T+N 收盘价
            idx_dates = sorted(closes.keys())
            try:
                i0 = idx_dates.index(date)
            except ValueError:
                continue
            rets = {}
            for h in HORIZONS:
                if i0 + h < len(idx_dates):
                    cN = closes[idx_dates[i0 + h]]
                    rets[h] = cN / c0 - 1.0
            if not rets:
                continue
            n_sig = len(codes)
            cats = set(cat_of(c) for c in codes)

            for h, r in rets.items():
                total[h].append(r)
                key_n = n_sig if n_sig <= 6 else "7+"
                by_sig_n.setdefault(key_n, {h: [] for h in HORIZONS})[h].append(r)
                # 当日涨幅分桶
                prev = closes.get(date)  # 近似: 用当日相对前日
                # 计算当日涨幅
                if i0 > 0:
                    c_prev = closes[idx_dates[i0-1]]
                    pct = (c0 - c_prev) / c_prev * 100
                    if pct < 0: bucket = "<0"
                    elif pct < 3: bucket = "0-3"
                    elif pct < 6: bucket = "3-6"
                    elif pct < 9: bucket = "6-9"
                    else: bucket = "9+"
                    by_pct_bucket[bucket][h].append(r)
                for c in cats:
                    by_cat[c][h].append(r)
                for code in set(codes):
                    per_signal.setdefault(code, {h: [] for h in HORIZONS})[h].append(r)

    result = {
        "horizons": HORIZONS,
        "total": {str(h): stats(total[h]) for h in HORIZONS},
        "by_sig_n": {str(k): {str(h): stats(v[h]) for h in HORIZONS} for k, v in by_sig_n.items()},
        "by_pct_bucket": {k: {str(h): stats(v[h]) for h in HORIZONS} for k, v in by_pct_bucket.items()},
        "by_cat": {k: {str(h): stats(v[h]) for h in HORIZONS} for k, v in by_cat.items()},
        "per_signal": {code: {str(h): stats(v[h]) for h in HORIZONS} for code, v in per_signal.items()},
    }

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/bt_signal_short.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    # 打印摘要
    print("\n=== 总体 ===")
    for h in HORIZONS:
        s = result["total"][str(h)]
        print(f"T+{h}: n={s['n']} mean={s['mean']}% med={s['median']}% win={s['win']}%")
    print("\n=== 按当日涨幅分桶 (验证追高) ===")
    for b in ["<0", "0-3", "3-6", "6-9", "9+"]:
        s = result["by_pct_bucket"][b]["10"]
        print(f"当日{b}%: n={s['n']} T+10 mean={s['mean']}% med={s['median']}% win={s['win']}%")
    print("\n=== 单信号 T+10 后效 TOP10 / BOTTOM10 ===")
    per = sorted(result["per_signal"].items(), key=lambda x: (x[1]["10"] or {}).get("median", -99))
    for code, v in per[:10]:
        s = v["10"]
        print(f"  {code}: med={s['median']}% win={s['win']}% n={s['n']}")
    print("---")
    for code, v in per[-10:][::-1]:
        s = v["10"]
        print(f"  {code}: med={s['median']}% win={s['win']}% n={s['n']}")
    print("DONE")

if __name__ == "__main__":
    main()
