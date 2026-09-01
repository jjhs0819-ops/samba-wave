# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "1C6204C82C7BB56B6EB0942AB2C9CC93"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(3)
r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/listing_shot4.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
