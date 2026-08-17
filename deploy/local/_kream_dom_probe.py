# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:90]
    return res.get("result", {}).get("value")
print("URL:", js("location.href"))
print("a 총개수:", js("document.querySelectorAll('a').length"))
print("products 앵커:", js("document.querySelectorAll('a[href*=\"/products/\"]').length"))
print("본문길이:", js("document.body.innerText.length"))
print("샘플 href:", js("JSON.stringify([...document.querySelectorAll('a')].slice(0,8).map(a=>a.getAttribute('href')))"))
c.close()
