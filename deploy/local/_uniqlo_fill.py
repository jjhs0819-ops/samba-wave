# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "0BA049D95E6F9DB5BB599AAC50BF8C97"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

fields = {
    "id-familyName": "任",
    "id-givenName": "成熙",
    "id-phoneticFamilyName": "イム",
    "id-phoneticGivenName": "ソンヒ",
    "id-city": "文京区小石川",
    "id-street1": "2-24-7",
    "id-street2": "名古屋ビル9237",
    "id-phone": "0338300852",
}

fill_js = """
(function(vals){
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  var results = {};
  for (var id in vals) {
    var el = document.getElementById(id);
    if (!el) { results[id] = 'NOT FOUND'; continue; }
    setter.call(el, vals[id]);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('blur', {bubbles: true}));
    results[id] = 'ok:' + el.value;
  }
  return JSON.stringify(results);
})(%s)
""" % json.dumps(fields, ensure_ascii=False)

r = c.call("Runtime.evaluate", {"expression": fill_js, "returnByValue": True})
val = r.get("result", {}).get("result", {}).get("value")
with open("C:/tmp/uniqlo_fill_result.txt", "w", encoding="utf-8") as f:
    f.write(val or "")
print("done")
c.close()
