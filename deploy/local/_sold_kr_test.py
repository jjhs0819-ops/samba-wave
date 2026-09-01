# -*- coding: utf-8 -*-
"""키워드 'a' + 한국발(_salic=196) + 판매완료 검증."""
import sys, os, time, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
kw = sys.argv[2] if len(sys.argv) > 2 else "a"
cat = sys.argv[3] if len(sys.argv) > 3 else "1"
url = (f"https://www.ebay.com/sch/i.html?_nkw={kw}&_sacat={cat}"
       f"&LH_Sold=1&LH_Complete=1&_sop=13&LH_SALocatedIn=1&_salic=196&_ipg=120")
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
c.send("Page.navigate", {"url": url})
time.sleep(9)
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
print("URL:", (js("location.href") or "")[:130])
t = js("document.body.innerText") or ""
m = re.search(r"([\d,]+)\+?\s*results", t)
print("결과수:", m.group(0) if m else "표시없음")
rows = js("""JSON.stringify([...document.querySelectorAll('li.s-item, li.s-card')].slice(0,6).map(li=>{
  var t=(li.querySelector('.s-item__title,.s-card__title')||{}).innerText||'';
  var p=(li.querySelector('.s-item__price,.s-card__price')||{}).innerText||'';
  var l=(li.querySelector('.s-item__location,.s-item__itemLocation,.s-card__location')||{}).innerText||'';
  var d=(li.querySelector('.s-item__title--tagblock,.s-item__caption,.s-card__caption')||{}).innerText||'';
  return {t:t.slice(0,48),p:p.slice(0,16),l:l.slice(0,22),d:d.slice(0,22)};
}).filter(o=>o.t))""")
print("샘플:", rows)
c.close()
