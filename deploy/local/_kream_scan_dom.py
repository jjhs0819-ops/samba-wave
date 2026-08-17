# -*- coding: utf-8 -*-
"""크림 브랜드 목록 → 상품ID 전량 수집 (DOM 앵커 스크레이핑 + 무한스크롤)."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab, out_path = sys.argv[1], sys.argv[2]
max_sec = int(sys.argv[3]) if len(sys.argv) > 3 else 600

c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")

found = set()
t0 = time.time(); last_new = time.time()
while time.time() - t0 < max_sec:
    ids = js("""JSON.stringify([...new Set([...document.querySelectorAll('a[href*="/products/"]')]
      .map(a=>(a.getAttribute('href')||'').match(/\/products\/(\d+)/)).filter(Boolean).map(m=>m[1]))])""")
    if ids:
        before = len(found)
        found.update(json.loads(ids))
        if len(found) > before:
            last_new = time.time()
            if len(found) % 200 < 60:
                print(f"  수집 {len(found)}", flush=True)
    js("window.scrollBy(0, 5000)")
    time.sleep(1.2)
    if time.time() - last_new > 40:
        break

json.dump(sorted(found), open(out_path, "w", encoding="utf-8"))
print("총 수집:", len(found), "->", out_path)
c.close()
