# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "413B2AD8658332F0A44B021FD2389266"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

click_js = """
(function(){
  var els = Array.from(document.querySelectorAll('*'));
  var target = els.find(e => e.textContent.trim() === "I didn't receive the return" && e.children.length === 0);
  if (!target) return 'NOT FOUND';
  target.click();
  return 'clicked: ' + target.tagName;
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(1)

r = c.call("Runtime.evaluate", {"expression": "document.getElementById('res-combobox').value", "returnByValue": True})
print("combobox value:", r.get("result", {}).get("result", {}).get("value"))
c.close()
