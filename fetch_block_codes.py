# -*- coding: utf-8 -*-
"""
板块代码解析器
==============
为 sector_ref.js 里的每个概念/行业名解析出东方财富板块代码(BKxxxx),
输出 data/out/block_codes.json = {"PCB":"BK0877", "商业航天":"BK0963", ...}

为什么要单独做:
  fetch_blocks.py 抓个股所属板块时只留了 f14(名字), 把 f12(BK 代码) 丢了。
  板块代码用于前端点击跳转 eastmoney 板块指数页:
      https://quote.eastmoney.com/bk/90.<BKxxxx>.html

做法(贪心集合覆盖, 省请求):
  东财 clist "全部板块列表" 接口当前被沙箱阻断(empty reply), 但 slist(个股所属板块) 可用。
  一次 slist 能返回该股全部 20~50 个板块, 所以按「能覆盖最多未解析目标」的顺序挑股票,
  几十~上百次请求即可把 400 个概念全部解析出来。

用法: python3 fetch_block_codes.py
"""
import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "out")
UA = {"User-Agent": "Mozilla/5.0"}


def secid_of(sym):
    return ("1." if sym[:2] == "sh" else "0.") + sym[2:]


def fetch_boards(sym, retry=2):
    """返回该股所属板块的 {名字: 代码}"""
    u = (f"https://push2.eastmoney.com/api/qt/slist/get?secid={secid_of(sym)}"
         f"&spt=3&fields=f12,f14&po=1&pn=1&pz=100")
    for _ in range(retry + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            diff = ((d.get("data") or {}).get("diff") or {})
            vals = diff.values() if isinstance(diff, dict) else diff
            return {v["f14"]: v["f12"] for v in vals if v.get("f12") and v.get("f14")}
        except Exception:
            time.sleep(0.4)
    return {}


def target_names():
    """从 sector_ref.js 读回概念名表(单一事实来源, 避免两边漂移)"""
    p = os.path.join(BASE, "sector_ref.js")
    s = open(p, encoding="utf-8").read()
    m = re.search(r"window\.SECTOR_NAMES=(\[.*?\]);", s, re.S)
    if not m:
        raise SystemExit("!! 未能在 sector_ref.js 找到 SECTOR_NAMES, 请先跑 gen_sector_ref.py")
    return json.loads(m.group(1))


def main():
    blocks = json.load(open(os.path.join(OUT, "stock_blocks.json"), encoding="utf-8"))
    targets = set(target_names())
    print("待解析板块名: %d 个" % len(targets))

    # 每只股票覆盖多少个目标概念 -> 贪心优先挑覆盖多的
    covers = {sym: sum(1 for b in blk if b in targets) for sym, blk in blocks.items()}
    order = sorted((s for s, c in covers.items() if c > 0), key=lambda s: -covers[s])

    codes = {}
    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        for i in range(0, len(order), 12):
            if len(codes) >= len(targets):
                break
            batch = order[i:i + 12]
            for mp in ex.map(fetch_boards, batch):
                for name, code in mp.items():
                    if name in targets and name not in codes:
                        codes[name] = code
            done += len(batch)
            if done % 1200 == 0 or len(codes) >= len(targets):
                print("  已请求 %d 只 | 已解析 %d/%d" % (done, len(codes), len(targets)), flush=True)
            time.sleep(0.02)

    miss = sorted(targets - set(codes))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "block_codes.json")
    json.dump(codes, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("OK 解析 %d/%d (%.1f%%) -> %s" % (
        len(codes), len(targets), 100.0 * len(codes) / len(targets), os.path.relpath(p, BASE)))
    if miss:
        print("未解析 %d 个:" % len(miss), " ".join(miss[:30]))


if __name__ == "__main__":
    main()
