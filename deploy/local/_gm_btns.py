# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
print(js("""JSON.stringify([...document.querySelectorAll('button')]
  .map(b=>({al:(b.getAttribute('aria-label')||'').slice(0,22), tx:(b.innerText||'').trim().slice(0,18),
            w:Math.round(b.getBoundingClientRect().width), y:Math.round(b.getBoundingClientRect().y)}))
  .filter(o=>o.w>0 && o.y>250))"""))
c.close()
