# -*- coding: utf-8 -*-
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
url = ("https://www.ebay.com/sch/i.html?_nkw=a&_sacat=1&LH_Sold=1&LH_Complete=1"
       "&LH_LocatedIn=1&_salic=196&_sop=13&_ipg=120")
c.send("Page.navigate", {"url": url})
time.sleep(9)
t = js("document.body.innerText") or ""
m = re.search(r"([\d,]+)\+?\s*results", t)
k = len(re.findall(r"Located in South Korea|from South Korea", t))
n = js('document.querySelectorAll("li.s-item, li.s-card").length') or 0
print(f"결과={m.group(1) if m else '?'} | 항목{n} 중 한국발 표기 {k}")
rows = js("""JSON.stringify([...document.querySelectorAll('li.s-item, li.s-card')].slice(0,5).map(li=>{
  var t=(li.querySelector('.s-item__title,.s-card__title')||{}).innerText||'';
  var p=(li.querySelector('.s-item__price,.s-card__price')||{}).innerText||'';
  return (t+' | '+p).slice(0,70);}).filter(x=>x.length>5))""")
print("샘플:", rows)
c.close()
