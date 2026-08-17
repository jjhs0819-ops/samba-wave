# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "BB98FD3FE1D268DE58FD3A0350077392"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

js = """
(function(){
  var img = document.querySelector('img[src*="ebayimg"]');
  if (!img) return 'NOT FOUND';
  return JSON.stringify({src: img.src, natW: img.naturalWidth, natH: img.naturalHeight, dispW: img.width, dispH: img.height});
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
