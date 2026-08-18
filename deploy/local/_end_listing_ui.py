# -*- coding: utf-8 -*-
"""Seller Hub 에서 특정 리스팅 검색 → 선택 → End listings."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab, item = sys.argv[1], sys.argv[2]
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")

c.send("Page.navigate", {"url": f"https://www.ebay.com/sh/lst/active?q={item}&searchField=all"})
time.sleep(9)
txt = js("document.body.innerText") or ""
print("리스팅 표시:", item in txt)
rows = js("""JSON.stringify([...document.querySelectorAll('input[type=checkbox]')]
  .map((b,i)=>({i, name:b.getAttribute('name')||'', aria:(b.getAttribute('aria-label')||'').slice(0,40)}))
  .filter(o=>o.aria||o.name).slice(0,8))""")
print("체크박스:", rows)
c.close()
