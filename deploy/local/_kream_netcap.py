# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
c = CDPConn(tab)
c.call("Network.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
# 스크롤로 추가 로드 유발
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
seen = []
t0 = time.time()
c.send("Runtime.evaluate", {"expression": "window.scrollTo(0, document.body.scrollHeight)"})
while time.time() - t0 < 25:
    try:
        c.ws.settimeout(2)
        msg = c.ws.recv()
    except Exception:
        c.send("Runtime.evaluate", {"expression": "window.scrollBy(0, 3000)"})
        continue
    try:
        d = json.loads(msg)
    except Exception:
        continue
    if d.get("method") == "Network.requestWillBeSent":
        u = d["params"]["request"].get("url", "")
        if "/api/" in u and "kream" in u:
            if u not in seen:
                seen.append(u)
for u in seen[:40]:
    print(u[:200])
print("총", len(seen))
c.close()
