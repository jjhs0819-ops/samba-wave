"""SSG 검색 파라미터 조합 실험 — 어떤 파라미터가 실제 카테고리 필터로 동작하는지 확인.

가설별 URL을 순차 요청하고, 반환된 상품 ID 목록을 비교해 필터 효과를 측정.
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

BASE = "https://department.ssg.com/search"
KEYWORD = "나이키"
REP_BRAND = "2000004827"
CTG_BOLCAP = "6000201147"  # 모자 > 볼캡/야구모자
CTG_BINI = "6000201151"  # 모자 > 비니
CTG_BELT = "6000201142"  # 벨트 > 남성벨트


def extract_items(html: str) -> list[dict]:
    items = _ssg._parse_search_html(html, KEYWORD)
    out = []
    for it in items:
        out.append(
            {"pid": it.get("siteProductId", ""), "name": (it.get("name") or "")[:60]}
        )
    return out


async def probe(client: httpx.AsyncClient, label: str, url: str) -> list[dict]:
    print(f"\n--- {label}")
    print(f"URL: {url}")
    try:
        r = await client.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
    except Exception as e:
        print(f"  !! 요청 실패: {e}")
        return []
    print(f"  HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        return []
    items = extract_items(r.text)
    print(f"  상품 수: {len(items)}")
    for i, it in enumerate(items[:10], 1):
        print(f"    [{i:2}] {it['pid']} {it['name']}")
    return items


async def main():
    # 점검할 URL 조합
    probes = [
        (
            "A. 기준 (repBrandId+ctgId+ctgLv+maxDiscount, 볼캡)",
            f"{BASE}?query={quote(KEYWORD)}&page=1&repBrandId={REP_BRAND}&ctgId={CTG_BOLCAP}&ctgLv=3&maxDiscount=1",
        ),
        (
            "B. 기준 (repBrandId+ctgId+ctgLv+maxDiscount, 비니)",
            f"{BASE}?query={quote(KEYWORD)}&page=1&repBrandId={REP_BRAND}&ctgId={CTG_BINI}&ctgLv=3&maxDiscount=1",
        ),
        (
            "C. repBrandId 제거 (ctgId+ctgLv+maxDiscount, 볼캡)",
            f"{BASE}?query={quote(KEYWORD)}&page=1&ctgId={CTG_BOLCAP}&ctgLv=3&maxDiscount=1",
        ),
        (
            "D. query 제거 (repBrandId+ctgId+ctgLv, 볼캡)",
            f"{BASE}?page=1&repBrandId={REP_BRAND}&ctgId={CTG_BOLCAP}&ctgLv=3",
        ),
        (
            "E. query+ctgId만 (repBrandId 없음, 볼캡)",
            f"{BASE}?query={quote(KEYWORD)}&page=1&ctgId={CTG_BOLCAP}&ctgLv=3",
        ),
        (
            "F. maxDiscount 제거 (볼캡)",
            f"{BASE}?query={quote(KEYWORD)}&page=1&repBrandId={REP_BRAND}&ctgId={CTG_BOLCAP}&ctgLv=3",
        ),
        (
            "G. ctgId만 (repBrandId/query/maxDiscount 전부 제거, 볼캡)",
            f"{BASE}?page=1&ctgId={CTG_BOLCAP}&ctgLv=3",
        ),
        (
            "H. ctgPath 경로 추가 (볼캡)",
            f"{BASE}?query={quote(KEYWORD)}&page=1&repBrandId={REP_BRAND}&ctgId={CTG_BOLCAP}&ctgLv=3&ctgPath={quote('모자/장갑/ACC > 모자 > 볼캡/야구모자')}&maxDiscount=1",
        ),
    ]

    async with httpx.AsyncClient() as client:
        results = {}
        for label, url in probes:
            items = await probe(client, label, url)
            results[label] = [it["pid"] for it in items]
            await asyncio.sleep(4)  # 차단 회피

    print("\n\n==== 비교 요약 ====")
    pid_a = set(results.get(list(results.keys())[0], []))
    for label, pids in results.items():
        s = set(pids)
        overlap = len(s & pid_a)
        print(f"  {label}: 총 {len(pids)}건, A와 교집합 {overlap}/{len(s)}")


if __name__ == "__main__":
    asyncio.run(main())
