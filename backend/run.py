"""로컬 개발 서버 실행 스크립트.

uvicorn CLI의 모듈 import 이슈 방지를 위해
앱을 직접 임포트하여 실행합니다.

사용법: python run.py [--port PORT]
"""
import argparse
import signal
import sys

import uvicorn


def _handle_exit(sig, frame):
  """Windows에서 Ctrl+C 시 즉시 종료."""
  sys.exit(0)

signal.signal(signal.SIGINT, _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)

from backend.main import app  # noqa: F401 - 앱 직접 임포트

if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--port", type=int, default=28080)
  parser.add_argument("--reload", action="store_true", default=False)
  args = parser.parse_args()

  uvicorn.run(
    "backend.main:app" if args.reload else app,
    host="127.0.0.1",
    port=args.port,
    reload=args.reload,
    reload_dirs=["backend"] if args.reload else None,
  )
