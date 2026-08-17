# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

for _ in range(15):
    c.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 1100, "y": 400, "deltaX": 0, "deltaY": -800})
    time.sleep(0.2)

time.sleep(1)
r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/gemini_scrolled_up.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
