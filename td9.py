# -*- coding: utf-8 -*-
"""
神奇九转（TD Sequential）核心算法
红9（买入）：连续9根K线，每根收盘价 < 4根K线前的收盘价
绿9（卖出）：连续9根K线，每根收盘价 > 4根K线前的收盘价
"""
from datetime import date, timedelta


def td_sequence(closes):
    """
    输入: 升序收盘价列表（float）
    返回: 计数序列，正数=买入setup计数，负数=卖出setup计数
    """
    n = len(closes)
    cnt = [0] * n
    for i in range(4, n):
        if closes[i] < closes[i - 4]:
            cnt[i] = cnt[i - 1] + 1 if cnt[i - 1] > 0 else 1
        elif closes[i] > closes[i - 4]:
            cnt[i] = cnt[i - 1] - 1 if cnt[i - 1] < 0 else -1
        else:
            cnt[i] = 0
    return cnt


def next_count(prev_cnt, cur_close, close_minus_4):
    """增量计算最后一根K线的TD计数（用于周/月动态聚合）"""
    if cur_close < close_minus_4:
        return prev_cnt + 1 if prev_cnt > 0 else 1
    if cur_close > close_minus_4:
        return prev_cnt - 1 if prev_cnt < 0 else -1
    return 0


def find_red9(closes):
    """返回红9(==9)出现的索引列表"""
    cnt = td_sequence(closes)
    return [i for i, c in enumerate(cnt) if c == 9]


def find_green9(closes):
    cnt = td_sequence(closes)
    return [i for i, c in enumerate(cnt) if c == -9]


def aggregate_bars(dates, opens, closes, highs, lows):
    """
    按日期聚合K线（周/月）
    dates: date列表
    返回: (dates_out, closes_out, highs_out, lows_out) 每根聚合K线取最后一天日期
    """
    out_dates, out_closes, out_highs, out_lows = [], [], [], []
    for d, o, c, h, l in zip(dates, opens, closes, highs, lows):
        if out_dates and out_dates[-1] == d:
            out_closes[-1] = c
            out_highs[-1] = max(out_highs[-1], h)
            out_lows[-1] = min(out_lows[-1], l)
        else:
            out_dates.append(d)
            out_closes.append(c)
            out_highs.append(h)
            out_lows.append(l)
    return out_dates, out_closes, out_highs, out_lows


def week_key(d):
    """日期所属周的周一"""
    return d - timedelta(days=d.weekday())


def month_key(d):
    return d.replace(day=1)


# ---------- 单元验证 ----------
if __name__ == "__main__":
    # 构造一段明确满足红9的序列: 每根收盘都低于4根前
    closes = [10, 11, 12, 13, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.5]
    # i=4: 9.5<10 ->1; i=5: 9.0<11 ->2; i=6: 8.5<12 ->3; i=7: 8.0<13 ->4;
    # i=8: 7.5<9.5 ->5; i=9: 7.0<9.0 ->6; i=10: 6.5<8.5 ->7; i=11: 6.0<8.0 ->8; i=12: 5.5<7.5 ->9
    r9 = find_red9(closes)
    print("red9 idx:", r9, "expect [12]")
    assert r9 == [12], "red9 test failed"

    # 反向测试
    closes_up = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    g9 = find_green9(closes_up)
    print("green9 idx:", g9, "expect [12]")
    assert g9 == [12], "green9 test failed"

    # 中断测试: 第8根破坏连续性
    closes_brk = [10, 11, 12, 13, 9.5, 9.0, 8.5, 8.0, 20.0, 7.0, 6.5, 6.0, 5.5]
    cnt = td_sequence(closes_brk)
    print("break cnt:", cnt)
    r9b = find_red9(closes_brk)
    assert r9b == [], f"break test failed got {r9b}"

    # 增量计算一致性: 完整序列最后一根 vs 部分序列
    full = closes_up + [23.0]  # 模拟新增一根
    full_cnt = td_sequence(full)
    prev_cnt = td_sequence(closes_up)[-1]
    inc = next_count(prev_cnt, 23.0, closes_up[-4])
    print("incremental:", inc, "full:", full_cnt[-1])
    assert inc == full_cnt[-1], "incremental mismatch"
    print("ALL TESTS PASSED")
