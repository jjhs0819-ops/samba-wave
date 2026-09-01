# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:90]
    return res.get("result", {}).get("value")
print(js("""JSON.stringify([...document.querySelectorAll('button')]
  .filter(b=>b.getBoundingClientRect().width>0 && !b.disabled)
  .map(b=>({t:(b.innerText||'').trim().slice(0,28), a:(b.getAttribute('aria-label')||'').slice(0,28)}))
  .filter(o=>o.t||o.a).slice(0,25))"""))
c.close()
