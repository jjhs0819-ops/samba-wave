# -*- coding: utf-8 -*-
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn

tab_id = "413B2AD8658332F0A44B021FD2389266"
c = CDPConn(tab_id)
c.call("Runtime.enable")
c.call("Page.enable")
c.call("Page.bringToFront")
time.sleep(0.5)

comment = (
    "The buyer has NOT returned the item to us. We have not received any return package, "
    "and no tracking number for a return shipment has been provided. A refund should only be "
    "issued after the returned item is received and confirmed by the seller.\n\n"
    "We also dispute the claim that the item \"arrived damaged.\" This was a factory-sealed "
    "Pokemon promo card pack, double/triple-wrapped with protective packaging (rigid mailer + "
    "bubble wrap) before shipping, exactly as we do for every order of this item. We have sold "
    "many units of this exact product and never had a damage complaint before.\n\n"
    "Since the buyer never returned the item and there is no proof of damage, this looks like an "
    "attempt to keep the item and get a refund. Please reverse the refund, or require the buyer "
    "to actually return the item with tracking before any refund is granted."
)

fill_js = """
(function(text){
  var el = document.getElementById('appealRequestComments');
  var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(el, text);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return el.value.length;
})(%s)
""" % json.dumps(comment)

r = c.call("Runtime.evaluate", {"expression": fill_js, "returnByValue": True})
print("filled len:", r.get("result", {}).get("result", {}).get("value"))
c.close()
