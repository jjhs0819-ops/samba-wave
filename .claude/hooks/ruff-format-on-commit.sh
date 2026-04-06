#!/bin/bash
# Python 파일이 스테이징되어 있으면 ruff format 자동 실행
# PreToolUse hook으로 git commit 전에 실행

cd "$(git rev-parse --show-toplevel 2>/dev/null)/backend" 2>/dev/null || exit 0

# 스테이징된 .py 파일이 있는지 확인
PY_FILES=$(git diff --cached --name-only --diff-filter=ACMR -- '*.py' 2>/dev/null)
if [ -z "$PY_FILES" ]; then
  exit 0
fi

# ruff format 실행
if [ -f ".venv/Scripts/python.exe" ]; then
  .venv/Scripts/python.exe -m ruff format . 2>/dev/null
  .venv/Scripts/python.exe -m ruff check --fix . 2>/dev/null
elif command -v ruff &>/dev/null; then
  ruff format . 2>/dev/null
  ruff check --fix . 2>/dev/null
fi

# 포맷 변경된 파일 다시 스테이징
git add $PY_FILES 2>/dev/null
