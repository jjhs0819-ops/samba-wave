# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab_id = sys.argv[1] if len(sys.argv) > 1 else "88C17EECB892F607421395A19075CFBD"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1.5)
r = c.call("Page.captureScreenshot", {"format": "png"})
open("C:/tmp/gm_shot.png","wb").write(base64.b64decode(r["result"]["result"]["data"] if "result" in r.get("result",{}) else r["result"]["data"]))
print("saved")
c.close()
