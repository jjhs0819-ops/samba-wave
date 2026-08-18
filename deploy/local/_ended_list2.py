# -*- coding: utf-8 -*-
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
html = js("document.body.innerHTML") or ""
ids = sorted(set(re.findall(r"/itm/(\d{12})", html)))
print("발견 itemId:", len(ids))
for i in ids:
    print(" ", i)
txt = js("document.body.innerText") or ""
open("C:/tmp/ended_txt.txt", "w", encoding="utf-8").write(txt)
c.close()
