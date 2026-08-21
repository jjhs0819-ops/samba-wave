# -*- coding: utf-8 -*-
"""키워드 없이 카테고리+한국발+판매완료 필터가 먹히는지 검증."""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
# 테스트: Collectibles(1) 카테고리, 한국발, 판매완료, 최근판매순
url = ("https://www.ebay.com/sch/1/i.html?_nkw=&LH_Sold=1&LH_Complete=1"
       "&_sop=13&LH_ItemLocationRegion=3&rt=nc")
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
c.send("Page.navigate", {"url": url})
time.sleep(9)
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
t = js("document.body.innerText") or ""
m = re.search(r"([\d,]+)\+?\s*results", t)
print("URL:", js("location.href")[:110])
print("결과수:", m.group(0) if m else "표시없음")
# 상위 항목 몇 개
items = js("""JSON.stringify([...document.querySelectorAll('.s-item__title, .s-card__title')].slice(1,8).map(e=>(e.innerText||'').slice(0,60)))""")
print("상위 항목:", items)
# 위치 표시 확인
loc = js("""JSON.stringify([...document.querySelectorAll('.s-item__location, .s-card__location')].slice(0,5).map(e=>(e.innerText||'')))""")
print("위치 표기:", loc)
c.close()
