import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "0BA049D95E6F9DB5BB599AAC50BF8C97"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(1)

js = """
(function(){
  var inputs = Array.from(document.querySelectorAll('input, select'));
  return inputs.map(function(el){
    var label = '';
    var id = el.id;
    if (id) {
      var lab = document.querySelector('label[for="'+id+'"]');
      if (lab) label = lab.textContent.trim();
    }
    return {
      tag: el.tagName, type: el.type, id: el.id, name: el.name,
      placeholder: el.placeholder, label: label, value: el.value
    };
  });
})()
"""
r = c.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
result = r.get("result", {}).get("result", {}).get("value", [])
with open("C:/tmp/uniqlo_fields.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("count", len(result))
c.close()
