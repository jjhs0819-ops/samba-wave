# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "E846410983295B8FBFB25331B6B9BD4D"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
c.send("Page.reload", {"ignoreCache": True})
time.sleep(4)
r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/listing_shot2.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
