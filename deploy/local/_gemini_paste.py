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

# 프롬프트 입력창 클릭
click_js = """
(function(){
  var el = document.querySelector('[contenteditable="true"]');
  if (!el) return 'NOT FOUND';
  el.focus();
  el.click();
  var r = el.getBoundingClientRect();
  return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
})()
"""
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print("click:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(0.5)

# Ctrl+V
c.call("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "key": "Control"})
c.call("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "key": "v", "code": "KeyV", "windowsVirtualKeyCode": 86})
c.call("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "key": "v", "code": "KeyV", "windowsVirtualKeyCode": 86})
c.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Control"})
time.sleep(1.5)
c.close()
