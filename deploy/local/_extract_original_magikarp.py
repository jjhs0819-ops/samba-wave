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
  var candidates = imgs.filter(i => i.naturalWidth > 300);
  // 잉어킹 큰 이미지 찾기 (가장 위쪽에 있는 큰 이미지)
  candidates.sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  if (!candidates.length) return null;
  var target = candidates[0];
  var canvas = document.createElement('canvas');
  canvas.width = target.naturalWidth;
  canvas.height = target.naturalHeight;
  var ctx = canvas.getContext('2d');
  ctx.drawImage(target, 0, 0);
  try {
    return JSON.stringify({url: target.src, data: canvas.toDataURL('image/png')});
  } catch(e) {
    return JSON.stringify({url: target.src, error: e.message});
  }
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value")
import json
obj = json.loads(val)
print("src url:", obj.get("url"))
if obj.get("data"):
    b64 = obj["data"].split(",", 1)[1]
    with open("C:/tmp/original_magikarp.png", "wb") as f:
        f.write(base64.b64decode(b64))
    print("saved", len(b64))
else:
    print("ERROR:", obj.get("error"))
c.close()
