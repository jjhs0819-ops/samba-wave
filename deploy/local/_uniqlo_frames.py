# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "0BA049D95E6F9DB5BB599AAC50BF8C97"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

js = """
(function(){
  var frames = Array.from(document.querySelectorAll('iframe'));
  return frames.map(f => ({src: f.src, id: f.id, name: f.name}));
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
