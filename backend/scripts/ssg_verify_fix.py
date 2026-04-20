"""검증: 3개 필터에서 'repBrandId 제거' 수정안 적용 시 실제 카테고리 일치 여부.

상세 조회 차단 상태 우회: 상품명에 카테고리 키워드가 포함되는지로 판정.
"""

import asyncio
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient  # noqa: E402

_ssg = SSGSourcingClient()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

BASE = "https://department.ssg.com/search"
KEYWORD = "나이키"

FILTERS = [
    {
        "name": "볼캡/야구모자",
        "ctg_id": "6000201147",
        "keywords": ["캡", "모자"],
    },
    {
        "name": "비니",
        "ctg_id": "6000201151",
        "keywords": ["비니"],
    },
    {
        "name": "남성벨트",
        "ctg_id": "6000201142",
        "keywords": ["벨트"],
    },
]


async def fetch(client: httpx.AsyncClient, url: str) -> list[dict]:
    r = await client.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
    print(f"  HTTP {r.status_code}")
    if r.status_code != 200:
        return []
    return _ssg._parse_search_html(r.text, KEYWORD)


async def test_filter(client: httpx.AsyncClient, f: dict, scenario: str, url: str):
    print(f"\n  [{scenario}]")
    print(f"  URL: {url}")
    items = await fetch(client, url)
    print(f"  수집: {len(items)}건")
    match = 0
    for i, it in enumerate(items, 1):
        name = it.get("name", "")
        ok = any(kw in name for kw in f["keywords"])
        mark = "✓" if ok else "✗"
        print(f"    [{i:2}] {mark} {it.get('siteProductId','')} {name[:60]}")
        if ok:
            match += 1
    print(f"  → 일치 {match}/{len(items)}")
    return match, len(items)


async def main():
    async with httpx.AsyncClient() as client:
        for f in FILTERS:
            print(f"\n{'=' * 78}")
            print(f"[필터] {f['name']} (ctgId={f['ctg_id']}, 기대 키워드: {f['keywords']})")

            # 현재(버그)
            cur = f"{BASE}?query={quote(KEYWORD)}&page=1&repBrandId=2000004827&ctgId={f['ctg_id']}&ctgLv=3&maxDiscount=1"
            await test_filter(client, f, "현재 (repBrandId 포함 — 버그)", cur)
            await asyncio.sleep(4)

            # 수정안
            fix = f"{BASE}?query={quote(KEYWORD)}&page=1&ctgId={f['ctg_id']}&ctgLv=3&maxDiscount=1"
            await test_filter(client, f, "수정안 (repBrandId 제거)", fix)
            await asyncio.sleep(4)


if __name__ == "__main__":
    asyncio.run(main())
