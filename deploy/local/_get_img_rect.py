# -*- coding: utf-8 -*-
import sys, os, time
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
  return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height, natW: target.naturalWidth, natH: target.naturalHeight});
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
