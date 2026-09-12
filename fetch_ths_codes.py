# -*- coding: utf-8 -*-
"""
同花顺板块代码解析器
====================
为 sector_ref.js 的概念名解析同花顺「概念板块」代码, 输出
data/out/ths_block_codes.json = {"PCB":"301558", "储能":"309121", ...}

用于前端卡片副入口跳转:
    https://q.10jqka.com.cn/gn/detail/code/<code>/

⚠️ 覆盖率说明(重要, 别误以为是 bug):
  东财与同花顺的概念**各有各的体系**, 名字对不上是常态:
    PCB        -> 同花顺叫「PCB概念」
    5G概念      -> 同花顺叫「5G」
    储能概念     -> 同花顺叫「储能」
    新能源车     -> 同花顺叫「新能源汽车」
    央国企改革    -> 同花顺叫「央企国企改革」
  更麻烦的是同花顺**根本没有**一批东财概念: 被动元件 / 通信技术 / 超清视频 / 光通信模块 ...
  所以本脚本只能解析出「确实存在对应板块」的那部分(约 50~60%), 其余留空 ->
  前端就不渲染同花顺入口(绝不猜、不硬套到名字相近但成分不同的板块上)。

数据来源: https://q.10jqka.com.cn/gn/ (服务端渲染, GBK, 361 个概念, 无反爬拦截)
  注意: 它的 ajax 分页接口 (/gn/index/.../ajax/1/) 返回 401, 拿不到更多页, 只能用这一份。

用法: python3 fetch_ths_codes.py
"""
import json
import os
import re
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "out")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# 人工核对过的别名: 东财概念名 -> 同花顺概念名
# 只收「成分股高度重叠、概念含义一致」的; 含义不同或同花顺没有的一律不收(宁缺勿错)
ALIAS = {
    "新能源车": "新能源汽车",
    "央国企改革": "央企国企改革",
    "长江三角": "长三角一体化",
    "PPP模式": "PPP概念",
    "并购重组概念": "股权转让(并购重组)",
    "核能核电": "核电",
    "养老金": "养老概念",
    "阿里概念": "阿里巴巴概念",
    "风能": "风电",
    "水利建设": "水利",
    "中字头": "中字头股票",
    "装配建筑": "装配式建筑",
    "智能驾驶": "无人驾驶",
    "婴童概念": "三胎概念",
    "文娱消费": "文化传媒概念",
    "新零售": "无人零售",
    "海洋经济": "海工装备",
}


def norm(n):
    """去掉「概念/板块/产业/行业」后缀与括号补充, 便于跨平台比对"""
    n = n.strip()
    n = re.sub(r"[（(].*?[)）]", "", n)
    n = re.sub(r"(概念|板块|产业|行业)$", "", n)
    return n


def fetch_ths_list():
    u = "https://q.10jqka.com.cn/gn/"
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20) as r:
        s = r.read().decode("gbk", "ignore")
    rows = re.findall(r'/gn/detail/code/(\d+)/?"[^>]*>([^<]{1,24})<', s)
    m = {}
    for code, name in rows:
        m.setdefault(name.strip(), code)
    return m


def main():
    ths = fetch_ths_list()
    print("同花顺概念板块: %d 个" % len(ths))

    js = open(os.path.join(BASE, "sector_ref.js"), encoding="utf-8").read()
    ours = json.loads(re.search(r"window\.SECTOR_NAMES=(\[.*?\]);", js, re.S).group(1))
    print("本项目概念名: %d 个" % len(ours))

    # 归一化索引(同花顺侧): 精确名 -> 代码, 归一化名 -> 代码
    by_norm = {}
    for name, code in ths.items():
        by_norm.setdefault(norm(name), code)

    codes = {}
    for o in ours:
        if o in ths:                                  # ① 同名
            codes[o] = ths[o]
        elif o in ALIAS and ALIAS[o] in ths:          # ② 人工别名
            codes[o] = ths[ALIAS[o]]
        elif norm(o) in by_norm:                      # ③ 归一化后同名(PCB概念 / 储能概念 / 5G概念)
            codes[o] = by_norm[norm(o)]
        elif o in by_norm:
            codes[o] = by_norm[o]

    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "ths_block_codes.json")
    json.dump(codes, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

    print("已解析 %d/%d = %.1f%%  (其余同花顺无对应板块, 前端不渲染入口)" % (
        len(codes), len(ours), 100.0 * len(codes) / len(ours)))
    print("-> %s" % os.path.relpath(p, BASE))
    print("样例:", " ".join("%s=%s" % (k, v) for k, v in list(codes.items())[:8]))


if __name__ == "__main__":
    main()
