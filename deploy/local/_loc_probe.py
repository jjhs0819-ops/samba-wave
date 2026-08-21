# -*- coding: utf-8 -*-
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
def test(label, url):
    c.send("Page.navigate", {"url": url})
    time.sleep(8)
    t = js("document.body.innerText") or ""
    m = re.search(r"([\d,]+)\+?\s*results", t)
    k = len(re.findall(r"Located in South Korea|from South Korea", t))
    n = js('document.querySelectorAll("li.s-item, li.s-card").length') or 0
    print(f"{label}: 결과={m.group(1) if m else '?'} | 항목{n} 중 한국발 {k}")
# A) 활성 리스팅 + 위치필터 (판매완료 없이)
test("A 활성+KR", "https://www.ebay.com/sch/i.html?_nkw=a&_sacat=1&_sop=12&LH_SALocatedIn=1&_salic=196&_ipg=60")
# B) 판매완료 + 위치필터 + rt=nc
test("B 판매완료+KR+rt", "https://www.ebay.com/sch/i.html?_nkw=a&_sacat=1&LH_Sold=1&LH_Complete=1&LH_SALocatedIn=1&_salic=196&rt=nc&_ipg=60")
c.close()
