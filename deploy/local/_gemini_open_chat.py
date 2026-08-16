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

click_js = """
(function(){
  var els = Array.from(document.querySelectorAll('*'));
  var target = els.find(e => e.textContent.trim() === '포스트잇 옆 잉어킹 카드 교체' && e.children.length === 0);
  if (!target) return 'NOT FOUND';
  target.click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(3)
r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/gemini_chat.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("len", len(text))
c.close()
