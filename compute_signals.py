# -*- coding: utf-8 -*-
"""
全市场六类技术信号共振计算
对每只股票、每个2026交易日计算触发信号，按日期聚合:
  {date: {sym: {"n": 信号总数, "cats": 类别数, "s": [信号代码...]}}}
同时输出每股最近交易日信号(供无日期筛选时用)
输出: data/out/signals_2026.json  {date: {sym: [codes]}}
      data/out/signal_meta.json  {sym: [name, last_close, last_pct]}
"""
import json
import glob
import os
import sys
import time
import numpy as np
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from signals import SignalEngine

YEAR = "2026"

# 信号类别映射
CAT = {
    "t_": "趋势", "m_": "动量", "v_": "量价",
    "k_": "K线形态", "p_": "图表形态", "a_": "辅助",
}
# 信号中文名
SIG_NAME = {
    "t_ma_golden": "MA金叉(5上穿20)", "t_above_year": "站上年线", "t_bull_arrange": "均线多头排列",
    "t_support20": "回踩MA20支撑", "t_macd_golden": "MACD金叉", "t_macd_red": "MACD红柱",
    "t_macd_div": "MACD底背离", "t_dmi_golden": "DMI金叉(+DI穿-DI)", "t_trix_golden": "TRIX金叉",
    "m_rsi_oversold": "RSI超卖(<30)", "m_rsi_golden": "RSI金叉(6穿12)", "m_rsi_div": "RSI底背离",
    "m_kdj_golden": "KDJ金叉", "m_kdj_low_golden": "KDJ低位金叉(<20)", "m_kdj_j_neg": "J值<0",
    "m_cci_break": "CCI上穿+100", "m_cci_oversold_break": "CCI上穿-100", "m_roc_neg": "ROC<0",
    "m_wr_rebound": "W%R超卖反转",
    "v_vol_price_up": "量增价升", "v_bottom_volume": "底部放量", "v_shrink_pullback": "缩量回调",
    "v_vol_flat": "量增价平", "v_obv_div": "OBV底背离",
    "k_hammer": "锤子线", "k_inv_hammer": "倒锤子线", "k_big_yang": "大阳线",
    "k_engulf": "看涨吞没", "k_pierce": "曙光初现", "k_three_soldiers": "多方炮",
    "k_rising_three": "上升三法",
    "p_double_bottom": "双底突破", "p_breakout": "平台突破", "p_support60": "回踩MA60回升",
    "a_boll_rebound": "BOLL下轨反弹", "a_bias_neg": "BIAS负偏离(<-8%)", "a_emv_pos": "EMV≥0",
    "a_brar_low": "BRAR低位", "a_vr_low": "VR<40", "a_psy_low": "PSY低位",
}

def process_stock(fp):
    sym = os.path.basename(fp)[:-5]
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        bars = d["bars"]
        if len(bars) < 60:
            return sym, None
        o = np.array([float(b[1]) for b in bars])
        c = np.array([float(b[2]) for b in bars])
        h = np.array([float(b[3]) for b in bars])
        l = np.array([float(b[4]) for b in bars])
        v = np.array([float(b[5]) for b in bars])
        dates = [b[0] for b in bars]
        eng = SignalEngine(o, h, l, c, v)
        out = {}
        trend = {}
        for i in range(len(c)):
            if dates[i].startswith(YEAR):
                s = eng.signals_at(i)
                if s:
                    out[dates[i]] = s
                trend[dates[i]] = 1 if eng.is_downtrend(i) else 0
        return sym, (out, trend)
    except Exception as e:
        return sym, None

def main():
    files = glob.glob("data/kline/*.json")
    print("stocks:", len(files), flush=True)
    t0 = time.time()

    # 多进程计算
    results = {}
    trends = {}
    n_ok = 0
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        for k, (sym, out) in enumerate(ex.map(process_stock, files, chunksize=20)):
            if out:
                results[sym] = out[0]
                trends[sym] = out[1]
                n_ok += 1
            if (k + 1) % 500 == 0:
                print(f"  {k+1}/{len(files)} ok={n_ok} elapsed={time.time()-t0:.0f}s", flush=True)
    print(f"computed ok={n_ok} elapsed={time.time()-t0:.0f}s", flush=True)

    # 按日期聚合
    by_date = {}
    trend_by_date = {}
    for sym, dmap in results.items():
        for date, sigs in dmap.items():
            by_date.setdefault(date, {})[sym] = sigs
    for sym, tmap in trends.items():
        for date, flag in tmap.items():
            trend_by_date.setdefault(date, {})[sym] = flag

    os.makedirs("data/out", exist_ok=True)
    with open("data/out/signals_2026.json", "w", encoding="utf-8") as f:
        json.dump(by_date, f, ensure_ascii=False)
    with open("data/out/trend_2026.json", "w", encoding="utf-8") as f:
        json.dump(trend_by_date, f, ensure_ascii=False)
    print(f"dates={len(by_date)}", flush=True)
    # 保存信号映射
    with open("data/out/signal_cat.json", "w", encoding="utf-8") as f:
        json.dump({"cat": CAT, "name": SIG_NAME}, f, ensure_ascii=False)
    print("DONE")

if __name__ == "__main__":
    main()
