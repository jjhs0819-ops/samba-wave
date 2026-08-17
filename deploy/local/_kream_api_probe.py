# -*- coding: utf-8 -*-
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
c = CDPConn(sys.argv[1]); c.call("Runtime.enable")
def js(e):
    r = c.call("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return "EXC " + str(res["exceptionDetails"].get("text"))[:100]
    return res.get("result", {}).get("value")
url = ("https://api.kream.co.kr/api/fetch/brands/Pokemon%20TCG/tabs/all"
       "?sort=recommend&cursor=1&shop_category_id=209&per_page=100")
out = js(f"""(async()=>{{
  const r = await fetch("{url}", {{credentials:'include'}});
  const j = await r.json();
  const keys = Object.keys(j);
  let items = j.items || j.data || j.products || [];
  return JSON.stringify({{status:r.status, keys:keys, n:(items&&items.length)||0,
    sample: items && items[0] ? JSON.stringify(items[0]).slice(0,700) : null,
    meta: JSON.stringify(Object.fromEntries(keys.filter(k=>k!=='items'&&k!=='data').map(k=>[k, j[k]]))).slice(0,400)}});
}})()""")
print(out)
c.close()
