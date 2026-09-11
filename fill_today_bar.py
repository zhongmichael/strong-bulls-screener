# -*- coding: utf-8 -*-
"""
用实时行情(qt.gtimg.cn)补全当日K线bar (镜像K线接口同步延迟时使用)
条件: 昨收衔接一致(qfq链完整) 且 成交量>0(当日有交易) 且 行情时间戳为当日
输出: 补全后的 data/kline/*.json, 打印统计
"""
import json
import glob
import os
import sys
import time
import urllib.request
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
KLINE_DIR = os.path.join(BASE, "data", "kline")
# 目标日期可由命令行或环境变量指定, 默认取系统当天(供每日自动化使用)
TODAY = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("TD9_TODAY") or date.today().isoformat()
TS_PREFIX = TODAY.replace("-", "")

def fetch_qt(symbols):
    """批量拉取实时行情, 返回 {sym: parts[]}"""
    out = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i+50]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": "https://gu.qq.com/"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode("gbk", errors="ignore")
            for line in raw.strip().split(";"):
                if "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 35:
                    continue
                sym = parts[0].split("=")[0].replace("v_", "").strip()
                if sym in symbols:
                    out[sym] = parts
        except Exception as e:
            print("  qt batch err:", str(e)[:80], flush=True)
        time.sleep(0.15)
    return out

def main():
    files = glob.glob(os.path.join(KLINE_DIR, "*.json"))
    missing = []          # (sym, fp, bars, last_close)
    for fp in files:
        sym = os.path.basename(fp)[:-5]
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            bars = d.get("bars") or []
            if not bars or bars[-1][0] < TODAY:
                last_close = float(bars[-1][2]) if bars else None
                missing.append((sym, fp, bars, last_close))
        except Exception:
            pass
    print("total files:", len(files), "| need today bar:", len(missing), flush=True)

    syms = [m[0] for m in missing]
    qt = fetch_qt(syms)
    print("qt quotes fetched:", len(qt), flush=True)

    appended = 0
    suspended = 0       # 成交量0 → 停牌/无成交
    ts_mismatch = 0     # 时间戳非当日 → 停牌
    prev_mismatch = 0   # 昨收衔接不一致 → 除权除息/数据异常, 跳过
    no_quote = 0
    examples = []
    for sym, fp, bars, last_close in missing:
        parts = qt.get(sym)
        if not parts:
            no_quote += 1
            continue
        try:
            cur = float(parts[3])
            prevc = float(parts[4])
            opn = float(parts[5])
            vol = float(parts[6])
            high = float(parts[33])
            low = float(parts[34])
            ts = parts[30] if len(parts) > 30 else ""
        except (ValueError, IndexError):
            no_quote += 1
            continue
        if vol <= 0:
            suspended += 1
            continue
        if not ts.startswith(TS_PREFIX):
            ts_mismatch += 1
            continue
        if last_close is None or abs(prevc - last_close) > 0.005:
            prev_mismatch += 1
            examples.append(sym)
            continue
        bar = [TODAY, f"{opn:.3f}", f"{cur:.3f}", f"{high:.3f}", f"{low:.3f}", f"{vol:.0f}"]
        bars.append(bar)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({"symbol": sym, "bars": bars}, f, ensure_ascii=False)
        appended += 1

    print("=" * 40)
    print(f"补全今日bar: {appended} | 停牌/无成交(vol=0): {suspended} | 时间戳非当日: {ts_mismatch} | 昨收衔接异常: {prev_mismatch} | 无行情: {no_quote}")
    if examples:
        print("昨收衔接异常样例:", examples[:20])

if __name__ == "__main__":
    main()
