# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "E2173D61159838FBE58BEC5F8F64D7D0"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

fill_js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
  var el = inputs[2];
  if (!el) return 'NOT FOUND';
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, '포켓몬');
  el.dispatchEvent(new Event('input', {bubbles: true}));
  return el.value;
})()
"""
r = c.call("Runtime.evaluate", {"expression": fill_js, "returnByValue": True})
print("filled:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.5)

enter_js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
  var el = inputs[2];
  el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', keyCode: 13, bubbles: true}));
  el.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', keyCode: 13, bubbles: true}));
  var btns = Array.from(document.querySelectorAll('button'));
  var searchBtn = btns.find(b => b.textContent.trim() === '검색');
  if (searchBtn) { searchBtn.click(); return 'clicked search btn'; }
  return 'enter dispatched only';
})()
"""
r = c.call("Runtime.evaluate", {"expression": enter_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
