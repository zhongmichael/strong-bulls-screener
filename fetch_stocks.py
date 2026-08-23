# -*- coding: utf-8 -*-
"""获取A股全市场股票列表（腾讯自选股接口）"""
import json
import time
import urllib.request

URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"

def fetch(offset, count=200):
    url = f"{URL}?board_code=aStock&sort_type=price&direct=down&offset={offset}&count={count}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://stockapp.finance.qq.com/"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    stocks = []
    seen = set()
    offset = 0
    while True:
        d = fetch(offset)
        rl = (d.get("data") or {}).get("rank_list") or []
        if not rl:
            break
        new = 0
        for x in rl:
            code = x.get("code")  # sh600519 格式
            name = x.get("name")
            if code and code not in seen:
                seen.add(code)
                stocks.append({"symbol": code, "name": name})
                new += 1
        print(f"offset={offset} got={len(rl)} new={new} total={len(stocks)}")
        if new == 0 or len(rl) < 200:
            break
        offset += 200
        time.sleep(0.15)
    with open("data/stock_list.json", "w", encoding="utf-8") as f:
        json.dump({"total": len(stocks), "stocks": stocks}, f, ensure_ascii=False)
    print(f"OK total={len(stocks)}")

if __name__ == "__main__":
    main()
