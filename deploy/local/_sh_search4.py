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

js = """
(function(){
  var el = document.querySelector('input[placeholder="Search by title, SKU, or item number"]');
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, '398254962289');
  el.dispatchEvent(new Event('input', {bubbles: true}));
  return el.value;
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print("filled:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.5)

# 검색(돋보기) 아이콘 버튼 클릭 시도
click_js = """
(function(){
  var buttons = Array.from(document.querySelectorAll('button, [role=button]'));
  var t = buttons.find(b => (b.getAttribute('aria-label')||'').toLowerCase().includes('search'));
  if (t) { t.click(); return 'clicked search icon'; }
  return 'not found';
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2.5)

r = c.call("Page.captureScreenshot", {"format": "png"})
data = r.get("result", {}).get("data")
with open("C:/tmp/sh_shot4.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
