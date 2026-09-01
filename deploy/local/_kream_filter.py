# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    return r.get("result", {}).get("result", {}).get("value")
print("현재 URL:", js("location.href"))
# 필터 버튼 텍스트 후보 나열
print(js("""JSON.stringify([...document.querySelectorAll('button,a,span,div')]
  .map(e=>(e.innerText||'').trim())
  .filter(t=>/^(싱글 카드|카드 박스|카드 팩|10만원 이하|20만원 이하|20만원대|필터)$/.test(t))
  .slice(0,20))"""))
c.close()
