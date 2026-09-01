# -*- coding: utf-8 -*-
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_sheet_helpers import CDPConn
tab_id = "AB105EAB71599F63E05C8AA63FC2DCF9"
c = CDPConn(tab_id)
c.call("Page.enable")
c.call("Input.dispatchMouseEvent", {"type":"mouseWheel","x":1100,"y":500,"deltaX":0,"deltaY":400})
time.sleep(1)
c.close()
