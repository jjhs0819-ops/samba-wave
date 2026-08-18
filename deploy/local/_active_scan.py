# -*- coding: utf-8 -*-
"""활성 리스팅 itemId 전량 수집 (페이지네이션 200/page)."""
import sys, os, time, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
found = set()
for page in range(1, 4):
    c.send("Page.navigate", {"url": f"https://www.ebay.com/sh/lst/active?limit=200&offset={(page-1)*200}"})
    time.sleep(11)
    html = js("document.body.innerHTML") or ""
    ids = set(re.findall(r"/itm/(\d{12})", html))
    before = len(found)
    found |= ids
    print(f"  page{page}: +{len(found)-before} (누적 {len(found)})", flush=True)
    if len(ids) < 5:
        break
json.dump(sorted(found), open("C:/tmp/active_ids.json", "w"))
print("활성 itemId 총:", len(found))
c.close()
