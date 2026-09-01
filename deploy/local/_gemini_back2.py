# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

for typ in ("mousePressed", "mouseReleased"):
    c.call("Input.dispatchMouseEvent", {"type": typ, "x": 46, "y": 30, "button": "left", "clickCount": 1})
    time.sleep(0.1)
time.sleep(1)

r = c.call("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
