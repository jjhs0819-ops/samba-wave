# -*- coding: utf-8 -*-
import sys, os, time, base64, json
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
  var candidates = imgs.filter(i => i.naturalWidth >= 800);
  candidates.sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  if (!candidates.length) return 'NOT FOUND';
  var target = candidates[0];
  var r = target.getBoundingClientRect();
  return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height});
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
rect_str = r.get("result", {}).get("result", {}).get("value")
print("rect:", rect_str)
rect = json.loads(rect_str)

r2 = c.call("Page.captureScreenshot", {"format": "png"})
data = r2.get("result", {}).get("data")
with open("C:/tmp/atomic_shot.png", "wb") as f:
    f.write(base64.b64decode(data))

from PIL import Image
img = Image.open("C:/tmp/atomic_shot.png")
crop = img.crop((int(rect["x"]), int(rect["y"]), int(rect["x"]+rect["w"]), int(rect["y"]+rect["h"])))
crop.save("C:/tmp/final_original_magikarp.png")
print("cropped size:", crop.size)
c.close()
