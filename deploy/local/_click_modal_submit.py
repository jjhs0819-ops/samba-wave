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
print("모달 Submit 클릭:", js("""(function(){var b=[...document.querySelectorAll('button')]
  .filter(e=>/^Submit$/i.test((e.innerText||'').trim())
     && e.closest('[role=dialog],[class*=dialog],[class*=modal],[class*=lightbox]') && !e.disabled);
  if(!b.length) return 'NOBTN'; b[0].click(); return 'clicked';})()"""))
time.sleep(15)
print("URL:", (js("location.href") or "")[:80])
t = js("document.body.innerText") or ""
for pat in ["successfully","성공적","listed","Congratulations","error","오류","failed","submitted"]:
    i = t.lower().find(pat.lower())
    if i >= 0:
        print(f"[{pat}] {t[max(0,i-70):i+120]}".replace("\n"," | ")[:230]); break
else:
    print("본문 앞부분:", t[:200].replace("\n"," | "))
c.close()
