"""GSShop 병렬 요청 시 실패율 측정 + 재시도 효과 검증.

실행: cd backend && .venv/Scripts/python.exe scripts/test_gsshop_parallel.py
"""

import asyncio
import re
import json
import base64
import time
from collections import Counter
import httpx

HEADERS_MOBILE = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://m.gsshop.com/",
}

HEADERS_PC = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.gsshop.com/",
}

KEYWORD = "내셔널지오그래픽"


def classify_html(html: str, product_id: str) -> str:
    if not html:
        return "EMPTY_HTML"
    if "var renderJson" in html or "var renderJson=" in html:
        return "OK_renderJson"
    if '"@type":"Product"' in html or '"@type": "Product"' in html:
        return "OK_jsonld"
    if "og:title" in html:
        return "OK_ogmeta"
    return "FAIL_no_data"


async def fetch_product(
    client: httpx.AsyncClient, product_id: str, timeout: float = 20.0
) -> tuple[str, str]:
    """단일 상품 상세 조회. (product_id, 결과) 반환."""
    url = f"https://m.gsshop.com/prd/prd.gs?prdid={product_id}"
    try:
        resp = await client.get(
            url, headers=HEADERS_MOBILE, timeout=timeout, follow_redirects=True
        )
        if resp.status_code == 429:
            return product_id, "429"
        if resp.status_code == 403:
            return product_id, "403"
        if resp.status_code != 200:
            return product_id, f"HTTP_{resp.status_code}"
        return product_id, classify_html(resp.text, product_id)
    except httpx.TimeoutException:
        return product_id, "TIMEOUT"
    except Exception as e:
        return product_id, f"ERR_{type(e).__name__}"


async def fetch_with_retry(
    client: httpx.AsyncClient, product_id: str, max_retry: int = 2
) -> tuple[str, str, int]:
    """재시도 포함 상세 조회. (product_id, 결과, 시도횟수) 반환."""
    for attempt in range(max_retry + 1):
        pid, result = await fetch_product(client, product_id)
        if result.startswith("OK"):
            return product_id, result, attempt + 1
        if result in ("429", "403"):
            wait = 2.0 * (2**attempt)
            await asyncio.sleep(wait)
        elif result == "TIMEOUT":
            if attempt < max_retry:
                await asyncio.sleep(1.0 * (attempt + 1))
        else:
            break  # HTTP 에러는 재시도 무의미
    return product_id, result, max_retry + 1


async def get_sample_ids(n: int = 100) -> list[str]:
    """검색 결과에서 n개 ID 수집."""
    prd_pattern = re.compile(r"/prd/prd\.gs\?prdid=(\d+)")
    prd_section_re = re.compile(
        r'<section[^>]+class="prd-list"[^>]*>(.*?)</section>', re.DOTALL
    )
    ids: list[str] = []
    seen: set[str] = set()

    async with httpx.AsyncClient() as client:
        for pg in range(1, 10):
            eh = base64.b64encode(
                json.dumps(
                    {"part": "DEPT", "selected": "opt-part"}
                    if pg == 1
                    else {"pageNumber": pg, "part": "DEPT", "selected": "opt-page"},
                    separators=(",", ":"),
                ).encode()
            ).decode()
            resp = await client.get(
                "https://www.gsshop.com/shop/search/main.gs",
                params={"tq": KEYWORD, "eh": eh},
                headers=HEADERS_PC,
                timeout=20.0,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                break
            m = prd_section_re.search(resp.text)
            html = m.group(1) if m else resp.text
            for pid in prd_pattern.findall(html):
                if pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
            if len(ids) >= n:
                break
            await asyncio.sleep(0.2)
    return ids[:n]


async def test_batch(
    ids: list[str],
    batch_size: int,
    inter_batch_sleep: float,
    label: str,
    use_retry: bool = False,
) -> dict:
    """배치 병렬 요청 테스트."""
    results: list[str] = []
    total_attempts = 0
    start = time.time()

    async with httpx.AsyncClient() as client:
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            if use_retry:
                tasks = [fetch_with_retry(client, pid) for pid in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in batch_results:
                    if isinstance(r, Exception):
                        results.append("ERR")
                    else:
                        results.append(r[1])
                        total_attempts += r[2]
            else:
                tasks = [fetch_product(client, pid) for pid in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in batch_results:
                    if isinstance(r, Exception):
                        results.append("ERR")
                    else:
                        results.append(r[1])
                total_attempts += len(batch)

            if inter_batch_sleep > 0:
                await asyncio.sleep(inter_batch_sleep)

    elapsed = time.time() - start
    counter = Counter(results)
    success = sum(v for k, v in counter.items() if k.startswith("OK"))
    total = len(results)
    rate = success / total * 100 if total else 0

    print(f"\n  [{label}]")
    print(
        f"  배치 크기: {batch_size}, 배치 간 딜레이: {inter_batch_sleep}s, 재시도: {'O' if use_retry else 'X'}"
    )
    print(f"  결과: {dict(counter)}")
    print(f"  성공률: {success}/{total} = {rate:.1f}%")
    print(f"  소요: {elapsed:.1f}초, 평균 시도: {total_attempts / total:.2f}회")

    return {
        "label": label,
        "success_rate": rate,
        "counter": dict(counter),
        "elapsed": elapsed,
    }


async def main():
    print("=" * 60)
    print("GS샵 병렬 요청 실패율 측정")
    print("=" * 60)

    print("\n샘플 ID 100개 수집 중...")
    ids = await get_sample_ids(100)
    print(f"{len(ids)}개 수집 완료")

    if len(ids) < 50:
        print("샘플 부족. 종료.")
        return

    print("\n[테스트 시작]")
    print("현재 프로덕션 방식(배치 5, 딜레이 없음) → 개선안들 비교")

    results = []

    # 현재 방식: 배치5, 딜레이0 (브랜드전체수집)
    r = await test_batch(
        ids[:50], batch_size=5, inter_batch_sleep=0, label="현재방식(배치5, 딜레이없음)"
    )
    results.append(r)
    await asyncio.sleep(3)

    # 현재 방식: 배치20, 딜레이0 (일반수집 선취합)
    r = await test_batch(
        ids[:50],
        batch_size=20,
        inter_batch_sleep=0,
        label="현재방식(배치20, 딜레이없음)",
    )
    results.append(r)
    await asyncio.sleep(3)

    # 개선안1: 배치5, 딜레이0.5s
    r = await test_batch(
        ids[:50], batch_size=5, inter_batch_sleep=0.5, label="개선1(배치5, 딜레이0.5s)"
    )
    results.append(r)
    await asyncio.sleep(3)

    # 개선안2: 배치5, 딜레이0.5s + 재시도2회
    r = await test_batch(
        ids[:50],
        batch_size=5,
        inter_batch_sleep=0.5,
        label="개선2(배치5, 딜레이0.5s+재시도)",
        use_retry=True,
    )
    results.append(r)
    await asyncio.sleep(3)

    # 개선안3: 배치3, 딜레이0.3s + 재시도2회
    r = await test_batch(
        ids[:50],
        batch_size=3,
        inter_batch_sleep=0.3,
        label="개선3(배치3, 딜레이0.3s+재시도)",
        use_retry=True,
    )
    results.append(r)

    print("\n" + "=" * 60)
    print("최종 비교")
    print("=" * 60)
    for r in results:
        print(f"  {r['label']}: 성공률 {r['success_rate']:.1f}% ({r['elapsed']:.0f}초)")


if __name__ == "__main__":
    asyncio.run(main())
