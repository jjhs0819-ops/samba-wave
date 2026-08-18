# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:90]
    return res.get("result", {}).get("value")
print("클릭:", js("""(function(){var b=[...document.querySelectorAll('button')]
  .filter(e=>/^Submit\s*\(\d+\)/i.test((e.innerText||'').trim()) && !e.disabled);
  if(!b.length) return 'NOBTN'; b[0].click(); return 'clicked';})()"""))
time.sleep(12)
t = js("document.body.innerText") or ""
print("URL:", js("location.href")[:90])
import re
for pat in ["successfully", "성공", "listed", "error", "오류", "failed", "Submit"]:
    i = t.lower().find(pat.lower())
    if i >= 0:
        print(f"[{pat}] {t[max(0,i-60):i+110]}".replace("\n", " | ")[:220])
        break
c.close()
