# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
c.send("Page.navigate", {"url": "https://www.ebay.com/sh/lst/active?limit=200"})
time.sleep(11)
print(js("""JSON.stringify([...document.querySelectorAll('th')].map(t=>(t.innerText||'').trim().slice(0,22)))"""))
c.close()
