# -*- coding: utf-8 -*-
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
c.send("Page.navigate", {"url": f"https://www.ebay.com/itm/{sys.argv[2]}"})
time.sleep(8)
t = js("document.body.innerText") or ""
for pat in ["Near Mint", "near mint", "NM", "Condition", "Ungraded", "Sealed"]:
    i = t.find(pat)
    if i >= 0:
        print(f"[{pat}] ...{t[max(0,i-90):i+120]}".replace("\n", " | ")[:260])
c.close()
