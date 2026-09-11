# -*- coding: utf-8 -*-
"""
全市场神奇九转红9计算
对每只股票计算:
  - 日线红9: 触发日索引
  - 周线红9: 按"截至查询日"动态聚合(部分周)判断本周K线计数==9
  - 月线红9: 按"截至查询日"动态聚合(部分月)判断本月K线计数==9
输出:
  data/daily_red9.json   {date: [symbol,...]}
  data/weekly_red9.json  {date: [symbol,...]}  键为2026年内交易日,值=截至该日本周周线红9
  data/monthly_red9.json {date: [symbol,...]}
  data/meta.json         {symbol: {name, last_close, last_date, last_pct}}
"""
import json
import glob
import os
from datetime import date, datetime
from td9 import (td_sequence, next_count, week_key, month_key)

YEAR = 2026

def parse_bars(symbol):
    with open(f"data/kline/{symbol}.json", encoding="utf-8") as f:
        d = json.load(f)
    bars = d["bars"]
    dates, opens, closes, highs, lows = [], [], [], [], []
    for b in bars:
        dt = datetime.strptime(b[0], "%Y-%m-%d").date()
        dates.append(dt)
        opens.append(float(b[1]))
        closes.append(float(b[2]))
        highs.append(float(b[3]))
        lows.append(float(b[4]))
    return dates, opens, closes, highs, lows

def build_grouped(dates, opens, closes, highs, lows, key_fn):
    """按 key_fn(日期)->key 分组聚合, 返回 (keys, closes, highs, lows, last_dates)
    每组取最后一天作为代表日期"""
    groups = {}
    order = []
    for i, d in enumerate(dates):
        k = key_fn(d)
        if k not in groups:
            groups[k] = {"o": opens[i], "h": highs[i], "l": lows[i],
                         "c": closes[i], "last": d}
            order.append(k)
        else:
            g = groups[k]
            g["h"] = max(g["h"], highs[i])
            g["l"] = min(g["l"], lows[i])
            g["c"] = closes[i]
            g["last"] = d
    gcloses = [groups[k]["c"] for k in order]
    ghighs = [groups[k]["h"] for k in order]
    glows = [groups[k]["l"] for k in order]
    glast = [groups[k]["last"] for k in order]
    return order, gcloses, ghighs, glows, glast

def incremental_last_cnt(prev_cnt, partial_close, full_closes, idx):
    """计算将第idx根替换为部分K线(partial_close)后的计数
    prev_cnt: 第idx-1根的计数; full_closes: 完整序列收盘; idx>=4"""
    if idx < 4:
        return None
    return next_count(prev_cnt, partial_close, full_closes[idx - 4])

def main():
    symbols = [os.path.basename(p)[:-5] for p in glob.glob("data/kline/*.json")]
    print("stocks:", len(symbols))

    daily_red9 = {}      # date -> [sym]
    weekly_red9 = {}     # date -> [sym]
    monthly_red9 = {}    # date -> [sym]
    meta = {}

    # 交易日序列(全市场并集)
    all_dates = set()
    for sym in symbols:
        try:
            dates, *_ = parse_bars(sym)
            all_dates.update(d for d in dates if d.year == YEAR)
        except Exception:
            continue
    trade_dates = sorted(all_dates)
    print("trade days:", len(trade_dates), trade_dates[0], "->", trade_dates[-1])

    for n, sym in enumerate(symbols):
        try:
            dates, opens, closes, highs, lows = parse_bars(sym)
        except Exception as e:
            print(f"  skip {sym}: {e}")
            continue
        if len(closes) < 10:
            continue
        if trade_dates is None:
            trade_dates = [d for d in dates if d.year == YEAR]
        else:
            pass

        # 日线红9
        d_cnt = td_sequence(closes)
        daily_rd = [dates[i].isoformat() for i, c in enumerate(d_cnt)
                    if c == 9 and dates[i].year == YEAR]
        for dstr in daily_rd:
            daily_red9.setdefault(dstr, []).append(sym)

        # 周/月完整序列
        wkeys, wcloses, whighs, wlows, wlast = build_grouped(
            dates, opens, closes, highs, lows, week_key)
        mkeys, mcloses, mhighs, mlows, mlast = build_grouped(
            dates, opens, closes, highs, lows, month_key)
        w_cnt = td_sequence(wcloses)
        m_cnt = td_sequence(mcloses)
        w_idx = {k: i for i, k in enumerate(wkeys)}
        m_idx = {k: i for i, k in enumerate(mkeys)}
        d_idx = {d.isoformat(): j for j, d in enumerate(dates)}

        # 对2026年每个交易日, 计算截至该日的周/月红9
        for j, d in enumerate(dates):
            if d.year != YEAR:
                continue
            dstr = d.isoformat()
            wk = week_key(d)
            mk = month_key(d)
            # ---- 周线: 本周K线计数（截至d的部分周收盘=d当日收盘）----
            wi = w_idx.get(wk)
            if wi is not None:
                if wi == len(wkeys) - 1 and d >= wlast[wi]:
                    cnt_week = w_cnt[wi]
                else:
                    if wi >= 4:
                        cnt_week = next_count(w_cnt[wi - 1], closes[j], wcloses[wi - 4])
                    else:
                        cnt_week = None
                if cnt_week == 9:
                    weekly_red9.setdefault(dstr, []).append(sym)
            # ---- 月线 ----
            mi = m_idx.get(mk)
            if mi is not None:
                if mi == len(mkeys) - 1 and d >= mlast[mi]:
                    cnt_month = m_cnt[mi]
                else:
                    if mi >= 4:
                        cnt_month = next_count(m_cnt[mi - 1], closes[j], mcloses[mi - 4])
                    else:
                        cnt_month = None
                if cnt_month == 9:
                    monthly_red9.setdefault(dstr, []).append(sym)

        # meta
        last_i = len(closes) - 1
        last_close = closes[last_i]
        prev_close = closes[last_i - 1] if last_i >= 1 else last_close
        pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0
        meta[sym] = {"name": "", "last_close": round(last_close, 2),
                     "last_date": dates[last_i].isoformat(),
                     "last_pct": round(pct, 2)}

        if (n + 1) % 500 == 0:
            print(f"  progress {n+1}/{len(symbols)}")

    # 补股票名称
    with open("data/stock_list.json", encoding="utf-8") as f:
        sl = json.load(f)["stocks"]
    for s in sl:
        if s["symbol"] in meta:
            meta[s["symbol"]]["name"] = s["name"]

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/daily_red9.json", "w") as f:
        json.dump(daily_red9, f)
    with open("data/out/weekly_red9.json", "w") as f:
        json.dump(weekly_red9, f)
    with open("data/out/monthly_red9.json", "w") as f:
        json.dump(monthly_red9, f)
    with open("data/out/meta.json", "w") as f:
        json.dump(meta, f, ensure_ascii=False)

    # 交易日序列
    with open("data/out/trade_dates.json", "w") as f:
        json.dump([d.isoformat() for d in trade_dates], f)

    print(f"daily days={len(daily_red9)} weekly days={len(weekly_red9)} monthly days={len(monthly_red9)}")
    print("sample daily:", list(daily_red9.items())[:3] if daily_red9 else "none")
    print("sample weekly:", list(weekly_red9.items())[:3] if weekly_red9 else "none")
    print("sample monthly:", list(monthly_red9.items())[:3] if monthly_red9 else "none")
    print("DONE")

if __name__ == "__main__":
    main()
