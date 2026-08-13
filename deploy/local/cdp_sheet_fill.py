# -*- coding: utf-8 -*-
import sys, time
sys.path.insert(0, "/tmp")
from cdp_sheet_helpers import CDPConn

TAB_ID = "AD6DD22DAE9BE59F200E57AD170C1F90"

ORDERS = [
    ("10-15015-98054", 2, "2026. 8. 11", "2026. 8. 18"),
    ("01-15038-16913", 4, "2026. 8. 12", "2026. 8. 19"),
    ("08-15024-50243", 1, "2026. 8. 12", "2026. 8. 19"),
    ("19-15005-34774", 1, "2026. 8. 12", "2026. 8. 19"),
    ("13-15016-25310", 1, "2026. 8. 12", "2026. 8. 19"),
    ("08-15024-75523", 1, "2026. 8. 12", "2026. 8. 19"),
    ("07-15027-20618", 2, "2026. 8. 12", "2026. 8. 19"),
    ("16-15011-83212", 10, "2026. 8. 12", "2026. 8. 20"),
    ("04-15033-52386", 1, "2026. 8. 12", "2026. 8. 20"),
    ("09-15024-88024", 5, "2026. 8. 12", "2026. 8. 20"),
    ("19-15008-73603", 1, "2026. 8. 13", "2026. 8. 20"),
    ("21-15005-25173", 1, "2026. 8. 13", "2026. 8. 20"),
    ("10-15025-08320", 3, "2026. 8. 13", "2026. 8. 20"),
]

rows = []
for order_no, qty, odate, deadline in ORDERS:
    for seq in range(1, qty + 1):
        # A, B, C, D, E, F, G, H, I
        rows.append([odate, order_no, str(seq), "", "", "", "", "", deadline])

print(f"total rows: {len(rows)}")

c = CDPConn(TAB_ID)
c.call("Input.enable")
c.call("Runtime.enable")

def mouse_click(x, y):
    c.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    c.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

def key(code, key_name, text=None, vk=None):
    params = {"type": "keyDown", "code": code, "key": key_name}
    if vk is not None:
        params["windowsVirtualKeyCode"] = vk
    if text is not None:
        params["text"] = text
    c.call("Input.dispatchKeyEvent", params)
    params2 = dict(params)
    params2["type"] = "keyUp"
    c.call("Input.dispatchKeyEvent", params2)

def insert_text(s):
    if s == "":
        return
    c.call("Input.insertText", {"text": s})

# 1) Name box 클릭 → A17로 점프
mouse_click(45, 68)
time.sleep(0.3)
# 기존 내용 전체선택 후 덮어쓰기 위해 ctrl+a
c.call("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "code": "KeyA", "key": "a", "windowsVirtualKeyCode": 65})
c.call("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "code": "KeyA", "key": "a", "windowsVirtualKeyCode": 65})
insert_text("A17")
key("Enter", "Enter", text="\r", vk=13)
time.sleep(0.6)

for ridx, row in enumerate(rows):
    for cidx, val in enumerate(row):
        insert_text(val)
        if cidx < len(row) - 1:
            key("Tab", "Tab", vk=9)
        else:
            key("Enter", "Enter", text="\r", vk=13)
    time.sleep(0.05)
    if ridx % 5 == 0:
        print(f"row {ridx+1}/{len(rows)} done")

print("ALL DONE")
c.close()
