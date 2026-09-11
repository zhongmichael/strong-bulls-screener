# -*- coding: utf-8 -*-
"""
六大类技术指标买入信号引擎（纯 numpy 向量化）
输入: OHLCV 序列 (numpy arrays, 时间升序)
输出: 每个交易日触发的信号代码列表

六大类:
  TREND     趋势跟踪: MA金叉/站上年线/多头排列/回踩支撑/MACD金叉/红柱/底背离/DMI/TRIX
  MOMENTUM  超买超卖: RSI超卖/金叉/底背离/KDJ金叉/低位金叉/J<0/CCI/ROC/W%R
  VOLUME    成交量:   量增价升/底部放量/缩量回调/量增价平/OBV底背离
  CANDLE    K线形态:  锤子线/倒锤子/大阳线/看涨吞没/曙光初现/多方炮/上升三法
  PATTERN   图表形态: 双底突破/平台突破/支撑位买入
  AUX       辅助:     BOLL下轨反弹/BIAS负偏离/EMV>=0/BRAR低位/VR低位/PSY低位
"""

import numpy as np

# ---------------- 基础工具 ----------------
def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n-1:] = (c[n:] - c[:-n]) / n
    return out

def ema(x, n):
    out = np.full(len(x), np.nan)
    if len(x) == 0:
        return out
    alpha = 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i-1]
    return out

def rolling_max(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i >= n-1:
            out[i] = np.max(x[i-n+1:i+1])
    return out

def rolling_min(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i >= n-1:
            out[i] = np.min(x[i-n+1:i+1])
    return out

def std(x, n):
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if i >= n-1:
            out[i] = np.std(x[i-n+1:i+1])
    return out

# ---------------- 指标计算 ----------------
class Indicators:
    def __init__(self, o, h, l, c, v):
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v
        n = len(c)
        # --- 均线 ---
        self.ma5   = sma(c, 5)
        self.ma10  = sma(c, 10)
        self.ma20  = sma(c, 20)
        self.ma60  = sma(c, 60)
        self.ma250 = sma(c, 250)
        # --- MACD ---
        ema12 = ema(c, 12); ema26 = ema(c, 26)
        self.dif = ema12 - ema26
        self.dea = ema(self.dif, 9)
        self.macd = 2 * (self.dif - self.dea)
        # --- RSI (Wilder 简化: SMA 窗口) ---
        diff = np.diff(c, prepend=c[0])
        gain = np.where(diff > 0, diff, 0.0)
        loss = np.where(diff < 0, -diff, 0.0)
        ag6  = sma(gain, 6);  al6  = sma(loss, 6)
        ag12 = sma(gain, 12); al12 = sma(loss, 12)
        ag14 = sma(gain, 14); al14 = sma(loss, 14)
        def rsi(ag, al):
            rs = np.divide(ag, al, out=np.full(n, 50.0), where=al != 0)
            return 100 - 100 / (1 + rs)
        self.rsi6  = rsi(ag6, al6)
        self.rsi12 = rsi(ag12, al12)
        self.rsi14 = rsi(ag14, al14)
        # --- KDJ ---
        llv9 = rolling_min(l, 9); hhv9 = rolling_max(h, 9)
        rsv = np.divide(c - llv9, hhv9 - llv9, out=np.full(n, 50.0), where=(hhv9-llv9) != 0) * 100
        self.k = np.full(n, 50.0); self.d = np.full(n, 50.0)
        for i in range(1, n):
            self.k[i] = self.k[i-1] * 2/3 + rsv[i] / 3
            self.d[i] = self.d[i-1] * 2/3 + self.k[i] / 3
        self.j = 3 * self.k - 2 * self.d
        # --- CCI(14) ---
        tp = (h + l + c) / 3
        tp_ma = sma(tp, 14)
        md = np.full(n, np.nan)
        for i in range(13, n):
            md[i] = np.mean(np.abs(tp[i-13:i+1] - tp_ma[i]))
        self.cci = np.divide(tp - tp_ma, 0.015 * md, out=np.full(n, 0.0), where=md != 0)
        # --- TRIX(12,3) ---
        e1 = ema(c, 12); e2 = ema(e1, 12); e3 = ema(e2, 12)
        self.trix = np.full(n, 0.0)
        self.trix[1:] = (e3[1:] - e3[:-1]) / np.abs(e3[:-1]) * 100
        self.trix_ma = sma(self.trix, 20)
        # --- W%R(14) ---
        hhv14 = rolling_max(h, 14); llv14 = rolling_min(l, 14)
        self.wr = np.divide(hhv14 - c, hhv14 - llv14, out=np.full(n, 50.0), where=(hhv14-llv14) != 0) * 100
        # --- ROC(12) ---
        self.roc = np.full(n, 0.0)
        self.roc[12:] = (c[12:] - c[:-12]) / np.abs(c[:-12]) * 100
        # --- BOLL(20) ---
        self.boll_mid = sma(c, 20)
        b_std = std(c, 20)
        self.boll_up = self.boll_mid + 2 * b_std
        self.boll_dn = self.boll_mid - 2 * b_std
        # --- BIAS(20) ---
        self.bias20 = np.divide(c - self.ma20, np.abs(self.ma20), out=np.full(n, 0.0), where=self.ma20 != 0) * 100
        # --- OBV ---
        obv = np.zeros(n)
        for i in range(1, n):
            if c[i] > c[i-1]:
                obv[i] = obv[i-1] + v[i]
            elif c[i] < c[i-1]:
                obv[i] = obv[i-1] - v[i]
            else:
                obv[i] = obv[i-1]
        self.obv = obv
        # --- EMV(14) ---
        mid = (h + l) / 2
        dm = np.zeros(n); br = np.zeros(n)
        for i in range(1, n):
            dm[i] = mid[i] - mid[i-1]
            br[i] = v[i] / 1e8 if v[i] > 0 else 1e-8
        emv_raw = np.divide(dm, br, out=np.zeros(n), where=br != 0)
        self.emv = sma(emv_raw, 14)
        # --- BR/AR ---
        br_up = np.maximum(h[1:] - c[:-1], 0)
        br_dn = np.maximum(c[:-1] - l[1:], 0)
        ar_up = np.maximum(h[1:] - l[1:], 0)  # 简化: 用H-L
        ar_dn = np.maximum(np.abs(c[1:] - c[:-1]), 1e-9)
        s26_up = np.convolve(br_up, np.ones(26), 'valid')
        s26_dn = np.convolve(br_dn, np.ones(26), 'valid')
        a26_up = np.convolve(ar_up, np.ones(26), 'valid')
        a26_dn = np.convolve(ar_dn, np.ones(26), 'valid')
        self.br = np.full(n, 100.0); self.ar = np.full(n, 100.0)
        if len(s26_dn) == n - 25:
            self.br[25:] = s26_up / np.maximum(s26_dn, 1e-9) * 100
            self.ar[25:] = a26_up / np.maximum(a26_dn, 1e-9) * 100
        # --- VR(26) ---
        vr_up = np.zeros(n); vr_dn = np.zeros(n); vr_fl = np.zeros(n)
        for i in range(1, n):
            if c[i] > c[i-1]:
                vr_up[i] = v[i]
            elif c[i] < c[i-1]:
                vr_dn[i] = v[i]
            else:
                vr_fl[i] = v[i]
        cu = np.convolve(vr_up, np.ones(26), 'same')
        cd = np.convolve(vr_dn, np.ones(26), 'same')
        cf = np.convolve(vr_fl, np.ones(26), 'same')
        self.vr = np.divide(cu, cd + cf/2 + 1e-9, out=np.full(n, 100.0), where=(cd+cf/2) != 0) * 100
        # --- PSY(12) ---
        up = np.zeros(n)
        for i in range(1, n):
            up[i] = 1 if c[i] > c[i-1] else 0
        self.psy = sma(up, 12) * 100
        # --- 预计算供信号判断使用的辅助序列 ---
        self.vma5 = sma(v, 5)
        self.llv20 = rolling_min(l, 20)
        self.hhv20 = rolling_max(h, 20)
        self.llv30 = rolling_min(l, 30)
        self.hhv30 = rolling_max(h, 30)
        # --- DMI(14) ---
        up_move = h[1:] - h[:-1]
        dn_move = l[:-1] - l[1:]
        pdm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
        ndm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        tr_s = np.convolve(tr, np.ones(14), 'valid')
        pdm_s = np.convolve(pdm, np.ones(14), 'valid')
        ndm_s = np.convolve(ndm, np.ones(14), 'valid')
        self.pdi = np.full(n, 0.0); self.mdi = np.full(n, 0.0)
        if len(tr_s) == n - 14:
            self.pdi[14:] = pdm_s / np.maximum(tr_s, 1e-9) * 100
            self.mdi[14:] = ndm_s / np.maximum(tr_s, 1e-9) * 100

# ---------------- 信号判断 ----------------
class SignalEngine:
    """对单只股票, 返回 {date_idx: [signal_codes]} 或逐日 bool 表"""

    def __init__(self, o, h, l, c, v):
        self.ind = Indicators(o, h, l, c, v)
        self.n = len(c)

    def is_downtrend(self, i):
        """下跌趋势判定: 均线空头排列(MA5<MA10<MA20<MA60) 或 (收盘<MA60且MA60下弯)
        返回 True = 下跌趋势"""
        if i < 60:
            return False
        ind = self.ind
        c = ind.c
        # 均线空头排列
        if not np.isnan(ind.ma5[i]) and not np.isnan(ind.ma10[i]) \
           and not np.isnan(ind.ma20[i]) and not np.isnan(ind.ma60[i]):
            if ind.ma5[i] < ind.ma10[i] < ind.ma20[i] < ind.ma60[i]:
                return True
        # 收盘 < MA60 且 MA60 下弯 (中期下跌)
        if not np.isnan(ind.ma60[i]) and not np.isnan(ind.ma60[i-1]):
            if c[i] < ind.ma60[i] and ind.ma60[i] < ind.ma60[i-1]:
                return True
        return False

    def signals_at(self, i):
        """判断第 i 根K线(截止当日)触发的所有信号"""
        if i < 20:
            return []
        ind = self.ind
        c = ind.c; h = ind.h; l = ind.l; v = ind.v; o = ind.o
        sig = []

        # ========== 一、趋势跟踪 TREND ==========
        # MA金叉: MA5上穿MA20 (当日)
        if i >= 1 and not np.isnan(ind.ma5[i]) and not np.isnan(ind.ma20[i]) \
           and not np.isnan(ind.ma5[i-1]) and not np.isnan(ind.ma20[i-1]):
            if ind.ma5[i-1] <= ind.ma20[i-1] and ind.ma5[i] > ind.ma20[i]:
                sig.append("t_ma_golden")
        # 站上年线
        if not np.isnan(ind.ma250[i]) and c[i] > ind.ma250[i]:
            sig.append("t_above_year")
        # 均线多头排列 MA5>MA10>MA20>MA60
        if not np.isnan(ind.ma5[i]) and not np.isnan(ind.ma60[i]):
            if ind.ma5[i] > ind.ma10[i] > ind.ma20[i] > ind.ma60[i]:
                sig.append("t_bull_arrange")
        # 回踩MA20支撑
        if not np.isnan(ind.ma20[i]) and c[i] >= ind.ma20[i] and c[i] <= ind.ma20[i] * 1.02:
            sig.append("t_support20")
        # MACD金叉
        if i >= 1 and ind.dif[i-1] <= ind.dea[i-1] and ind.dif[i] > ind.dea[i]:
            sig.append("t_macd_golden")
        # MACD红柱 (柱由负转正)
        if i >= 1 and ind.macd[i-1] <= 0 and ind.macd[i] > 0:
            sig.append("t_macd_red")
        # MACD底背离 (20日内: 股价新低但DIF低点抬高)
        if i >= 20:
            seg_c = c[i-19:i+1]; seg_dif = ind.dif[i-19:i+1]
            if not np.isnan(seg_dif).any():
                if c[i] <= np.min(seg_c[:-1]) * 1.001 and ind.dif[i] > np.min(seg_dif[:-1]):
                    sig.append("t_macd_div")
        # DMI金叉 +DI上穿-DI
        if i >= 1 and ind.pdi[i-1] <= ind.mdi[i-1] and ind.pdi[i] > ind.mdi[i]:
            sig.append("t_dmi_golden")
        # TRIX金叉
        if i >= 1 and not np.isnan(ind.trix_ma[i]) and not np.isnan(ind.trix_ma[i-1]):
            if ind.trix[i-1] <= ind.trix_ma[i-1] and ind.trix[i] > ind.trix_ma[i]:
                sig.append("t_trix_golden")

        # ========== 二、超买超卖/动量 MOMENTUM ==========
        # RSI超卖 (<30)
        if not np.isnan(ind.rsi14[i]) and ind.rsi14[i] < 30:
            sig.append("m_rsi_oversold")
        # RSI快线上穿慢线 (RSI6上穿RSI12)
        if i >= 1 and not np.isnan(ind.rsi6[i-1]) and not np.isnan(ind.rsi12[i-1]) \
           and not np.isnan(ind.rsi6[i]) and not np.isnan(ind.rsi12[i]):
            if ind.rsi6[i-1] <= ind.rsi12[i-1] and ind.rsi6[i] > ind.rsi12[i]:
                sig.append("m_rsi_golden")
        # RSI底背离
        if i >= 20:
            seg_c = c[i-19:i+1]; seg_r = ind.rsi14[i-19:i+1]
            if not np.isnan(seg_r).any():
                if c[i] <= np.min(seg_c[:-1]) * 1.001 and ind.rsi14[i] > np.min(seg_r[:-1]):
                    sig.append("m_rsi_div")
        # KDJ金叉
        if i >= 1 and ind.k[i-1] <= ind.d[i-1] and ind.k[i] > ind.d[i]:
            sig.append("m_kdj_golden")
        # KDJ低位金叉 (K,D<20)
        if i >= 1 and ind.k[i-1] <= ind.d[i-1] and ind.k[i] > ind.d[i] \
           and ind.k[i] < 20 and ind.d[i] < 20:
            sig.append("m_kdj_low_golden")
        # J值<0
        if ind.j[i] < 0:
            sig.append("m_kdj_j_neg")
        # CCI上穿+100
        if i >= 1 and ind.cci[i-1] <= 100 and ind.cci[i] > 100:
            sig.append("m_cci_break")
        # CCI从-100下方上穿-100
        if i >= 1 and ind.cci[i-1] < -100 and ind.cci[i] >= -100:
            sig.append("m_cci_oversold_break")
        # ROC超卖 (<-8, 显著负动量)
        if ind.roc[i] < -8:
            sig.append("m_roc_neg")
        # W%R超卖后反转 (WR>90后回落至<85)
        if i >= 1 and ind.wr[i-1] > 90 and ind.wr[i] < 85:
            sig.append("m_wr_rebound")

        # ========== 三、成交量 VOLUME ==========
        if not np.isnan(ind.vma5[i]):
            # 量增价升
            if v[i] > ind.vma5[i] * 1.5 and c[i] > c[i-1]:
                sig.append("v_vol_price_up")
            # 底部放量 (20日低位 + 放量)
            if not np.isnan(ind.llv20[i]) and c[i] < ind.llv20[i] * 1.06 and v[i] > ind.vma5[i] * 2:
                sig.append("v_bottom_volume")
            # 缩量回调 (MA20上方 缩量回调)
            if not np.isnan(ind.ma20[i]) and c[i] > ind.ma20[i] and c[i] < c[i-1] \
               and v[i] < ind.vma5[i] * 0.6:
                sig.append("v_shrink_pullback")
            # 量增价平
            if v[i] > ind.vma5[i] * 1.5 and abs(c[i] - c[i-1]) / c[i-1] < 0.005:
                sig.append("v_vol_flat")
        # OBV底背离
        if i >= 20:
            seg_c = c[i-19:i+1]; seg_o = ind.obv[i-19:i+1]
            if c[i] <= np.min(seg_c[:-1]) * 1.001 and ind.obv[i] > np.min(seg_o[:-1]):
                sig.append("v_obv_div")

        # ========== 四、K线形态 CANDLE ==========
        body = abs(c[i] - o[i])
        rng = h[i] - l[i]
        if rng > 0:
            upper = h[i] - max(o[i], c[i])
            lower = min(o[i], c[i]) - l[i]
            # 锤子线: 下影>2*实体 上影<实体 低位
            if lower > body * 2 and upper < body and body > 0:
                sig.append("k_hammer")
            # 倒锤子线
            if upper > body * 2 and lower < body and body > 0:
                sig.append("k_inv_hammer")
            # 大阳线
            if c[i] > o[i] and body / (ind.ma20[i] if not np.isnan(ind.ma20[i]) else 1) > 0.04:
                sig.append("k_big_yang")
        # 看涨吞没
        if i >= 1 and c[i] > o[i] and c[i-1] < o[i-1] \
           and c[i] >= o[i-1] and o[i] <= c[i-1]:
            sig.append("k_engulf")
        # 曙光初现
        if i >= 1 and c[i-1] < o[i-1] and c[i] > o[i] \
           and c[i] > (o[i-1] + c[i-1]) / 2 and c[i] < o[i-1]:
            sig.append("k_pierce")
        # 多方炮 (两阳夹一阴)
        if i >= 2 and c[i] > o[i] and c[i-2] > o[i-2] and c[i-1] < o[i-1] \
           and c[i] > c[i-1] and c[i-2] > c[i-1]:
            sig.append("k_three_soldiers")
        # 上升三法 (大阳后3小阴未破大阳开盘价, 第5日大阳)
        if i >= 4 and c[i-4] > o[i-4] and c[i] > o[i]:
            small = all(o[i-j] > c[i-j] for j in range(1, 4))
            if small and min(l[i-3:i]) > o[i-4] and c[i] > o[i-4]:
                sig.append("k_rising_three")

        # ========== 五、图表形态 PATTERN ==========
        # 双底突破 (30日内两次触底, 突破中间高点)
        if i >= 30 and not np.isnan(ind.llv30[i]) and not np.isnan(ind.hhv30[i]):
            seg_l = ind.l[i-29:i+1]; seg_h = ind.h[i-29:i+1]
            ll1 = np.min(seg_l[:15]); ll2 = np.min(seg_l[14:])
            mid_hi = np.max(seg_h[:20])
            if abs(ll1 - ll2) / max(ll1, 1e-9) < 0.03 and c[i] > mid_hi:
                sig.append("p_double_bottom")
        # 平台突破 (20日箱体整理后突破)
        if i >= 20 and not np.isnan(ind.hhv20[i]) and not np.isnan(ind.llv20[i]):
            hi20 = ind.hhv20[i]; lo20 = ind.llv20[i]
            if (hi20 - lo20) / max(lo20, 1e-9) < 0.15 and c[i] > hi20:
                sig.append("p_breakout")
        # 支撑位买入 (回踩MA60后回升)
        if i >= 1 and not np.isnan(ind.ma60[i]) and not np.isnan(ind.ma60[i-1]):
            if l[i-1] <= ind.ma60[i-1] * 1.01 and c[i] > ind.ma60[i]:
                sig.append("p_support60")

        # ========== 六、辅助 AUX ==========
        # BOLL跌破下轨后反弹 (前日<下轨 今日>下轨)
        if i >= 1 and not np.isnan(ind.boll_dn[i]) and not np.isnan(ind.boll_dn[i-1]):
            if l[i-1] < ind.boll_dn[i-1] and c[i] > ind.boll_dn[i]:
                sig.append("a_boll_rebound")
        # BIAS负偏离过大 (<-8%)
        if not np.isnan(ind.bias20[i]) and ind.bias20[i] < -8:
            sig.append("a_bias_neg")
        # EMV 上穿 0 (量价动能转正)
        if i >= 1 and not np.isnan(ind.emv[i]) and not np.isnan(ind.emv[i-1]):
            if ind.emv[i-1] <= 0 and ind.emv[i] > 0:
                sig.append("a_emv_pos")
        # BRAR低位 (BR<50 或 AR<40)
        if not np.isnan(ind.br[i]) and not np.isnan(ind.ar[i]):
            if ind.br[i] < 50 or ind.ar[i] < 40:
                sig.append("a_brar_low")
        # VR<40
        if not np.isnan(ind.vr[i]) and ind.vr[i] < 40:
            sig.append("a_vr_low")
        # PSY低位 (<25)
        if not np.isnan(ind.psy[i]) and ind.psy[i] < 25:
            sig.append("a_psy_low")

        return sig

    def signals_on_dates(self, date_idxs):
        """date_idxs: 需要判断的日期索引列表 -> {idx: [codes]}"""
        out = {}
        for i in date_idxs:
            s = self.signals_at(i)
            if s:
                out[i] = s
        return out
