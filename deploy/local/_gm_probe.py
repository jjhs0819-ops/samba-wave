# -*- coding: utf-8 -*-
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1])
c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
print("총 img:", js("document.querySelectorAll('img').length"))
print(js("""JSON.stringify([...document.querySelectorAll('img')].map(i=>({
  nw:i.naturalWidth, nh:i.naturalHeight, w:Math.round(i.getBoundingClientRect().width),
  src:(i.src||'').slice(0,45), alt:(i.alt||'').slice(0,25)
})))"""))
c.close()
