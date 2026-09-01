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
  var imgs = Array.from(document.querySelectorAll('img'));
  // 가장 큰(실제 생성이미지) + 마지막(최신) 것 선택
  var candidates = imgs.filter(i => i.naturalWidth > 300);
  if (!candidates.length) return null;
  var target = candidates[candidates.length - 1];
  var canvas = document.createElement('canvas');
  canvas.width = target.naturalWidth;
  canvas.height = target.naturalHeight;
  var ctx = canvas.getContext('2d');
  ctx.drawImage(target, 0, 0);
  try {
    return canvas.toDataURL('image/png');
  } catch(e) {
    return 'ERROR: ' + e.message;
  }
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value")
if val and val.startswith("data:image"):
    b64 = val.split(",", 1)[1]
    with open("C:/tmp/gemini_venusaur_final.png", "wb") as f:
        f.write(base64.b64decode(b64))
    print("saved", len(b64))
else:
    print("FAIL:", (val or "")[:200])
c.close()
