"""무신사 랭킹 API 탐색 스크립트."""

import httpx
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
resp = httpx.get(
    "https://static.msscdn.net/static/v2/pc/ranking/ranking.js",
    headers=headers,
    timeout=15.0,
)
js = resp.text

# 모든 .get() .post() 호출에서 경로 추출
all_calls = re.findall(r'\.(?:get|post)\s*\(\s*["\x27`](/[^"\x27`]+)["\x27`]', js)
print(f"=== get/post 경로 ({len(set(all_calls))}개) ===")
for c in sorted(set(all_calls)):
    print(f"  {c}")

# archive 문맥
for m in list(re.finditer(r"archive", js))[:3]:
    start = max(0, m.start() - 200)
    end = min(len(js), m.end() + 200)
    ctx = js[start:end]
    print("\n=== archive 문맥 ===")
    print(f"  {ctx}")

# 쿼리 파라미터로 date, categoryCode 사용하는 문맥
for kw in ["date", "categoryCode", "gf"]:
    matches = list(re.finditer(kw, js))
    if matches:
        m = matches[0]
        start = max(0, m.start() - 150)
        end = min(len(js), m.end() + 150)
        ctx = js[start:end]
        print(f"\n=== {kw} 문맥 ===")
        print(f"  {ctx}")
