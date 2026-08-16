# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "E2173D61159838FBE58BEC5F8F64D7D0"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input'));
  return inputs.map(function(el, i){
    return {i: i, type: el.type, placeholder: el.placeholder};
  });
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
with open("C:/tmp/kream_fields2.json", "w", encoding="utf-8") as f:
    json.dump(r.get("result", {}).get("result", {}).get("value", []), f, ensure_ascii=False, indent=2)
print("done")
c.close()
