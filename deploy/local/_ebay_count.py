# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
c.send("Page.navigate", {"url": "https://www.ebay.com/sh/lst/active"})
time.sleep(8)
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
txt = js("document.body.innerText") or ""
open("C:/tmp/ebay_active.txt","w",encoding="utf-8").write(txt)
import re
m = re.findall(r"(\d[\d,]*)\s*(?:개\s*)?(?:results?|items?|listings?)", txt, re.I)
print("페이지 내 숫자후보:", m[:8])
for line in txt.splitlines():
    if re.search(r"Active|활성|results|Showing", line, re.I) and len(line) < 90:
        print("|", line.strip())
c.close()
