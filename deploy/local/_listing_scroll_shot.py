# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "E846410983295B8FBFB25331B6B9BD4D"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
c.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 700, "y": 500, "deltaX": 0, "deltaY": 700})
time.sleep(1)
r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/listing_shot3.png", "wb") as f:
    f.write(base64.b64decode(data))

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
idx = text.find("Shipping:")
with open("C:/tmp/listing_ship.txt", "w", encoding="utf-8") as f:
    f.write(text[idx:idx+300] if idx >= 0 else "NOT FOUND")
print("saved")
c.close()
