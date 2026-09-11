# -*- coding: utf-8 -*-
"""
周K红9后延迟买入回测
口径:
  信号周 T0 (周线红9确认周)
  主口径: T2 周收盘买入, 持有3周(T3,T4,T5), T5 收盘卖出 -> 收益 = T5/T2 - 1
  对照口径: 买入时点 T1/T2(持有3周), 以及 T0 立即买入持有3周
统计: 均值/中位数/胜率/25/75分位/最大最小/分年/分月信号量
输出: data/out/bt_weekly9_w2.json
"""
import json
import glob
import os
from datetime import datetime
from statistics import mean, median

from td9 import td_sequence, week_key

def load_weekly(symbol):
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
            wcloses[-1] = close; wlast[-1] = dt
    return wkeys, wcloses, wlast

def pct_list(vals):
    s = sorted(vals)
    n = len(s)
    return {
        "p10": round(s[int(n*0.10)], 4),
        "p25": round(s[int(n*0.25)], 4),
        "p50": round(s[int(n*0.50)], 4),
        "p75": round(s[int(n*0.75)], 4),
        "p90": round(s[int(n*0.90)], 4),
    }

def main():
    files = glob.glob("data/kline/*.json")
    print("stocks:", len(files))

    # buy_week: 买入周相对信号周的偏移(2 = T2收盘买入)
    # hold: 持有周数, 卖出周 = buy_week + hold
    CONFIGS = {
        "t0_hold3": {"buy": 0, "hold": 3},   # T0收盘买, T3卖 (基准: 信号即买)
        "t1_hold3": {"buy": 1, "hold": 3},   # T1收盘买, T4卖
        "t2_hold3": {"buy": 2, "hold": 3},   # T2收盘买, T5卖 (主口径)
        "t2_hold2": {"buy": 2, "hold": 2},   # T2收盘买, T4卖 (持有2周)
        "t2_hold4": {"buy": 2, "hold": 4},   # T2收盘买, T6卖 (持有4周)
    }
    stat = {k: {"rets": [], "pcts": [], "samples": [], "years": {}, "months": {}} for k in CONFIGS}

    n_checked = 0
    for fp in files:
        sym = os.path.basename(fp)[:-5]
        try:
            wkeys, wcloses, wlast = load_weekly(sym)
        except Exception:
            continue
        if len(wcloses) < 14:
            continue
        n_checked += 1
        cnt = td_sequence(wcloses)
        for i, c in enumerate(cnt):
            if c != 9:
                continue
            # 需要到 T(2+4)=T6 存在
            if i + 6 >= len(wcloses):
                continue
            base = wcloses[i]
            if base <= 0:
                continue
            for cfg, spec in CONFIGS.items():
                bi = i + spec["buy"]
                si = i + spec["buy"] + spec["hold"]
                if si >= len(wcloses) or bi >= len(wcloses):
                    continue
                if wcloses[bi] <= 0:
                    continue
                ret = wcloses[si] / wcloses[bi] - 1.0
                st = stat[cfg]
                st["rets"].append(ret)
                st["pcts"].append(round(ret * 100, 2))
                yr = wlast[i].year
                st["years"].setdefault(yr, []).append(ret)
                mk = wlast[i].isoformat()[:7]
                st["months"][mk] = st["months"].get(mk, 0) + 1

    result = {}
    for cfg, st in stat.items():
        n = len(st["rets"])
        if n == 0:
            result[cfg] = {"n": 0}
            continue
        ystat = {}
        for yr, arr in sorted(st["years"].items()):
            ystat[str(yr)] = {
                "n": len(arr),
                "mean": round(mean(arr) * 100, 2),
                "median": round(median(arr) * 100, 2),
                "win": round(sum(1 for x in arr if x > 0) / len(arr) * 100, 1),
            }
        result[cfg] = {
            "n": n,
            "mean": round(mean(st["rets"]) * 100, 2),
            "median": round(median(st["rets"]) * 100, 2),
            "win": round(sum(1 for x in st["rets"] if x > 0) / n * 100, 1),
            "max": round(max(st["rets"]) * 100, 2),
            "min": round(min(st["rets"]) * 100, 2),
            "quantiles": {k: round(v * 100, 2) for k, v in pct_list(st["rets"]).items()},
            "years": ystat,
            "months": dict(sorted(st["months"].items())),
            "hist": {  # 收益分布直方图(5%档)
                str(b): sum(1 for r in st["rets"] if b <= r * 100 < b + 5)
                for b in range(-60, 61, 5)
            },
        }

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/bt_weekly9_w2.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"checked={n_checked}")
    for cfg, r in result.items():
        if r.get("n"):
            print(f"{cfg}: n={r['n']} mean={r['mean']}% med={r['median']}% win={r['win']}% "
                  f"p25={r['quantiles']['p25']}% p75={r['quantiles']['p75']}% "
                  f"min={r['min']}% max={r['max']}%")
    print("DONE")

if __name__ == "__main__":
    main()
