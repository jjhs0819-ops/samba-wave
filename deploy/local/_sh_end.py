# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "8E18DEC4C2608D21C7C63F59FB213D7E"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

# 체크박스 선택 (첫 결과행)
js = """
(function(){
  var rows = document.querySelectorAll('table tbody tr, [role=row]');
  var boxes = Array.from(document.querySelectorAll('input[type=checkbox]'));
  var target = boxes.find(b => (b.getAttribute('aria-label')||'').includes('Zygarde'));
  if (!target) return 'checkbox NOT FOUND';
  target.click();
  return 'checked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(1)

# Actions 드롭다운 열기
js2 = """
(function(){
  var els = Array.from(document.querySelectorAll('button, [role=button]'));
  var t = els.find(e => e.textContent.trim().startsWith('Actions'));
  if (!t) return 'NOT FOUND';
  t.click();
  return 'clicked actions';
})()
"""
r2 = c.call("Runtime.evaluate", {"expression": js2, "returnByValue": True})
print(r2.get("result", {}).get("result", {}).get("value"))
time.sleep(1)

r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/sh_shot6.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
