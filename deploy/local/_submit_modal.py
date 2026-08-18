# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:90]
    return res.get("result", {}).get("value")
print(js("""JSON.stringify([...document.querySelectorAll('button')]
  .filter(e=>/submit/i.test(e.innerText||''))
  .map(e=>{var r=e.getBoundingClientRect();
    var inDlg=!!e.closest('[role=dialog],[class*=dialog],[class*=modal],[class*=lightbox]');
    return {t:(e.innerText||'').trim().slice(0,20), dlg:inDlg, dis:!!e.disabled,
            x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), w:Math.round(r.width)};})
  .filter(o=>o.w>0))"""))
c.close()
