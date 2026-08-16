# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "EB3B4370CC14CFE9B948A5D90CE1C628"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
c.send("Page.reload", {"ignoreCache": True})
time.sleep(5)

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/orders_page_check.txt", "w", encoding="utf-8") as f:
    f.write(text[:3000])
print("len", len(text))
c.close()
