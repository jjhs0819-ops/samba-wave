# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "A8BB045184BAD50A6BB12EB37EC65FDD"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

js = """
(function(){
  var selects = Array.from(document.querySelectorAll('select'));
  return selects.map(s => ({
    value: s.value,
    options: Array.from(s.options).map(o => ({value: o.value, text: o.text}))
  }));
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
with open("C:/tmp/dropdowns.json", "w", encoding="utf-8") as f:
    json.dump(r.get("result", {}).get("result", {}).get("value", []), f, ensure_ascii=False, indent=2)
print("done")
c.close()
