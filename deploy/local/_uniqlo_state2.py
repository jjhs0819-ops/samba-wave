# -*- coding: utf-8 -*-
import sys, os, time, json
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
  var sel = document.querySelector('select[name=state]');
  if (!sel) return 'NO SELECT';
  var opts = Array.from(sel.options).map(o => ({value:o.value, text:o.text}));
  return JSON.stringify({current: sel.value, options: opts.slice(0,50)});
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value")
with open("C:/tmp/uniqlo_state_options.txt", "w", encoding="utf-8") as f:
    f.write(val or "")
print("saved")
c.close()
