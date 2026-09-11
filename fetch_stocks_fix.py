# -*- coding: utf-8 -*-
"""补齐科创板/北交所/创业板列表并合并"""
import json, time, urllib.request

def fetch_em(fs, max_retry=8):
    out = {}
    page = 1
    while True:
        ok = False
        for attempt in range(max_retry):
            try:
                url = (f"https://82.push2.eastmoney.com/api/qt/clist/get?pn={page}&pz=100&po=1&np=1"
                       f"&fltt=2&invt=2&fid=f12&fs={fs}&fields=f12,f14")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    d = json.loads(r.read().decode("utf-8"))
                diff = (d.get("data") or {}).get("diff") or []
                ok = True
                break
            except Exception:
                time.sleep(2 + attempt * 2)
        if not ok:
            break
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
            out[sym] = name
        if len(diff) < 100:
            break
        page += 1
        time.sleep(0.4)
    return out

old = json.load(open("data/stock_list.json", encoding="utf-8"))
all_s = {s["symbol"]: s["name"] for s in old["stocks"]}
# 只补可能缺的板块
groups = [("m:1+t:23", "科创板"), ("m:0+t:6", "深主板"), ("m:0+t:80", "创业板"), ("m:0+t:81+s:2048", "北交所")]
for fs, label in groups:
    try:
        arr = fetch_em(fs)
        for k, v in arr.items():
            all_s[k] = v
        print(label, len(arr), flush=True)
    except Exception as e:
        print(label, "FAIL", e, flush=True)
    time.sleep(0.8)

stocks = [{"symbol": k, "name": v} for k, v in sorted(all_s.items())]
json.dump({"total": len(stocks), "stocks": stocks}, open("data/stock_list.json", "w", encoding="utf-8"), ensure_ascii=False)
print("total", len(stocks), flush=True)
print("科创板", len([s for s in stocks if s["symbol"].startswith("sh688")]), flush=True)
print("北交所", len([s for s in stocks if s["symbol"].startswith("bj")]), flush=True)
