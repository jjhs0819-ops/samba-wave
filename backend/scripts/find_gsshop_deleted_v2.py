"""GS샵 삭제 상품 적극 탐색 v2 — 가장 오래된 상품 + 시즌 아우터 + 더 큰 샘플."""

import asyncio
import asyncpg
import httpx
from backend.core.config import settings


async def check_one(client: httpx.AsyncClient, sid: str, headers: dict) -> str:
    """단일 prdid 검사 → 'alive', 'redirect', 'errorpage', 'other'."""
    try:
        resp = await client.get(
            f"https://m.gsshop.com/prd/prd.gs?prdid={sid}", headers=headers
        )
        if 300 <= resp.status_code < 400:
            loc = resp.headers.get("Location", "")
            return (
                "redirect" if "prdid=" not in loc and "prd.gs" not in loc else "alive"
            )
        if resp.status_code == 200:
            body = resp.text
            if "DustView" in body or "에러 페이지" in body:
                return "errorpage"
            if "var renderJson" in body and '"prd":{' in body:
                return "alive"
            return "other"
        return "other"
    except Exception:
        return "other"


async def scan(label: str, rows, headers, sleep: float = 0.25):
    """N개 샘플 스캔 후 결과 요약."""
    alive = redirect = errorpage = other = 0
    deleted_samples: list[tuple] = []
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        for i, r in enumerate(rows, 1):
            sid = r["site_product_id"]
            res = await check_one(client, sid, headers)
            if res == "alive":
                alive += 1
            elif res == "redirect":
                redirect += 1
                if len(deleted_samples) < 5:
                    deleted_samples.append((sid, r.get("name", ""), "redirect"))
            elif res == "errorpage":
                errorpage += 1
                if len(deleted_samples) < 5:
                    deleted_samples.append((sid, r.get("name", ""), "errorpage"))
            else:
                other += 1
            if i % 50 == 0:
                print(
                    f"  [{label}] {i}/{len(rows)} 살아={alive} 삭제={redirect + errorpage} 기타={other}"
                )
            await asyncio.sleep(sleep)
    print(
        f"\n  [{label}] 최종: 살아={alive} redirect={redirect} errorpage={errorpage} other={other}"
    )
    if deleted_samples:
        print(f"  [{label}] 삭제 샘플:")
        for sid, nm, typ in deleted_samples:
            print(f"    {typ:10} sid={sid} | {(nm or '')[:50]!r}")
    return alive, redirect, errorpage, other, deleted_samples


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
        # 후보 1: 가장 오래 전에 수집된 상품 (created_at ASC) 300개
        oldest = await conn.fetch(
            """
            SELECT site_product_id, name, created_at
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            ORDER BY created_at ASC
            LIMIT 300
            """
        )
        # 후보 2: site_product_id가 가장 작은(가장 오래된 GS샵 ID) 300개
        smallest_id = await conn.fetch(
            """
            SELECT site_product_id, name
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
            ORDER BY site_product_id ASC
            LIMIT 300
            """
        )
        # 후보 3: 옷 시즌 (겨울 아우터, 패딩, 코트) - 지난 시즌 종료된 것 다수
        winter = await conn.fetch(
            """
            SELECT site_product_id, name
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
              AND (name ILIKE '%패딩%' OR name ILIKE '%코트%' OR name ILIKE '%다운%' OR name ILIKE '%부츠%')
            LIMIT 200
            """
        )
    finally:
        await conn.close()

    print(
        f"[샘플 크기] oldest={len(oldest)}, smallest_id={len(smallest_id)}, winter={len(winter)}"
    )
    print(
        f"  oldest 첫 row created_at: {oldest[0]['created_at']}, 마지막: {oldest[-1]['created_at']}"
    )
    print(
        f"  smallest_id 첫 sid: {smallest_id[0]['site_product_id']}, 마지막: {smallest_id[-1]['site_product_id']}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "text/html,application/xhtml+xml",
    }

    print("\n=== 1) oldest by created_at 300개 ===")
    await scan("oldest", oldest, headers)

    print("\n=== 2) smallest site_product_id 300개 ===")
    await scan("smallest_id", smallest_id, headers)

    print("\n=== 3) 시즌상품(패딩/코트/다운/부츠) 200개 ===")
    await scan("winter", winter, headers)


if __name__ == "__main__":
    asyncio.run(main())
