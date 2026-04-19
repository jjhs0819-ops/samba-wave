"""GSShop 수집 실패 원인 분류 테스트.

실행: cd backend && .venv/Scripts/python.exe scripts/test_gsshop_failures.py
"""

import asyncio
import re
import json
import base64
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
SAMPLE_SIZE = 50  # 상세 조회 테스트 샘플 수


async def fetch_search_page(client: httpx.AsyncClient, pg: int) -> str:
    if pg == 1:
        eh = base64.b64encode(
            json.dumps({"part": "DEPT", "selected": "opt-part"}, separators=(",", ":")).encode()
        ).decode()
    else:
        eh = base64.b64encode(
            json.dumps({"pageNumber": pg, "part": "DEPT", "selected": "opt-page"}, separators=(",", ":")).encode()
        ).decode()

    resp = await client.get(
        "https://www.gsshop.com/shop/search/main.gs",
        params={"tq": KEYWORD, "eh": eh},
        headers=HEADERS_PC,
        timeout=20.0,
        follow_redirects=True,
    )
    return resp.text if resp.status_code == 200 else ""


async def collect_search_ids() -> tuple[list[str], list[str]]:
    """검색 결과에서 prd ID와 deal ID 분리 수집."""
    prd_pattern = re.compile(r"/prd/prd\.gs\?prdid=(\d+)")
    deal_pattern = re.compile(r"/deal/deal\.gs\?dealNo=(\d+)")

    prd_section_re = re.compile(
        r'<section[^>]+class="prd-list"[^>]*>(.*?)</section>', re.DOTALL
    )

    prd_ids: list[str] = []
    deal_ids: list[str] = []
    seen: set[str] = set()

    async with httpx.AsyncClient() as client:
        for pg in range(1, 70):  # 최대 69페이지 (3818건 / 60개 ≈ 64페이지)
            html = await fetch_search_page(client, pg)
            if not html:
                print(f"  페이지 {pg}: 응답 없음, 중단")
                break

            section_m = prd_section_re.search(html)
            search_html = section_m.group(1) if section_m else html

            new_prd = 0
            new_deal = 0
            for pid in prd_pattern.findall(search_html):
                if pid not in seen:
                    seen.add(pid)
                    prd_ids.append(pid)
                    new_prd += 1
            for did in deal_pattern.findall(search_html):
                if did not in seen:
                    seen.add(did)
                    deal_ids.append(did)
                    new_deal += 1

            if new_prd + new_deal == 0:
                print(f"  페이지 {pg}: 새 상품 없음, 중단")
                break

            print(f"  페이지 {pg}: prd+{new_prd} deal+{new_deal} (누적 prd={len(prd_ids)} deal={len(deal_ids)})")
            await asyncio.sleep(0.2)

    return prd_ids, deal_ids


async def test_prd_url(client: httpx.AsyncClient, product_id: str) -> str:
    """prd URL로 상세 조회 시 결과 분류."""
    url = f"https://m.gsshop.com/prd/prd.gs?prdid={product_id}"
    try:
        resp = await client.get(url, headers=HEADERS_MOBILE, timeout=20.0, follow_redirects=True)
        if resp.status_code == 429:
            return "429"
        if resp.status_code == 403:
            return "403"
        if resp.status_code != 200:
            return f"HTTP_{resp.status_code}"
        html = resp.text
        if "var renderJson" in html or "var renderJson=" in html:
            return "OK_renderJson"
        if '"@type":"Product"' in html or '"@type": "Product"' in html:
            return "OK_jsonld"
        if 'og:title' in html:
            return "OK_ogmeta"
        return "OK_empty"
    except httpx.TimeoutException:
        return "TIMEOUT"
    except Exception as e:
        return f"ERR_{type(e).__name__}"


async def test_deal_url(client: httpx.AsyncClient, deal_id: str) -> str:
    """deal URL로 상세 조회 시 결과 분류."""
    url = f"https://m.gsshop.com/deal/deal.gs?dealNo={deal_id}"
    try:
        resp = await client.get(url, headers=HEADERS_MOBILE, timeout=20.0, follow_redirects=True)
        if resp.status_code in (429, 403):
            return f"HTTP_{resp.status_code}"
        if resp.status_code != 200:
            return f"HTTP_{resp.status_code}"
        html = resp.text
        if "var renderJson" in html or "var renderJson=" in html:
            return "OK_renderJson"
        if '"@type":"Product"' in html:
            return "OK_jsonld"
        if 'og:title' in html:
            return "OK_ogmeta"
        return "OK_empty"
    except httpx.TimeoutException:
        return "TIMEOUT"
    except Exception as e:
        return f"ERR_{type(e).__name__}"


async def test_deal_via_prd(client: httpx.AsyncClient, deal_id: str) -> str:
    """deal ID를 prd URL로 조회하면 어떻게 되는지 (현재 버그 재현)."""
    url = f"https://m.gsshop.com/prd/prd.gs?prdid={deal_id}"
    try:
        resp = await client.get(url, headers=HEADERS_MOBILE, timeout=20.0, follow_redirects=True)
        if resp.status_code != 200:
            return f"HTTP_{resp.status_code}"
        html = resp.text
        if "var renderJson" in html or "var renderJson=" in html:
            return "OK_renderJson"
        return "FAIL_no_data"
    except httpx.TimeoutException:
        return "TIMEOUT"
    except Exception:
        return "ERR"


async def main():
    print("=" * 60)
    print(f"GS샵 수집 실패 원인 분류 테스트: '{KEYWORD}'")
    print("=" * 60)

    # 1단계: 검색 결과 수집
    print("\n[1단계] 검색 결과 수집 (prd vs deal 분류)")
    prd_ids, deal_ids = await collect_search_ids()
    total = len(prd_ids) + len(deal_ids)

    print(f"\n총 {total}건 수집")
    print(f"  - prd 상품: {len(prd_ids)}건 ({len(prd_ids)/total*100:.1f}%)")
    print(f"  - deal 상품: {len(deal_ids)}건 ({len(deal_ids)/total*100:.1f}%)")

    if not prd_ids and not deal_ids:
        print("검색 결과 없음. 종료.")
        return

    # 2단계: prd 샘플 상세 조회 테스트
    sample_prd = prd_ids[:SAMPLE_SIZE]
    sample_deal = deal_ids[:SAMPLE_SIZE]

    print(f"\n[2단계] prd ID {len(sample_prd)}건 상세 조회 테스트 (prd URL 사용)")
    prd_results: list[str] = []
    async with httpx.AsyncClient() as client:
        for i, pid in enumerate(sample_prd):
            result = await test_prd_url(client, pid)
            prd_results.append(result)
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(sample_prd)} 완료...")
            await asyncio.sleep(0.3)

    prd_counter = Counter(prd_results)
    print(f"  결과: {dict(prd_counter)}")
    prd_success = sum(v for k, v in prd_counter.items() if k.startswith("OK"))
    print(f"  성공률: {prd_success}/{len(sample_prd)} = {prd_success/max(len(sample_prd),1)*100:.1f}%")

    if sample_deal:
        # 3단계: deal ID를 현재 방식(prd URL)으로 조회 → 버그 재현
        print(f"\n[3단계] deal ID {len(sample_deal)}건 → prd URL로 조회 (현재 버그 재현)")
        deal_via_prd_results: list[str] = []
        async with httpx.AsyncClient() as client:
            for i, did in enumerate(sample_deal):
                result = await test_deal_via_prd(client, did)
                deal_via_prd_results.append(result)
                if (i + 1) % 10 == 0:
                    print(f"  {i+1}/{len(sample_deal)} 완료...")
                await asyncio.sleep(0.3)

        dvp_counter = Counter(deal_via_prd_results)
        print(f"  결과: {dict(dvp_counter)}")
        dvp_success = sum(v for k, v in dvp_counter.items() if k.startswith("OK"))
        print(f"  성공률: {dvp_success}/{len(sample_deal)} = {dvp_success/max(len(sample_deal),1)*100:.1f}%")

        # 4단계: deal ID를 deal URL로 조회 → 올바른 방법
        print(f"\n[4단계] deal ID {len(sample_deal)}건 → deal URL로 조회 (수정 후 예상)")
        deal_results: list[str] = []
        async with httpx.AsyncClient() as client:
            for i, did in enumerate(sample_deal):
                result = await test_deal_url(client, did)
                deal_results.append(result)
                if (i + 1) % 10 == 0:
                    print(f"  {i+1}/{len(sample_deal)} 완료...")
                await asyncio.sleep(0.3)

        deal_counter = Counter(deal_results)
        print(f"  결과: {dict(deal_counter)}")
        deal_success = sum(v for k, v in deal_counter.items() if k.startswith("OK"))
        print(f"  성공률: {deal_success}/{len(sample_deal)} = {deal_success/max(len(sample_deal),1)*100:.1f}%")

    # 최종 요약
    print("\n" + "=" * 60)
    print("최종 요약")
    print("=" * 60)
    print(f"검색 결과: 총 {total}건 (prd {len(prd_ids)}건 / deal {len(deal_ids)}건)")
    if total > 0:
        print(f"deal 비율: {len(deal_ids)/total*100:.1f}%")
        print()
        if len(deal_ids) / total > 0.15:
            print("★ deal vs prd 혼재 버그가 실패의 주원인으로 추정됩니다.")
        else:
            print("→ deal 비율이 낮음. rate limit / 타임아웃이 주원인일 가능성 높음.")


if __name__ == "__main__":
    asyncio.run(main())
