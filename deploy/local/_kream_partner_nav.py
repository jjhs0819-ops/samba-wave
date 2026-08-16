# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "E2173D61159838FBE58BEC5F8F64D7D0"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

click_js = """
(function(){
  var els = Array.from(document.querySelectorAll('*'));
  var target = els.find(e => e.textContent.trim() === '보관 판매 입찰' && e.children.length === 0);
  if (!target) return 'NOT FOUND';
  target.click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)
r = c.call("Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
