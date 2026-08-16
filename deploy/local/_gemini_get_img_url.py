# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

js = """
(function(){
  var imgs = Array.from(document.querySelectorAll('img'));
  return imgs.map(i => i.src).filter(s => s && !s.includes('data:image/svg'));
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
urls = r.get("result", {}).get("result", {}).get("value", [])
with open("C:/tmp/gemini_img_urls.json", "w", encoding="utf-8") as f:
    json.dump(urls, f, ensure_ascii=False, indent=2)
print(len(urls), "found")
c.close()
