"""GSShop 수정 후 최종 검증 — 재시도 로직 동작 확인.

실행: cd backend && .venv/Scripts/python.exe scripts/test_gsshop_final.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.samba.proxy.gsshop_sourcing import GsShopSourcingClient


async def main():
    print("=" * 60)
    print("GSShop 수정 후 최종 검증")
    print("=" * 60)

    client = GsShopSourcingClient()

    # 타임아웃 설정 확인
    print(f"\n타임아웃: {client._timeout}")  # 30초여야 함

    # 상품 30개 순차 조회 (재시도 로직 포함)
    test_ids = [
        "1113986676", "1113986677", "1113986678",
        "1077777777", "1088888888",  # 존재하지 않는 ID (빈 결과 예상)
    ]

    # 실제 GS샵에서 내셔널지오그래픽 ID 5개 수집
    import re, json, base64
    import httpx
    prd_pattern = re.compile(r"/prd/prd\.gs\?prdid=(\d+)")
    prd_section_re = re.compile(r'<section[^>]+class="prd-list"[^>]*>(.*?)</section>', re.DOTALL)

    HEADERS_PC = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.gsshop.com/",
    }

    real_ids: list[str] = []
    async with httpx.AsyncClient() as hclient:
        eh = base64.b64encode(json.dumps({"part": "DEPT", "selected": "opt-part"}, separators=(",",":")).encode()).decode()
        resp = await hclient.get(
            "https://www.gsshop.com/shop/search/main.gs",
            params={"tq": "내셔널지오그래픽", "eh": eh},
            headers=HEADERS_PC, timeout=20.0, follow_redirects=True
        )
        if resp.status_code == 200:
            m = prd_section_re.search(resp.text)
            html = m.group(1) if m else resp.text
            real_ids = prd_pattern.findall(html)[:10]

    print(f"\n실제 상품 ID {len(real_ids)}개 수집: {real_ids[:5]}...")

    success = 0
    fail = 0
    for pid in real_ids:
        result = await client.get_product_detail(pid)
        if result and result.get("name"):
            success += 1
            print(f"  [OK] {pid}: {result['name'][:30]} / 가격={result.get('salePrice',0):,}")
        else:
            fail += 1
            print(f"  [FAIL] {pid}: 실패")
        await asyncio.sleep(0.3)

    print(f"\n결과: 성공 {success}/{len(real_ids)} = {success/max(len(real_ids),1)*100:.1f}%")
    print(f"타임아웃 30초 확인: {client._timeout.read}초")


if __name__ == "__main__":
    asyncio.run(main())
