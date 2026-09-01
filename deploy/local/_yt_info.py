# -*- coding: utf-8 -*-
import sys, os, time, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
import urllib.request
tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9223/json/list", timeout=6).read())
tab = next(t["id"] for t in tabs if t.get("type")=="page" and "youtube" in (t.get("url") or ""))
c = CDPConn(tab); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC"
    return res.get("result", {}).get("value")
time.sleep(4)
print("채널:", js("(document.querySelector('#owner #channel-name a')||{}).innerText"))
print("제목:", js("(document.querySelector('h1.ytd-watch-metadata')||{}).innerText"))
# 더보기 클릭해 설명 펼치기
js("(function(){var b=document.querySelector('#expand'); if(b) b.click();})()")
time.sleep(2)
print("설명:", (js("(document.querySelector('#description-inline-expander')||{}).innerText") or "")[:800])
print("길이/조회:", js("(document.querySelector('#info-container')||{}).innerText"))
c.close()
