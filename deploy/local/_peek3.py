# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
for item in sys.argv[2:]:
    c.send("Page.navigate", {"url": f"https://www.ebay.com/itm/{item}"})
    time.sleep(6)
    ttl = js("document.title") or ""
    print(item, "|", ttl[:80])
c.close()
