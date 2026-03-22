#!/bin/bash
# 백엔드 서버 재시작 스크립트
taskkill.exe //F //IM python.exe 2>/dev/null
.venv/Scripts/python.exe run.py
