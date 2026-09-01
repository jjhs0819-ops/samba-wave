# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
# ESC로 열린 메뉴 닫기
for t in ("keyDown","keyUp"):
    c.call("Input.dispatchKeyEvent", {"type":t,"key":"Escape","code":"Escape","windowsVirtualKeyCode":27,"nativeVirtualKeyCode":27})
time.sleep(1)
js("(function(){var a=[...document.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().width>=300);if(a.length)a[a.length-1].scrollIntoView({block:'center'});})()")
time.sleep(1.5)
print("결과이미지 rect:", js("(function(){var a=[...document.querySelectorAll('img')].filter(i=>i.getBoundingClientRect().width>=300);if(!a.length)return null;var r=a[a.length-1].getBoundingClientRect();return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};})()"))
print(js("""JSON.stringify([...document.querySelectorAll('button')]
  .map(b=>{var r=b.getBoundingClientRect();return {al:(b.getAttribute('aria-label')||'').slice(0,25),
    tx:(b.innerText||'').trim().slice(0,14), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width)};})
  .filter(o=>o.w>0&&o.x>700))"""))
c.close()
