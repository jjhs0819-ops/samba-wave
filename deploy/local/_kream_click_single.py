# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
ok = js("""(function(){var t=[...document.querySelectorAll('button,a,span,div')]
  .filter(e=>(e.innerText||'').trim()==='싱글 카드' && e.getBoundingClientRect().width>0);
  if(!t.length) return 'NOBTN';
  t[0].click(); return 'clicked '+t.length;})()""")
print("싱글카드 클릭:", ok)
time.sleep(3)
print("URL:", js("location.href"))
c.close()
