# -*- coding: utf-8 -*-
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
t = js("document.body.innerText") or ""
for pat in ["This listing was ended", "no longer available", "ended by the seller",
            "Buy It Now", "Add to cart", "Sold", "Out of stock", "Ended"]:
    if pat.lower() in t.lower():
        print("발견:", pat)
i = t.lower().find("this listing")
print("문맥:", t[max(0,i-60):i+160].replace("\n"," | ") if i >= 0 else "없음")
c.close()
