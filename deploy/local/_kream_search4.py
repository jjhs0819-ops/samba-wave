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

# 날짜필드 초기화 먼저
fill_js = """
(function(){
  var el = document.querySelector('input[placeholder*="모델번호"]');
  if (!el) return 'NOT FOUND';
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, 'Pokemon');
  el.dispatchEvent(new Event('input', {bubbles: true}));
  return el.value;
})()
"""
r = c.call("Runtime.evaluate", {"expression": fill_js, "returnByValue": True})
print("filled:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.5)

btn_js = """
(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  var searchBtn = btns.find(b => b.textContent.trim() === '검색');
  if (searchBtn) { searchBtn.click(); return 'clicked'; }
  return 'NO BUTTON';
})()
"""
r = c.call("Runtime.evaluate", {"expression": btn_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
c.close()
