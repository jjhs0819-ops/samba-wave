"""GSShop 1000건 대량 수집 성공률 측정.

실행: cd backend && .venv/Scripts/python.exe scripts/test_gsshop_1000.py
"""

import asyncio
import re
import json
import base64
import time
from collections import Counter
import httpx

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

HEADERS_MOBILE = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://m.gsshop.com/",
}

KEYWORD = "내셔널지오그래픽"
TARGET = 1000


async def collect_ids(target: int) -> list[str]:
    prd_pattern = re.compile(r"/prd/prd\.gs\?prdid=(\d+)")
    prd_section_re = re.compile(
        r'<section[^>]+class="prd-list"[^>]*>(.*?)</section>', re.DOTALL
    )
    ids: list[str] = []
    seen: set[str] = set()

    async with httpx.AsyncClient() as client:
        for pg in range(1, 300):
            if pg == 1:
                eh = base64.b64encode(
                    json.dumps(
                        {"part": "DEPT", "selected": "opt-part"}, separators=(",", ":")
                    ).encode()
                ).decode()
            else:
                eh = base64.b64encode(
                    json.dumps(
                        {"pageNumber": pg, "part": "DEPT", "selected": "opt-page"},
                        separators=(",", ":"),
                    ).encode()
                ).decode()

            try:
                resp = await client.get(
                    "https://www.gsshop.com/shop/search/main.gs",
                    params={"tq": KEYWORD, "eh": eh},
                    headers=HEADERS_PC,
                    timeout=20.0,
                    follow_redirects=True,
                )
            except Exception as e:
                print(f"  페이지 {pg} 요청 실패: {e}")
                break

            if resp.status_code != 200:
                print(f"  페이지 {pg} HTTP {resp.status_code}, 중단")
                break

            m = prd_section_re.search(resp.text)
            html = m.group(1) if m else resp.text
            new = 0
            for pid in prd_pattern.findall(html):
                if pid not in seen:
                    seen.add(pid)
                    ids.append(pid)
                    new += 1

            if new == 0:
                break
            if len(ids) >= target:
                break
            if pg % 5 == 0:
                print(f"  페이지 {pg}: {len(ids)}건 수집")
            await asyncio.sleep(0.2)

    return ids[:target]


async def fetch_with_retry(
    client: httpx.AsyncClient, product_id: str
) -> tuple[str, str, int]:
    """재시도 포함 상세 조회. (product_id, 결과, 시도횟수)"""
    for attempt in range(3):
        url = f"https://m.gsshop.com/prd/prd.gs?prdid={product_id}"
        try:
            resp = await client.get(
                url, headers=HEADERS_MOBILE, timeout=30.0, follow_redirects=True
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", str(2**attempt)))
                await asyncio.sleep(min(wait, 15))
                continue
            if resp.status_code == 403:
                await asyncio.sleep(2**attempt)
                continue
            if resp.status_code != 200:
                return product_id, f"HTTP_{resp.status_code}", attempt + 1
            html = resp.text
            if "var renderJson" in html or "var renderJson=" in html:
                return product_id, "OK_renderJson", attempt + 1
            if '"@type":"Product"' in html:
                return product_id, "OK_jsonld", attempt + 1
            if "og:title" in html:
                return product_id, "OK_ogmeta", attempt + 1
            return product_id, "FAIL_no_data", attempt + 1
        except asyncio.TimeoutError:
            if attempt < 2:
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                return product_id, "TIMEOUT", 3
        except Exception as e:
            return product_id, f"ERR_{type(e).__name__}", attempt + 1

    return product_id, "FAIL_3RETRY", 3


async def run_batch_test(
    ids: list[str], batch_size: int, inter_sleep: float, label: str
) -> dict:
    results: list[str] = []
    total_attempts = 0
    failed_ids: list[str] = []
    start = time.time()

    async with httpx.AsyncClient() as client:
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            tasks = [fetch_with_retry(client, pid) for pid in batch]
            batch_res = await asyncio.gather(*tasks, return_exceptions=True)
            for r in batch_res:
                if isinstance(r, Exception):
                    results.append("ERR")
                    total_attempts += 1
                else:
                    results.append(r[1])
                    total_attempts += r[2]
                    if not r[1].startswith("OK"):
                        failed_ids.append(r[0])
            done = min(i + batch_size, len(ids))
            if done % 100 == 0 or done == len(ids):
                ok = sum(1 for r in results if r.startswith("OK"))
                print(
                    f"  [{label}] {done}/{len(ids)} / 현재 성공률 {ok / len(results) * 100:.1f}%"
                )
            if inter_sleep > 0:
                await asyncio.sleep(inter_sleep)

    elapsed = time.time() - start
    counter = Counter(results)
    success = sum(v for k, v in counter.items() if k.startswith("OK"))
    total = len(results)
    rate = success / total * 100 if total else 0

    print(f"\n  [{label}] 완료")
    print(f"  결과: {dict(counter)}")
    print(f"  성공률: {success}/{total} = {rate:.1f}%")
    print(
        f"  소요: {elapsed:.0f}초 ({elapsed / 60:.1f}분), 평균 시도: {total_attempts / max(total, 1):.2f}회"
    )
    if failed_ids:
        print(f"  실패 ID 샘플: {failed_ids[:10]}")

    return {
        "label": label,
        "success_rate": rate,
        "counter": dict(counter),
        "elapsed": elapsed,
    }


async def main():
    print("=" * 60)
    print(f"GS샵 대량 수집 성공률 측정: '{KEYWORD}' {TARGET}건")
    print("=" * 60)

    print(f"\n[1단계] {TARGET}건 ID 수집 중...")
    ids = await collect_ids(TARGET)
    print(f"  {len(ids)}건 수집 완료")

    if len(ids) < 100:
        print("ID 부족. 종료.")
        return

    print(
        "\n[2단계] 배치5 + 딜레이0.5s + 재시도3회 (프로덕션 브랜드전체수집 시뮬레이션)"
    )
    r1 = await run_batch_test(
        ids, batch_size=5, inter_sleep=0.5, label="배치5/딜레이0.5s/재시도O"
    )

    await asyncio.sleep(5)

    print("\n[3단계] 배치20 + 딜레이0.3s + 재시도3회 (프로덕션 선취합 시뮬레이션)")
    r2 = await run_batch_test(
        ids, batch_size=20, inter_sleep=0.3, label="배치20/딜레이0.3s/재시도O"
    )

    print("\n" + "=" * 60)
    print("최종 비교")
    print("=" * 60)
    for r in [r1, r2]:
        print(f"  {r['label']}: {r['success_rate']:.1f}% ({r['elapsed']:.0f}초)")


if __name__ == "__main__":
    asyncio.run(main())
