# -*- coding: utf-8 -*-
import sys, os, time, base64, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
url = "https://lh3.googleusercontent.com/gg/ACRwjavYqT80VtheaSfPxvZwKInx9S8hjmQ6ybatMRv6syfUvEYZieAcBk9Qp5UdUvm5mCj2udyqyQuVRrHf1ADAXsgdeppPTOHPClpWULO-Gk7ex5kK4l5glym5E24VNNMd3hu_K_ohKknjGQlL8fxQMC9SrYVUBOq2mBgxvuiUeMf0V0ZhYeJBhQNEfOdEgcEPIyN1wBywcdAsrzb-v201VrBEBOnnzweIrN0CJvFbXCkcWvyg7Y0KKf88GxXg8omEIdpj_uIyLIjAiTYLBAbM2BYJmrygoVlFreA"

c = CDPConn(tab_id, timeout=60)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

js = """
(async function(){
  try {
    var resp = await fetch(%s, {credentials: 'include'});
    if (!resp.ok) return 'HTTP_' + resp.status;
    var blob = await resp.blob();
    var reader = new FileReader();
    return await new Promise((resolve) => {
      reader.onloadend = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    });
  } catch(e) {
    return 'ERROR: ' + e.message;
  }
})()
""" % json.dumps(url)

r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
val = r.get("result", {}).get("result", {}).get("value", "")
if val and val.startswith("data:image"):
    b64 = val.split(",", 1)[1]
    with open("C:/tmp/original_magikarp3.png", "wb") as f:
        f.write(base64.b64decode(b64))
    print("saved", len(b64))
else:
    print("FAIL:", val[:300])
c.close()
