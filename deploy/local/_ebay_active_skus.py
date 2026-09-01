# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "8E18DEC4C2608D21C7C63F59FB213D7E"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(1)

# 페이지당 200개로 변경 시도
js_set_page_size = """
(function(){
  var links = Array.from(document.querySelectorAll('a, button, [role=button]'));
  var t = links.find(l => l.textContent.trim() === '200');
  if (t) { t.click(); return 'clicked 200'; }
  return 'not found 200 option';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js_set_page_size, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)

all_skus = set()
for page in range(1, 4):
    r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
    text = r.get("result", {}).get("result", {}).get("value", "") or ""
    with open(f"C:/tmp/ebay_active_page{page}.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print(f"page{page} len", len(text))
    # 다음 페이지 버튼
    next_js = """
    (function(){
      var btns = Array.from(document.querySelectorAll('button, a'));
      var t = btns.find(b => (b.getAttribute('aria-label')||'').includes('Next') || b.textContent.trim() === 'Next');
      if (t && !t.disabled) { t.click(); return 'clicked next'; }
      return 'no next';
    })()
    """
    r2 = c.call("Runtime.evaluate", {"expression": next_js, "returnByValue": True})
    res = r2.get("result", {}).get("result", {}).get("value")
    print("  ", res)
    if res != "clicked next":
        break
    time.sleep(2)

c.close()
