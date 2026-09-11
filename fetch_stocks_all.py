# -*- coding: utf-8 -*-
"""从东方财富接口拉取全市场A股列表(含科创板/北交所), 合并进stock_list.json"""
import json
import time
import urllib.request

def fetch_em(fs, pz=100):
    """fs: 板块过滤条件, 分页拉取全部"""
    out = []
    page = 1
    while True:
        url = (f"https://82.push2.eastmoney.com/api/qt/clist/get?pn={page}&pz={pz}&po=1&np=1"
               f"&fltt=2&invt=2&fid=f12&fs={fs}&fields=f12,f14")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  page{page} FAIL: {e}")
            break
        diff = (d.get("data") or {}).get("diff") or []
        if not diff:
            break
        for x in diff:
            code = str(x.get("f12", ""))
            name = x.get("f14", "")
            if not code or not name:
                continue
            if code.startswith("6"):
                sym = "sh" + code
            elif code.startswith(("0", "3")):
                sym = "sz" + code
            elif code.startswith(("4", "8", "9")):
                sym = "bj" + code
            else:
                continue
            out.append({"symbol": sym, "name": name})
        if len(diff) < pz:
            break
        page += 1
        time.sleep(0.15)
    return out

def main():
    # 沪深主板+创业板+科创板+北交所
    groups = [
        ("m:1+t:2,m:1+t:23", "沪主板+科创板"),     # 沪: 1+t:2主板 1+t:23科创
        ("m:0+t:6,m:0+t:80", "深主板+创业板"),     # 深: 0+t:6主板 0+t:80创业
        ("m:0+t:81+s:2048", "北交所"),
    ]
    all_stocks = {}
    for fs, label in groups:
        try:
            arr = fetch_em(fs)
            for s in arr:
                all_stocks[s["symbol"]] = s["name"]
            print(f"{label}: {len(arr)}只")
        except Exception as e:
            print(f"{label} FAIL: {e}")
        time.sleep(0.3)

    # 合并旧列表
    try:
        old = json.load(open("data/stock_list.json", encoding="utf-8"))
        for s in old.get("stocks", []):
            all_stocks.setdefault(s["symbol"], s["name"])
    except Exception:
        pass

    stocks = [{"symbol": k, "name": v} for k, v in sorted(all_stocks.items())]
    with open("data/stock_list.json", "w", encoding="utf-8") as f:
        json.dump({"total": len(stocks), "stocks": stocks}, f, ensure_ascii=False)
    print(f"OK total={len(stocks)}")
    # 统计
    from collections import Counter
    c = Counter(s["symbol"][:2] for s in stocks)
    print("板块分布:", dict(c))
    kc = [s for s in stocks if s["symbol"].startswith("sh688")]
    print("科创板:", len(kc))
    bj = [s for s in stocks if s["symbol"].startswith("bj")]
    print("北交所:", len(bj))

if __name__ == "__main__":
    main()
