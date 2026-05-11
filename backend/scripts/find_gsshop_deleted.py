"""GSShop 실제 삭제된 상품 자동 탐색 — DB의 상품 100개 직접 호출해 redirect/에러 케이스 찾기."""

import asyncio
import asyncpg
import httpx
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    try:
        # last_refreshed_at 오래된 상품 우선 (NULL은 한 번도 갱신 안 됐으니 가장 의심)
        rows = await conn.fetch(
            """
            SELECT site_product_id, name, last_refreshed_at
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            ORDER BY last_refreshed_at ASC NULLS FIRST
            LIMIT 100
            """
        )
    finally:
        await conn.close()

    print(f"[탐색] GSShop 상품 {len(rows)}개 직접 호출 시작")
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "text/html,application/xhtml+xml",
    }
    deleted: list[tuple] = []
    redirect_3xx: list[tuple] = []
    error_page: list[tuple] = []
    alive = 0
    other = 0

    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for i, r in enumerate(rows, 1):
            sid = r["site_product_id"]
            try:
                resp = await client.get(
                    f"https://m.gsshop.com/prd/prd.gs?prdid={sid}",
                    headers=headers,
                )
                if 300 <= resp.status_code < 400:
                    loc = resp.headers.get("Location", "")
                    if "prdid=" not in loc and "prd.gs" not in loc:
                        redirect_3xx.append(
                            (sid, r["name"], resp.status_code, loc[:80])
                        )
                        deleted.append((sid, r["name"]))
                    else:
                        alive += 1
                elif resp.status_code == 200:
                    body = resp.text
                    if "DustView" in body or "에러 페이지" in body:
                        error_page.append((sid, r["name"]))
                        deleted.append((sid, r["name"]))
                    elif "var renderJson" in body and '"prd":{' in body:
                        alive += 1
                    else:
                        other += 1
                else:
                    other += 1
                if i % 20 == 0:
                    print(
                        f"  진행 {i}/{len(rows)} 살아있음={alive} 삭제={len(deleted)} 기타={other}"
                    )
            except Exception as e:
                print(f"  [error] {sid}: {e}")
                other += 1
            await asyncio.sleep(0.3)  # 차단 방지

    print("\n=== 결과 ===")
    print(f"  살아있음: {alive}")
    print(f"  삭제(redirect 3xx + 메인튕김): {len(redirect_3xx)}")
    print(f"  삭제(200 + DustView 에러페이지): {len(error_page)}")
    print(f"  기타: {other}")

    if redirect_3xx:
        print("\n[3xx redirect 케이스] (처음 5개):")
        for sid, name, sc, loc in redirect_3xx[:5]:
            print(f"  sid={sid} | name={(name or '')[:40]!r} | {sc}→{loc}")

    if error_page:
        print("\n[200 + 에러페이지 케이스] (처음 5개):")
        for sid, name in error_page[:5]:
            print(f"  sid={sid} | name={(name or '')[:40]!r}")

    if not deleted:
        print(
            "\n[!] 100개 중 삭제 케이스 0건. NULL last_refreshed_at 우선 샘플링이지만 다 살아있음."
        )
        print(
            "    19,983개 중 NULL=15,813개라서 한 번도 안 돈 상품이 많은 게 진짜 문제일 수 있음."
        )


if __name__ == "__main__":
    asyncio.run(main())
