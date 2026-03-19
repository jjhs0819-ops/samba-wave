---
name: 백엔드 실행 명령어
description: 백엔드 서버 실행은 .venv/Scripts/python.exe run.py 사용
type: feedback
---

백엔드 서버 실행 시 `cd backend && .venv/Scripts/python.exe run.py` 사용.
**Why:** uvicorn CLI의 모듈 import 이슈 방지를 위해 run.py에서 직접 임포트하는 방식 사용.
**How to apply:** 백엔드 재시작 안내 시 항상 이 명령어를 알려줄 것. uvicorn 직접 호출하지 말 것.
