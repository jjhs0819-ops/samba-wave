# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:90]
    return res.get("result", {}).get("value")
print(js("""JSON.stringify([...document.querySelectorAll('button,a,input[type=submit],[role=button]')]
  .filter(e=>/relist|list it|submit|저장|등록/i.test((e.innerText||'')+(e.value||'')+(e.getAttribute('aria-label')||'')))
  .map(e=>{var r=e.getBoundingClientRect();return {
    tag:e.tagName, t:((e.innerText||e.value||'').trim()).slice(0,30),
    dis:!!e.disabled, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width)};})
  .filter(o=>o.w>0).slice(0,15))"""))
c.close()
