# -*- coding: utf-8 -*-
"""[이사 안내] 실제 코드는 tools/sheet_sync/ 로 옮겼다.

작업 스케줄러 'kream-ebay-watch' 가 이 경로를 직접 가리키는데, 스케줄러 수정에는
관리자 권한이 필요해 경로를 못 바꿨다(0x80070005). 그래서 이 파일은 새 위치를
불러 실행하기만 하는 껍데기로 남긴다. 로직을 여기 다시 쓰지 말 것.

  실제 코드   tools/sheet_sync/kream_ebay_watch_once.py
  설명 문서   tools/sheet_sync/README.md
"""
import os
import runpy
import sys

_TARGET = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools", "sheet_sync", "kream_ebay_watch_once.py",
)

sys.path.insert(0, os.path.dirname(_TARGET))
runpy.run_path(_TARGET, run_name="__main__")
