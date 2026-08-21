# -*- coding: utf-8 -*-
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable")
def js(e, ctx=None):
    p = {"expression": e, "returnByValue": True}
    if ctx: p["contextId"] = ctx
    r = c.call("Runtime.evaluate", p)
    return r.get("result", {}).get("result", {}).get("value")
src = js("(function(){var f=document.getElementById('desc_ifr');return f?f.src:null;})()")
print("desc src:", (src or "none")[:110])
if src:
    c.send("Page.navigate", {"url": src})
    time.sleep(6)
    t = js("document.body.innerText") or ""
    print("설명 길이:", len(t))
    print("본문:", t[:700].replace("\n", " | "))
c.close()
