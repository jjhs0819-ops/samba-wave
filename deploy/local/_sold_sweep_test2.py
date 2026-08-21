# -*- coding: utf-8 -*-
"""브라우즈 페이지로 리다이렉트 회피 — _dmd=1 + 정확한 sch 경로, 국가코드 필터."""
import sys, os, time, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
# LH_ItemLocationCountry=KR 로 국가 지정 (지역코드 대신)
url = ("https://www.ebay.com/sch/i.html?_nkw=&_sacat=1&LH_Sold=1&LH_Complete=1"
       "&_sop=13&LH_ItemLocationCountry=KR&_ipg=60")
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
c.send("Page.navigate", {"url": url})
time.sleep(9)
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
print("URL:", (js("location.href") or "")[:120])
t = js("document.body.innerText") or ""
m = re.search(r"([\d,]+)\+?\s*(?:results|개)", t)
print("결과수:", m.group(0) if m else "표시없음")
items = js("""JSON.stringify([...document.querySelectorAll('.s-item__title, .s-card__title, h3')].slice(0,8).map(e=>(e.innerText||'').trim().slice(0,55)).filter(Boolean))""")
print("상위:", items)
loc = js("""JSON.stringify([...document.querySelectorAll('.s-item__location, .s-card__location, .s-item__itemLocation')].slice(0,5).map(e=>e.innerText||''))""")
print("위치:", loc)
c.close()
