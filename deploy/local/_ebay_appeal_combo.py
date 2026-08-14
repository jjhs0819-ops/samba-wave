# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "413B2AD8658332F0A44B021FD2389266"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

click_js = """
(function(){
  var el = document.getElementById('res-combobox');
  el.click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(1)

opts_js = """
(function(){
  var opts = Array.from(document.querySelectorAll('li, [role=option]'));
  return opts.map(o => o.textContent.trim()).filter(t => t);
})()
"""
r = c.call("Runtime.evaluate", {"expression": opts_js, "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value")
with open("C:/tmp/ebay_appeal_options.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(val or []))
print("saved", len(val or []))
c.close()
