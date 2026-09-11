# -*- coding: utf-8 -*-
"""
红9触发日动态均线判断（覆盖日/周/月线三类红9）
对每只股票构建 日期->(close, ma120, ma250) 映射，
对 daily/weekly/monthly 红9的每个 (date, sym) 触发对记录:
  [close, ma120, ma250, above120(收盘>MA120), above250(收盘>MA250)]
输出: data/out/trigger_ma.json  {date: {sym: [close, ma120, ma250, above120, above250]}}
"""
import json
import glob
import os

def rolling_ma(closes, n):
    """O(n) 滚动均值: 第i天 = 最近n天收盘均值; 不足n根用已有均值"""
    s = [0.0] * (len(closes) + 1)
    for i, c in enumerate(closes):
        s[i + 1] = s[i] + c
    out = []
    for i in range(len(closes)):
        if i + 1 < n:
            out.append(s[i + 1] / (i + 1))
        else:
            out.append((s[i + 1] - s[i + 1 - n]) / n)
    return out

def main():
    files = glob.glob("data/kline/*.json")
    print("stocks:", len(files))

    # 预加载每只股票的 日期->(close, ma120, ma250)
    daily_ma = {}  # sym -> {date: (close, ma120, ma250)}
    for fp in files:
        sym = os.path.basename(fp)[:-5]
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        bars = d["bars"]
        if len(bars) < 20:
            continue
        dates = [b[0] for b in bars]
        closes = [float(b[2]) for b in bars]
        ma120 = rolling_ma(closes, 120)
        ma250 = rolling_ma(closes, 250)
        daily_ma[sym] = {dates[i]: (closes[i], ma120[i], ma250[i])
                         for i in range(len(dates))}

    print("loaded daily_ma:", len(daily_ma))

    # 三类红9的触发对
    trigger_ma = {}
    for key in ["daily_red9", "weekly_red9", "monthly_red9"]:
        with open(f"data/out/{key}.json", encoding="utf-8") as f:
            red9 = json.load(f)
        cnt = 0
        for dstr, syms in red9.items():
            for sym in syms:
                rec = daily_ma.get(sym, {}).get(dstr)
                if rec is None:
                    continue
                close, ma120, ma250 = rec
                trigger_ma.setdefault(dstr, {})[sym] = [
                    round(close, 3), round(ma120, 3), round(ma250, 3),
                    close > ma120, close > ma250,
                ]
                cnt += 1
        print(f"  {key}: pairs={cnt}")

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/trigger_ma.json", "w", encoding="utf-8") as f:
        json.dump(trigger_ma, f, ensure_ascii=False)
    print("trigger days:", len(trigger_ma))
    print("DONE")

if __name__ == "__main__":
    main()
