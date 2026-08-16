# -*- coding: utf-8 -*-
import sys, os, time
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
  if (!el) return 'NOT FOUND';
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, '398254962289');
  el.dispatchEvent(new Event('input', {bubbles: true}));
  return el.value;
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print("filled:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.3)

enter_js = """
(function(){
  var el = document.querySelector('input[placeholder="Search by title, SKU, or item number"]');
  el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', keyCode: 13, bubbles: true}));
  el.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', keyCode: 13, bubbles: true}));
  var form = el.closest('form');
  if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
  return 'done';
})()
"""
r = c.call("Runtime.evaluate", {"expression": enter_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2.5)

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/sh_search_result2.txt", "w", encoding="utf-8") as f:
    f.write(text[:3000])
print("len", len(text))
c.close()
