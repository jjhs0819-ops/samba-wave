# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

js = """
(function(){
  var scroller = document.scrollingElement || document.documentElement;
  window.scrollTo(0, 0);
  var mainScroll = document.querySelector('[class*="chat-history"], [class*="conversation"], main');
  if (mainScroll) mainScroll.scrollTop = 0;
  return 'scrolled';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(1.5)

r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/gemini_top.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
