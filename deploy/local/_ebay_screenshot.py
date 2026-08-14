# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "413B2AD8658332F0A44B021FD2389266"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/ebay_appeal_screenshot.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
