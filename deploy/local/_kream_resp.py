# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1])
c.call("Network.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
ids = {}
c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 4000)"})
t0 = time.time()
body = None
while time.time() - t0 < 30 and body is None:
    try:
        c.ws.settimeout(2); msg = c.ws.recv()
    except Exception:
        c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 4000)"}); continue
    try: d = json.loads(msg)
    except Exception: continue
    m = d.get("method")
    if m == "Network.responseReceived":
        u = d["params"]["response"].get("url", "")
        if "/api/fetch/brands/" in u:
            ids[d["params"]["requestId"]] = u
    elif m == "Network.loadingFinished" and d["params"]["requestId"] in ids:
        rid = d["params"]["requestId"]
        r = c.call("Network.getResponseBody", {"requestId": rid})
        b = r.get("result", {}).get("result", {}).get("body") or r.get("result", {}).get("body")
        if b:
            try:
                j = json.loads(b)
            except Exception:
                continue
            print("URL:", ids[rid][:120])
            print("TOP KEYS:", list(j.keys())[:12])
            for k in j:
                v = j[k]
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    print(f"LIST '{k}' n={len(v)}")
                    print("ITEM0:", json.dumps(v[0], ensure_ascii=False)[:800])
                    break
            body = True
            break
c.close()
