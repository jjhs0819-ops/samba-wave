# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("DOM.enable")
c.call("Page.bringToFront")
time.sleep(1)

# "+" 버튼 클릭해서 첨부 메뉴 열기
plus_js = """
(function(){
  var btns = Array.from(document.querySelectorAll('button'));
  // 입력창 근처의 + 버튼 (aria-label 후보)
  var target = btns.find(b => (b.getAttribute('aria-label')||'').includes('파일') ||
                               (b.getAttribute('aria-label')||'').includes('업로드') ||
                               (b.getAttribute('aria-label')||'').includes('첨부'));
  if (!target) {
    // fallback: 입력창 바로 앞의 버튼
    var input = document.querySelector('[contenteditable="true"], textarea, input[placeholder*="물어보기"]');
    if (input) {
      var container = input.closest('div');
      target = container ? container.parentElement.querySelector('button') : null;
    }
  }
  if (!target) return 'NOT FOUND';
  target.click();
  return 'clicked: ' + (target.getAttribute('aria-label')||target.outerHTML.slice(0,80));
})()
"""
r = c.call("Runtime.evaluate", {"expression": plus_js, "returnByValue": True})
print("plus click:", r.get("result", {}).get("result", {}).get("value"))
time.sleep(1)

menu_js = """
(function(){
  var all = Array.from(document.querySelectorAll('*'));
  return all.filter(e => e.children.length===0 && e.textContent.trim().length>0 && e.textContent.trim().length<20)
    .map(e => e.textContent.trim()).slice(-30);
})()
"""
r = c.call("Runtime.evaluate", {"expression": menu_js, "returnByValue": True})
print("visible short texts:", r.get("result", {}).get("result", {}).get("value"))

# input[type=file] 찾기
doc = c.call("DOM.getDocument", {"depth": -1, "pierce": True})
root_id = doc["result"]["root"]["nodeId"]
found = c.call("DOM.querySelectorAll", {"nodeId": root_id, "selector": "input[type=file]"})
node_ids = found.get("result", {}).get("nodeIds", [])
print("file input nodeIds:", node_ids)

if node_ids:
    r = c.call("DOM.setFileInputFiles", {
        "nodeId": node_ids[0],
        "files": ["C:\\tmp\\out_v3.jpg", "C:\\tmp\\blastoise_shot.png"],
    })
    print("setFileInputFiles:", r)

c.close()
