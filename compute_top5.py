# -*- coding: utf-8 -*-
"""
每日最强5股计算（综合强度评分 v2 防追高版）
基于回测诊断的修正（2026-08-23）:
  原版"当日表现"对涨幅6~9%给2分、>9%给0分——回测显示当日大涨(9%+)的票
  T+10中位-1.96%(胜率44.5%)明显差于当日0~6%的票(中位约-0.6%)。
  v2 改为: 涨幅0~3%→4, 3~6%→3, 6~9%→1, >9%→-2(追高惩罚), <0→0
评分公式（满分约100）:
  信号数分: min(sig_n, 8) * 5            -> 最高 40
  类别数分: cat_n * 4                    -> 最高 24
  趋势分:   站上年线+6, 多头排列+4        -> 最高 10
  动量分:   动量类信号数*3(封顶12)        -> 最高 12
  量价分:   量价类信号数*3(封顶12)        -> 最高 12
  当日表现: 0~3%→4, 3~6%→3, 6~9%→1, >9%→-2, <0→0
输出: data/out/top5_2026.json {date: [top5条目]}
每条: {sym,name,date,close,pct,sig_n,cat_n,score,bd:{...},sigs:[中文名]}
"""
import json
import glob
import os

CAT_PREFIX = {"t_": "趋势", "m_": "动量", "v_": "量价",
              "k_": "K线形态", "p_": "图表形态", "a_": "辅助"}

def cat_of(code):
    for k, v in CAT_PREFIX.items():
        if code.startswith(k):
            return v
    return "其他"

def score_stock(sigs, pct):
    sig_n = len(sigs)
    cats = set(cat_of(s) for s in sigs)
    cat_n = len(cats)
    has_year = "t_above_year" in sigs
    has_bull = "t_bull_arrange" in sigs
    mom_n = sum(1 for s in sigs if cat_of(s) == "动量")
    vol_n = sum(1 for s in sigs if cat_of(s) == "量价")
    s_sig = min(sig_n, 8) * 5
    s_cat = cat_n * 4
    s_trend = (6 if has_year else 0) + (4 if has_bull else 0)
    s_mom = min(mom_n, 4) * 3
    s_vol = min(vol_n, 4) * 3
    if pct is not None:
        if 0 <= pct < 3:   s_day = 4
        elif 3 <= pct < 6: s_day = 3
        elif 6 <= pct < 9: s_day = 1
        elif pct >= 9:     s_day = -2   # 追高惩罚
        else:              s_day = 0
    else:
        s_day = 0
    score = s_sig + s_cat + s_trend + s_mom + s_vol + s_day
    bd = {"信号": s_sig, "类别": s_cat, "趋势": s_trend,
          "动量": s_mom, "量价": s_vol, "当日": s_day, "合计": score}
    return score, bd

def load_daily_price():
    """sym -> {date: (close, pct)} 当日收盘与涨跌幅"""
    dmap = {}
    files = glob.glob("data/kline/*.json")
    for fp in files:
        sym = os.path.basename(fp)[:-5]
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        bars = d["bars"]
        m = {}
        for i, b in enumerate(bars):
            close = float(b[2])
            if i > 0:
                prev = float(bars[i-1][2])
                pct = (close - prev) / prev * 100 if prev else None
            else:
                pct = None
            m[b[0]] = (close, pct)
        dmap[sym] = m
    return dmap

def main():
    sig = json.load(open("data/out/signals_2026.json"))
    trend = json.load(open("data/out/trend_2026.json"))
    meta = json.load(open("data/out/meta.json"))
    catmap = json.load(open("data/out/signal_cat.json"))
    names = catmap["name"]
    code_list = list(catmap["name"].keys())
    dmap = load_daily_price()
    print("price maps:", len(dmap))

    out = {}
    for date, day in sig.items():
        td_ = trend.get(date, {})
        scored = []
        for sym, sigval in day.items():
            # 剔除下跌趋势
            if td_.get(sym) == 1:
                continue
            codes = sigval if isinstance(sigval, list) else sigval.split(",")
            close, pct = (dmap.get(sym, {}).get(date) or (None, None))
            score, bd = score_stock(codes, pct)
            scored.append({
                "sym": sym,
                "name": meta.get(sym, {}).get("name", ""),
                "date": date,
                "close": round(close, 2) if close else None,
                "pct": round(pct, 2) if pct is not None else None,
                "sig_n": len(codes),
                "cat_n": len(set(cat_of(c) for c in codes)),
                "score": score,
                "bd": bd,
                "sigs": [names.get(c, c) for c in codes],
            })
        scored.sort(key=lambda x: -x["score"])
        out[date] = scored[:10]   # 预存10只, 网页端可按maxPct动态再筛

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/top5_2026.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    last = sorted(out.keys())[-1]
    print(f"days={len(out)} latest={last}")
    for i, s in enumerate(out[last][:5], 1):
        print(f"  #{i} {s['sym']} {s['name']} 收盘{s['close']} 涨{s['pct']}% "
              f"信号{s['sig_n']} 类{s['cat_n']} 分{s['score']}")
        print(f"     信号: {s['sigs']}")
    print("DONE")

if __name__ == "__main__":
    main()
