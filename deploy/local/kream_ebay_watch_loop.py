# -*- coding: utf-8 -*-
"""P5 체크박스 상시 감시(2초 간격) — 백그라운드로 계속 돌면서 클릭 몇 초 내로 반응."""
import os
import sys
import time
import traceback

import gspread

SHEET_ID = "1FM3smmTlsbxhN03CFCoK_Pp5byA9wTfpiQ66jOG0ohM"
TAB_NAME = "크림매칭"
CREDS_PATH = "C:/Users/canno/.claude/google-credentials.json"
POLL_SECONDS = 2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kream_ebay_sync  # noqa: E402


def main():
    print("[loop] 시작", flush=True)
    gc = gspread.service_account(filename=CREDS_PATH)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    print("[loop] 시트 연결됨, 감시 시작", flush=True)
    while True:
        try:
            val = ws.acell("P5").value
            if str(val).strip().upper() in ("TRUE", "1"):
                print("[loop] P5 감지 -> 실행", flush=True)
                ws.update(range_name="P5", values=[[False]], value_input_option="USER_ENTERED")
                kream_ebay_sync.main()
                print("[loop] 완료", flush=True)
        except Exception:
            traceback.print_exc()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
