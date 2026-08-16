# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "8E18DEC4C2608D21C7C63F59FB213D7E"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)
c.send("Page.navigate", {"url": "https://www.ebay.com/sh/lst/active"})
time.sleep(3)

js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input'));
  return inputs.map(i => ({placeholder: i.placeholder, type: i.type, ariaLabel: i.getAttribute('aria-label')}));
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
with open("C:/tmp/sh_inputs.json", "w", encoding="utf-8") as f:
    json.dump(r.get("result", {}).get("result", {}).get("value", []), f, ensure_ascii=False, indent=2)
print("done")
c.close()
