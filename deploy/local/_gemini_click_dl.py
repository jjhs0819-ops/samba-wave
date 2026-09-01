import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Input.dispatchMouseEvent", {"type":"mousePressed","x":959,"y":525,"button":"left","clickCount":1})
c.call("Input.dispatchMouseEvent", {"type":"mouseReleased","x":959,"y":525,"button":"left","clickCount":1})
time.sleep(2)
c.close()
