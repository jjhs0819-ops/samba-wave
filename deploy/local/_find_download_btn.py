# -*- coding: utf-8 -*-
import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Input.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

# 결과 이미지(1024짜리 큰 이미지) 클릭해서 라이트박스 열기
js = """
(function(){
  var imgs = Array.from(document.querySelectorAll('img'));
  var candidates = imgs.filter(i => i.naturalWidth >= 800);
  candidates.sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  if (!candidates.length) return 'NOT FOUND';
  candidates[0].click();
  return 'clicked';
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(2)

# 다운로드 버튼/아이콘 찾기
js2 = """
(function(){
  var els = Array.from(document.querySelectorAll('button, a, [role=button]'));
  return els.filter(e => (e.getAttribute('aria-label')||'').toLowerCase().includes('download') ||
                          (e.textContent||'').toLowerCase().includes('download'))
    .map(e => e.getAttribute('aria-label') || e.textContent.trim());
})()
"""
r2 = c.call("Runtime.evaluate", {"expression": js2, "returnByValue": True})
print("download candidates:", r2.get("result", {}).get("result", {}).get("value"))

r3 = c.call("Page.captureScreenshot", {"format": "png"})
data = r3.get("result", {}).get("data")
with open("C:/tmp/lightbox2.png", "wb") as f:
    f.write(base64.b64decode(data))
print("saved")
c.close()
