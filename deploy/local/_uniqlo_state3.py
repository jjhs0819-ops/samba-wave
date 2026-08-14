# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "0BA049D95E6F9DB5BB599AAC50BF8C97"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

r = c.call("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
print("URL:", r.get("result", {}).get("result", {}).get("value"))

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/uniqlo_page_now.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("len", len(text))
c.close()
