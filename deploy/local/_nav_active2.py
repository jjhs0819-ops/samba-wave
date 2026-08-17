# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "4128F89D5C96703F28382CAD395EBF76"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
c.send("Page.navigate", {"url": "https://www.ebay.com/sh/lst/active"})
time.sleep(4)
r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/ebay_active_list2.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("len", len(text))
c.close()
