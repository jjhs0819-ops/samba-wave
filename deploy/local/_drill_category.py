import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "ECEBED73F08CC270BB9FC8EF31BC3E9E"
CATEGORY_TEXT = sys.argv[1]
OUT = sys.argv[2]

c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

click_js = """
(function(){
  var all = Array.from(document.querySelectorAll('*'));
  var matches = all.filter(e => e.textContent.trim() === %s);
  if (matches.length === 0) return 'NO MATCH';
  // 가장 깊은(자식 적은) 요소 우선
  matches.sort((a,b) => a.children.length - b.children.length);
  var el = matches[0];
  var clickable = el.closest('a,button,[role=button],[tabindex],[class*=Card],[class*=card]') || el;
  clickable.click();
  return 'matches=' + matches.length + ' clicked=' + clickable.tagName + ' cls=' + (clickable.className||'').slice(0,80);
})()
""" % json.dumps(CATEGORY_TEXT)
r = c.call("Runtime.evaluate", {"expression": click_js, "returnByValue": True})
print(r.get("result", {}).get("result", {}).get("value"))
time.sleep(3)

r = c.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
text = r.get("result", {}).get("result", {}).get("value", "") or ""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(text)
print("len", len(text))
c.close()
