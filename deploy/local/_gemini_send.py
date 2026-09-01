# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

click_js = """
(function(){
  var el = document.querySelector('[contenteditable="true"]');
  if (!el) return 'NOT FOUND';
  el.focus();
  return 'focused';
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.3)

insert_js = """
(function(text){
  var el = document.querySelector('[contenteditable="true"]');
  el.focus();
  document.execCommand('insertText', false, text);
  return el.innerText;
})('카드만 이 카드로 바꿔')
"""
r = c.call("Runtime.evaluate", {"expression": insert_js, "returnByValue": True})
print("typed:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.5)

c.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "windowsVirtualKeyCode": 13})
c.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "windowsVirtualKeyCode": 13})
time.sleep(3)
c.close()
