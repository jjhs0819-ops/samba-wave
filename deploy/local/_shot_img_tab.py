# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "A364291B191ACC833F7FF9993A06C552"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(2)

# 이미지 자연크기 확인
c.call("Runtime.enable")
r = c.call("Runtime.evaluate", {"expression": "document.title + '|' + (document.querySelector('img') ? document.querySelector('img').naturalWidth+'x'+document.querySelector('img').naturalHeight : 'no img')", "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))

r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/img_tab_shot.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
