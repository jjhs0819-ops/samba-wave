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

    # [2026-08-20] 체크박스 위치를 **자동으로 찾는다.** 종전엔 "P5" 를 박아둬서
    # 시트에서 행이 하나만 밀려도 영영 반응하지 않았다(실측: 체크박스가 P6 로
    # 내려가 있었고 스크립트는 계속 빈 P5 를 읽었다). 같은 사고가 2026-08-14 에도
    # 있었다 — 위치를 고정하지 말고 P열에서 체크된 칸을 찾는다.
    cells = ws.get("P1:P20") or []
    hit = 0
    for i, row in enumerate(cells, start=1):
        v = (row[0] if row else "").strip().upper()
        if v in ("TRUE", "1"):
            hit = i
            break
    if not hit:
        return

    addr = "P%d" % hit
    print("[watch] %s 체크됨 -> 실행" % addr)
    ws.update(range_name=addr, values=[[False]], value_input_option="USER_ENTERED")
    kream_ebay_sync.main()


if __name__ == "__main__":
    main()
