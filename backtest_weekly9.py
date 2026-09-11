# -*- coding: utf-8 -*-
"""
周线红9信号后6周走势回测
- 对每只股票构建完整周K线序列（每周最后交易日为该周收盘）
- 计算周线TD计数，标记红9(==9)信号周
- 信号周收盘为基准(1.0)，统计其后6周（T1~T6）的收盘相对走势
- 输出: data/out/bt_weekly9.json (聚合统计 + 原始样本)
"""
import json
import glob
import os
from datetime import datetime
from statistics import mean, median

from td9 import td_sequence, week_key

LOOKAHEAD = 6

def load_weekly(symbol):
    """返回 (week_dates, week_closes) 完整周序列"""
    with open(f"data/kline/{symbol}.json", encoding="utf-8") as f:
        d = json.load(f)
    bars = d["bars"]
    wkeys, wcloses, wlast = [], [], []
    cur = None
    for b in bars:
        dt = datetime.strptime(b[0], "%Y-%m-%d").date()
        close = float(b[2])
        wk = week_key(dt)
        if wk != cur:
            wkeys.append(wk); wcloses.append(close); wlast.append(dt); cur = wk
        else:
            wcloses[-1] = close
            wlast[-1] = dt
    return wkeys, wcloses, wlast

def main():
    files = glob.glob("data/kline/*.json")
    print("stocks:", len(files))

    samples = []  # {sym, signal_date, base_close, path:[1.0, r1..r6], pct:[0,..], year}
    n_checked = 0
    n_signals = 0

    for fp in files:
        sym = os.path.basename(fp)[:-5]
        try:
            wkeys, wcloses, wlast = load_weekly(sym)
        except Exception:
            continue
        if len(wcloses) < 12:
            continue
        n_checked += 1
        cnt = td_sequence(wcloses)
        # 信号周: cnt==9 且其后至少有 LOOKAHEAD 个完整周
        for i, c in enumerate(cnt):
            if c == 9 and i + LOOKAHEAD < len(wcloses):
                base = wcloses[i]
                if base <= 0:
                    continue
                path = [1.0]
                for k in range(1, LOOKAHEAD + 1):
                    path.append(round(wcloses[i + k] / base, 6))
                pct = [round((v - 1) * 100, 2) for v in path]
                samples.append({
                    "sym": sym,
                    "date": wlast[i].isoformat(),     # 信号周最后交易日(确认日)
                    "base_close": round(base, 3),
                    "path": path,
                    "pct": pct,
                    "year": wlast[i].year,
                })
                n_signals += 1

    print(f"checked={n_checked} signals={n_signals}")

    # ---- 聚合统计 ----
    agg = {"mean": [], "median": [], "p25": [], "p75": [], "win_rate": [], "n": len(samples)}
    # T1..T6
    for k in range(1, LOOKAHEAD + 1):
        vals = [s["path"][k] for s in samples]
        vals_sorted = sorted(vals)
        agg["mean"].append(round(mean(vals), 4))
        agg["median"].append(round(median(vals), 4))
        agg["p25"].append(round(vals_sorted[int(len(vals) * 0.25)], 4))
        agg["p75"].append(round(vals_sorted[int(len(vals) * 0.75)], 4))
        wins = sum(1 for v in vals if v > 1.0)
        agg["win_rate"].append(round(wins / len(vals) * 100, 1))

    # ---- 按年份分组 ----
    by_year = {}
    for s in samples:
        y = s["year"]
        by_year.setdefault(y, {"n": 0, "paths": []})
        by_year[y]["n"] += 1
        by_year[y]["paths"].append(s["path"])
    year_stat = {}
    for y, g in by_year.items():
        arr = list(zip(*g["paths"]))  # arr[0]=T0, arr[1]=T1...
        year_stat[str(y)] = {
            "n": g["n"],
            "t6_mean": round(mean(arr[6]) * 100 - 100, 2) if len(arr[6]) else None,
            "t6_median": round(median(arr[6]) * 100 - 100, 2) if len(arr[6]) else None,
        }

    # ---- 分月信号数量 ----
    month_cnt = {}
    for s in samples:
        mk = s["date"][:7]
        month_cnt[mk] = month_cnt.get(mk, 0) + 1

    result = {
        "lookahead": LOOKAHEAD,
        "range": {"start": min(s["date"] for s in samples), "end": max(s["date"] for s in samples)},
        "samples": len(samples),
        "agg": agg,
        "by_year": year_stat,
        "month_cnt": dict(sorted(month_cnt.items())),
        "top_drop": sorted(
            [{"date": s["date"], "sym": s["sym"], "t6": round((s["path"][6]-1)*100, 1)}
             for s in samples], key=lambda x: x["t6"])[:10],
        "top_gain": sorted(
            [{"date": s["date"], "sym": s["sym"], "t6": round((s["path"][6]-1)*100, 1)}
             for s in samples], key=lambda x: -x["t6"])[:10],
    }

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/bt_weekly9.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    # 打印摘要
    print("range:", result["range"])
    print("agg:", json.dumps(agg, ensure_ascii=False))
    print("by_year:", json.dumps(year_stat, ensure_ascii=False))
    print("month_cnt sample:", dict(list(result["month_cnt"].items())[:6]))
    print("DONE")

if __name__ == "__main__":
    main()
