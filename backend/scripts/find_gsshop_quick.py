"""GS샵 삭제 상품 빠른 탐색 — winter 키워드 200 + smallest_id 200 (총 400)."""

import asyncio
import asyncpg
import httpx
from backend.core.config import settings


async def check_one(client, sid, headers):
    try:
        resp = await client.get(
            f"https://m.gsshop.com/prd/prd.gs?prdid={sid}", headers=headers
        )
        if 300 <= resp.status_code < 400:
            loc = resp.headers.get("Location", "")
            if "prdid=" not in loc and "prd.gs" not in loc:
                return "redirect", loc[:80]
            return "alive", ""
        if resp.status_code == 200:
            body = resp.text
            if "DustView" in body or "에러 페이지" in body:
                return "errorpage", ""
            if "var renderJson" in body and '"prd":{' in body:
                return "alive", ""
            return "other", ""
        return "other", ""
    except Exception as e:
        return "other", str(e)[:40]


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2", port=5432,
        user=settings.read_db_user, password=settings.read_db_password,
        database=settings.read_db_name, ssl=False,
    )
    try:
        winter = await conn.fetch(
            "SELECT site_product_id, name FROM samba_collected_product "
            "WHERE source_site = 'GSShop' "
            "AND (name ILIKE '%패딩%' OR name ILIKE '%코트%' OR name ILIKE '%다운%' OR name ILIKE '%부츠%') "
            "LIMIT 200"
        )
        smallest = await conn.fetch(
            "SELECT site_product_id, name FROM samba_collected_product "
            "WHERE source_site = 'GSShop' "
            "ORDER BY site_product_id ASC LIMIT 200"
        )
    finally:
        await conn.close()

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    }
    print(f"[샘플] winter={len(winter)}, smallest_id={len(smallest)}")
    print(f"  winter 첫: {winter[0]['site_product_id'] if winter else 'N/A'}")
    print(f"  smallest 첫: {smallest[0]['site_product_id']}")

    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        for label, rows in [("winter", winter), ("smallest_id", smallest)]:
            alive = redirect = errorpage = other = 0
            deleted = []
            for i, r in enumerate(rows, 1):
                res, info = await check_one(client, r["site_product_id"], headers)
                if res == "alive":
                    alive += 1
                elif res == "redirect":
                    redirect += 1
                    if len(deleted) < 5:
                        deleted.append((r["site_product_id"], r["name"], "redirect", info))
                elif res == "errorpage":
                    errorpage += 1
                    if len(deleted) < 5:
                        deleted.append((r["site_product_id"], r["name"], "errorpage", ""))
                else:
                    other += 1
                await asyncio.sleep(0.15)
            print(f"\n[{label}] 살아={alive} redirect={redirect} errorpage={errorpage} other={other}")
            for sid, nm, typ, info in deleted:
                print(f"  {typ}: sid={sid} | {(nm or '')[:45]!r} | {info}")


if __name__ == "__main__":
    asyncio.run(main())
