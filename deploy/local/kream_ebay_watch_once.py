# -*- coding: utf-8 -*-
"""P5 체크박스 1회성 체크 — 작업스케줄러가 1분마다 이걸 실행."""
import os
import sys

import gspread

SHEET_ID = "1FM3smmTlsbxhN03CFCoK_Pp5byA9wTfpiQ66jOG0ohM"
TAB_NAME = "크림매칭"
CREDS_PATH = "C:/Users/canno/.claude/google-credentials.json"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kream_ebay_sync  # noqa: E402


def main():
    gc = gspread.service_account(filename=CREDS_PATH)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)

    val = ws.acell("P5").value
    triggered = str(val).strip().upper() in ("TRUE", "1")
    if not triggered:
        return

    print("[watch] P5 체크됨 -> 실행")
    ws.update(range_name="P5", values=[[False]], value_input_option="USER_ENTERED")
    kream_ebay_sync.main()


if __name__ == "__main__":
    main()
