# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "A8BB045184BAD50A6BB12EB37EC65FDD"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(3)

fill_js = """
(function(){
  var input = document.querySelector('input[placeholder="검색어"]');
  if (!input) return 'NOT FOUND';
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, 'cp_01M04Z5ZRQF5ER358VG6GHGDBB');
  input.dispatchEvent(new Event('input', {bubbles: true}));
  return 'filled';
})()
"""
r = c.call("Runtime.evaluate", {"expression": fill_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.5)

time.sleep(0.3)
click_js = """
(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  var target = btns.find(b => b.textContent.trim() === '검색');
  if (!target) return 'NOT FOUND';
  target.click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print("search click:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)

r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/products_search.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
