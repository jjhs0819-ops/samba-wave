# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "0BA049D95E6F9DB5BB599AAC50BF8C97"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(1)

click_js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input'));
  var el = inputs.find(i => i.value && i.value.indexOf('都道府県') >= 0);
  if (!el) return 'NOT FOUND';
  var r = el.getBoundingClientRect();
  el.focus();
  el.click();
  return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value")
print("click:", val)
time.sleep(0.5)

# 텍스트 입력
setter_js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input'));
  var el = inputs.find(i => i.value && i.value.indexOf('都道府県') >= 0);
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, '東京都');
  el.dispatchEvent(new Event('input', {bubbles: true}));
  return el.value;
})()
"""
r = c.call("Runtime.evaluate", {"expression": setter_js, "returnByValue": True})
print("input:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(1)

# 드롭다운 옵션 찾기
list_js = """
(function(){
  var opts = Array.from(document.querySelectorAll('li, [role=option]'));
  var matches = opts.filter(o => o.textContent.trim() === '東京都');
  return matches.length;
})()
"""
r = c.call("Runtime.evaluate", {"expression": list_js, "returnByValue": True})
print("options found:", r.get("result", {}).get("result", {}).get("value"))
c.close()
