# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

# 브라우저 다운로드 경로 설정
c.call("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": "C:\\tmp\\gemini_downloads"})

js = """
(function(){
  var x = 1703, y = 32; // 다운로드 아이콘 대략 좌표
  var el = document.elementFromPoint(x, y);
  if (el) { el.click(); return 'clicked via point: ' + el.outerHTML.slice(0,100); }
  return 'no element';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)
c.close()
