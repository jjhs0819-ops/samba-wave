import os

os.environ["PYTHONUNBUFFERED"] = "1"

print("1. Python 시작", flush=True)
print("2. uvicorn import 중...", flush=True)
import uvicorn

print("3. uvicorn import 완료", flush=True)
print("4. backend.main import 중...", flush=True)
from backend.main import app

print("5. backend.main import 완료", flush=True)
print("6. 서버 시작 중...", flush=True)
uvicorn.run(app, host="0.0.0.0", port=28080, log_level="info")
