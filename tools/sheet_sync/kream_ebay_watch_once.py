# -*- coding: utf-8 -*-
"""P5 체크박스 1회성 체크 — 작업스케줄러가 1분마다 이걸 실행."""

import os
import sys

import gspread

SHEET_ID = "1FM3smmTlsbxhN03CFCoK_Pp5byA9wTfpiQ66jOG0ohM"
TAB_NAME = "크림매칭"
CREDS_PATH = "C:/Users/canno/.claude/google-credentials.json"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# [2026-08-18] 작업스케줄러가 1분마다 실행하는데 python.exe 라 매번 콘솔 창이
# 깜빡였다. pythonw.exe 로 바꿔 창을 없앴는데, pythonw 는 sys.stdout 이 None 이라
# print() 가 AttributeError 로 죽는다. 출력을 로그 파일로 돌려 창도 없애고
# 기록도 남긴다(예전엔 창이 곧바로 닫혀 아무 기록도 안 남았다).
if sys.stdout is None or sys.stderr is None:
    _log = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "kream_ebay_watch.log"
    )
    _fh = open(_log, "a", encoding="utf-8", buffering=1)
    sys.stdout = _fh
    sys.stderr = _fh

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
