# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "413B2AD8658332F0A44B021FD2389266"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1.5)

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/ebay_appeal_page.txt", "w", encoding="utf-8") as f:
    f.write(text)

js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input, select, textarea, button'));
  return inputs.map(function(el){
    return {tag: el.tagName, type: el.type, id: el.id, name: el.name,
            placeholder: el.placeholder||'', text: (el.textContent||'').trim().slice(0,60)};
  });
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
with open("C:/tmp/ebay_appeal_fields.json", "w", encoding="utf-8") as f:
    json.dump(r.get("result", {}).get("result", {}).get("value", []), f, ensure_ascii=False, indent=2)

print("done, textlen", len(text))
c.close()
