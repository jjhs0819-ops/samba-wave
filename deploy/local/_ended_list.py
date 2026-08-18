# -*- coding: utf-8 -*-
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
rows = js("""JSON.stringify([...document.querySelectorAll('tr')].map(tr=>{
  var tx=(tr.innerText||'').replace(/\n/g,' | ').slice(0,150);
  var a=tr.querySelector('a[href*="/itm/"]');
  var id=a?(a.getAttribute('href').match(/itm\/(\d+)/)||[])[1]:null;
  return id?{id:id, tx:tx}:null;}).filter(Boolean))""")
d = json.loads(rows or "[]")
print("행수", len(d))
for x in d:
    print(x["id"], "|", x["tx"][:95])
c.close()
