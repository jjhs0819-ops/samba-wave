# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1])
c.call("Network.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
ids = {}; done = False
time.sleep(3)
c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 4000)"})
t0 = time.time()
while time.time() - t0 < 30 and not done:
    try:
        c.ws.settimeout(2); msg = c.ws.recv()
    except Exception:
        c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 4000)"}); continue
    try: d = json.loads(msg)
    except Exception: continue
    m = d.get("method")
    if m == "Network.responseReceived" and "/api/fetch/brands/" in d["params"]["response"].get("url",""):
        ids[d["params"]["requestId"]] = 1
    elif m == "Network.loadingFinished" and d["params"]["requestId"] in ids:
        r = c.call("Network.getResponseBody", {"requestId": d["params"]["requestId"]})
        b = (r.get("result", {}).get("result", {}) or r.get("result", {})).get("body")
        if not b: continue
        j = json.loads(b)
        it = j.get("items") or []
        if not it: continue
        # product_card 안에서 가격 관련 키 탐색
        s = json.dumps(it[0], ensure_ascii=False)
        import re
        print("가격키 후보:", sorted(set(re.findall(r'"([a-z_]*(?:price|amount|ask|bid)[a-z_]*)"', s))))
        # 전체 구조 키
        def keys(o, p="", depth=0):
            out=[]
            if depth>3: return out
            if isinstance(o, dict):
                for k,v in o.items():
                    out.append(p+k)
                    out += keys(v, p+k+".", depth+1)
            return out
        ks = keys(it[0])
        print("키 일부:", [k for k in ks if any(x in k for x in ('price','amount','soldout','status','product'))][:25])
        done = True
c.close()
