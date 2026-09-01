# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab, item = sys.argv[1], sys.argv[2]
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
c.send("Page.navigate", {"url": f"https://www.ebay.com/itm/{item}"})
time.sleep(7)
print("URL:", js("location.href"))
txt = (js("document.body.innerText") or "")[:600].replace("\n", " | ")
print("본문:", txt[:400])
c.close()
