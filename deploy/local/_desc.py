# -*- coding: utf-8 -*-
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
c.send("Page.navigate", {"url": f"https://www.ebay.com/itm/{sys.argv[2]}"})
time.sleep(9)
print("제목:", js("document.title")[:90])
# 설명은 iframe 안에 있음
ifr = js("""JSON.stringify([...document.querySelectorAll('iframe')].map(f=>f.id||f.name||f.src.slice(0,60)))""")
print("iframe:", ifr)
t = js("document.body.innerText") or ""
for pat in ["sealed", "Sealed", "미개봉", "unopened", "Unopened", "pack"]:
    for m in re.finditer(pat, t):
        i = m.start()
        seg = t[max(0,i-70):i+90].replace("\n"," | ")
        if "feedback" not in seg.lower() and "Feedback" not in seg:
            print(f"[{pat}] {seg[:180]}")
            break
c.close()
