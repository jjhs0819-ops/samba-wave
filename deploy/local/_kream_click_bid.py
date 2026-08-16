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
  var btns = Array.from(document.querySelectorAll('button'));
  var target = btns.find(b => b.textContent.trim() === '판매 입찰하기');
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
