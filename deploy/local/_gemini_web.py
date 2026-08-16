# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("DOM.enable")
c.call("Page.bringToFront")
time.sleep(2)

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/gemini_page.txt", "w", encoding="utf-8") as f:
    f.write(text[:3000])
print("len", len(text))

# input[type=file] 찾기
js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input[type=file]'));
  return inputs.map(i => ({id: i.id, accept: i.accept}));
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print("file inputs:", r.get("result", {}).get("result", {}).get("value"))
c.close()
