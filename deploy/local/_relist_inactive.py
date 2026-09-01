# -*- coding: utf-8 -*-
"""Seller Hub 비활성 목록에서 전체 선택 → Relist."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:80]
    return res.get("result", {}).get("value")

c.send("Page.navigate", {"url": "https://www.ebay.com/sh/lst/ended"})
time.sleep(10)
print("URL:", js("location.href"))
txt = js("document.body.innerText") or ""
import re
m = re.search(r"Results:\s*([\d\-]+)\s*of\s*(\d+)", txt)
print("결과수:", m.group(0) if m else "못찾음")
print("Relist 링크 수:", js("[...document.querySelectorAll('a,button')].filter(e=>/^Relist$/i.test((e.innerText||'').trim())).length"))
c.close()
