# -*- coding: utf-8 -*-
import sys, os, time, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab = sys.argv[1]
c = CDPConn(tab); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
c.send("Page.navigate", {"url": "https://www.ebay.com/sch/ebayadvsearch"})
time.sleep(7)
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:80]
    return res.get("result", {}).get("value")
# 위치 관련 input/select 이름 전수 출력
print(js("""JSON.stringify([...document.querySelectorAll('input,select')]
  .filter(e=>/loc|salic|country|prefloc/i.test(e.name||'')||/loc/i.test(e.id||''))
  .map(e=>({tag:e.tagName,name:e.name,id:e.id,type:e.type||'',
    opts:e.tagName==='SELECT'?[...e.options].slice(0,3).map(o=>o.value+':'+o.text.slice(0,12)):null})))"""))
c.close()
