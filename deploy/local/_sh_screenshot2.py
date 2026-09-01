# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "8E18DEC4C2608D21C7C63F59FB213D7E"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/sh_shot2.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
