# -*- coding: utf-8 -*-
import sys, os, time, re, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
for kw in ["zenless+ban+olim+pizza+code", "zenless+zone+zero+pizza+redeem+code", "arknights+endfield+frank+burger+code"]:
    url = f"https://www.ebay.com/sch/i.html?_nkw={kw}&LH_Sold=1&LH_Complete=1&_sop=13&_ipg=60"
    c.send("Page.navigate", {"url": url})
    time.sleep(8)
    t = js("document.body.innerText") or ""
    m = re.search(r"([\d,]+)\+?\s*results", t)
    rows = js("""JSON.stringify([...document.querySelectorAll('li.s-item, li.s-card')].slice(0,5).map(li=>{
      var t=(li.querySelector('.s-item__title,.s-card__title')||{}).innerText||'';
      var p=(li.querySelector('.s-item__price,.s-card__price')||{}).innerText||'';
      return (t.slice(0,55)+' || '+p.slice(0,12));}).filter(x=>x.length>15))""")
    print(f"[{kw}] {m.group(0) if m else '0'}")
    import json as J
    for r in J.loads(rows or "[]"):
        print("  ", r)
c.close()
