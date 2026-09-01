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

# 잉어킹 이미지(가장 위쪽) 클릭해서 라이트박스 열기
js = """
(function(){
  var imgs = Array.from(document.querySelectorAll('img'));
  var candidates = imgs.filter(i => i.naturalWidth > 300);
  candidates.sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  if (!candidates.length) return 'NOT FOUND';
  var target = candidates[0];
  target.click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)

r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/lightbox_shot.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
