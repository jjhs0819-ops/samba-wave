# -*- coding: utf-8 -*-
"""비활성 목록에서 지정한 itemId 행만 체크 → Relist 버튼 클릭."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

TARGETS = ["398276572065","398279900842","398279901688","398279903071","398279991273",
           "398279991457","398279991576","398279991734","398279992025","398279992391",
           "398279992536","398279992699","398279993074","398279993234","398279993439",
           "398279993634","398279998305"]
EXCLUDE = ["398202769232"]

c = CDPConn(sys.argv[1]); c.call("Runtime.enable"); c.call("Page.enable"); c.call("Page.bringToFront")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True})
    res = r.get("result", {})
    if "exceptionDetails" in res: return "EXC " + str(res["exceptionDetails"].get("text"))[:90]
    return res.get("result", {}).get("value")

checked = js("""(function(ids, excl){
  var done=0, skipped=0;
  var rows=[...document.querySelectorAll('tr')];
  for (const tr of rows){
    var a=tr.querySelector('a[href*="/itm/"]');
    if(!a) continue;
    var m=(a.getAttribute('href')||'').match(/itm\/(\d+)/);
    if(!m) continue;
    var id=m[1];
    if(excl.includes(id)){ skipped++; continue; }
    if(!ids.includes(id)) continue;
    var cb=tr.querySelector('input[type=checkbox]');
    if(cb && !cb.checked){ cb.click(); done++; }
  }
  return JSON.stringify({checked:done, skipped:skipped});
})(""" + json.dumps(TARGETS) + "," + json.dumps(EXCLUDE) + ")")
print("체크 결과:", checked)
time.sleep(1)
btn = js("""(function(){var b=[...document.querySelectorAll('button,a')]
  .filter(e=>/^Relist$/i.test((e.innerText||'').trim()) && !e.disabled);
  return b.length;})()""")
print("활성 Relist 버튼:", btn)
c.close()
