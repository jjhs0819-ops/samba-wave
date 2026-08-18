# -*- coding: utf-8 -*-
"""활성 목록에서 itemId → 제목/SKU 추출 (고아 정체 파악용)."""
import sys, os, time, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
out = {}
for page in range(2):
    c.send("Page.navigate", {"url": f"https://www.ebay.com/sh/lst/active?limit=200&offset={page*200}"})
    time.sleep(11)
    rows = js("""JSON.stringify([...document.querySelectorAll('tr')].map(tr=>{
      var a=tr.querySelector('a[href*="/itm/"]'); if(!a) return null;
      var m=(a.getAttribute('href')||'').match(/itm.(\d{12})/); if(!m) return null;
      var tds=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').trim());
      return {id:m[1], title:(a.innerText||'').trim().slice(0,60), cells:tds.slice(0,8)};
    }).filter(Boolean))""")
    for x in json.loads(rows or "[]"):
        out[x["id"]] = x
json.dump(out, open("C:/tmp/active_detail.json", "w", encoding="utf-8"), ensure_ascii=False)
print("수집", len(out))
c.close()
