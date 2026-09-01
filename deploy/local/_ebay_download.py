# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "8E18DEC4C2608D21C7C63F59FB213D7E"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

# 다운로드 경로 설정
c.call("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": "C:\\tmp"})

js = """
(function(){
  var els = Array.from(document.querySelectorAll('button, a'));
  var t = els.find(e => e.textContent.trim() === 'Download');
  if (!t) return 'NOT FOUND';
  t.click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open("C:/tmp/ebay_after_download_click.txt", "w", encoding="utf-8") as f:
    f.write(text[-2000:])
c.close()
