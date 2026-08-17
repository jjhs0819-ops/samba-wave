# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Network.enable")
print("network enabled - capturing 60s")
seen = {}
t0 = time.time()
while time.time() - t0 < 60:
    try:
        msg = c.ws.recv()
    except Exception as e:
        break
    try:
        d = json.loads(msg)
    except Exception:
        continue
    m = d.get("method")
    if m == "Network.requestWillBeSent":
        req = d["params"]["request"]
        url = req.get("url", "")
        if req.get("method") == "POST" and ("batchexecute" in url or "StreamGenerate" in url or "assistant" in url or "bard" in url):
            seen[d["params"]["requestId"]] = {"url": url, "postDataLen": len(req.get("postData") or "")}
            print("POST", url[:160], "bodylen", len(req.get("postData") or ""))
with open("C:/tmp/gemini_netcap.json", "w", encoding="utf-8") as f:
    json.dump(seen, f, ensure_ascii=False, indent=2)
print("captured", len(seen))
c.close()
