# -*- coding: utf-8 -*-
import sys, os, time, base64, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Page.enable"); c.call("Runtime.enable"); c.call("Emulation.setDeviceMetricsOverride", {"width":900,"height":1400,"deviceScaleFactor":2,"mobile":False})
time.sleep(1.5)
r = c.call("Runtime.evaluate", {"expression":"(function(){var e=document.querySelector('.wrap');var r=e.getBoundingClientRect();return JSON.stringify({w:Math.ceil(r.width),h:Math.ceil(r.height)});})()","returnByValue":True})
box = json.loads(r["result"]["result"]["value"])
print("배너 크기:", box)
s = c.call("Page.captureScreenshot", {"format":"png","clip":{"x":0,"y":0,"width":box["w"],"height":box["h"],"scale":2}})
open("C:/tmp/banner_new.png","wb").write(base64.b64decode(s["result"]["result"]["data"] if "result" in s.get("result",{}) else s["result"]["data"]))
print("저장 완료")
c.close()
