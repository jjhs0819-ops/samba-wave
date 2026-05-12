"""셀렙샵에디션 상품(site_product_id=2030274229) 이미지 용량 진단.

목적: 롯데홈쇼핑 [1038] 대표/부가이미지 용량 초과 원인 파악.
- images / detail_images 각 URL에 HEAD 요청 → Content-Length
- detail_html 내부 <img src=...> 추출 + HEAD 크기 점검
- 900KB 초과 항목 표시
"""

import asyncio
import re

import asyncpg
import httpx

from backend.core.config import settings


SITE_PRODUCT_ID = "LE1219202563"
MUSINSA_ID = "404566-02"
LIMIT_BYTES = 900_000


async def head_size(client: httpx.AsyncClient, url: str) -> tuple[int | None, int]:
    try:
        r = await client.head(url, follow_redirects=True, timeout=10.0)
        cl = r.headers.get("content-length")
        return (int(cl) if cl and cl.isdigit() else None, r.status_code)
    except Exception as e:
        return (None, -1)


async def real_size(client: httpx.AsyncClient, url: str) -> int:
    try:
        r = await client.get(url, follow_redirects=True, timeout=20.0)
        return len(r.content)
    except Exception:
        return -1


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        row = await conn.fetchrow(
            """
            SELECT id, name, source_site, site_product_id,
                   images, detail_images, detail_html
              FROM samba_collected_product
             WHERE site_product_id = $1
                OR site_product_id = $2
                OR name LIKE '%푸마 404566%'
             ORDER BY updated_at DESC NULLS LAST
             LIMIT 1
            """,
            SITE_PRODUCT_ID, MUSINSA_ID,
        )
    finally:
        await conn.close()

    if not row:
        print(f"NOT FOUND: site_product_id={SITE_PRODUCT_ID}")
        return

    print(f"DB id={row['id']} site={row['source_site']} name={row['name']}")
    images = row["images"] or []
    detail_images = row["detail_images"] or []
    detail_html = row["detail_html"] or ""

    # JSONB -> list 강제
    import json
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except Exception:
            images = []
    if isinstance(detail_images, str):
        try:
            detail_images = json.loads(detail_images)
        except Exception:
            detail_images = []

    print(f"images count={len(images)}")
    print(f"detail_images count={len(detail_images)}")
    print(f"detail_html len={len(detail_html)}")

    # detail_html 내부 src/data-src/srcset/style url 추출
    html_urls: list[str] = []
    for pat in [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<img[^>]+data-src=["\']([^"\']+)["\']',
        r'<img[^>]+data-original=["\']([^"\']+)["\']',
        r'srcset=["\']([^"\']+)["\']',
        r'background-image:\s*url\(["\']?([^)"\']+)',
    ]:
        for m in re.finditer(pat, detail_html, flags=re.IGNORECASE):
            v = m.group(1).strip()
            if v.startswith("http"):
                # srcset이면 첫 URL만
                v = v.split(",")[0].split()[0]
                html_urls.append(v)
    html_urls = list(dict.fromkeys(html_urls))
    print(f"detail_html image-like URLs (dedup) = {len(html_urls)}")

    targets: list[tuple[str, str]] = []
    for i, u in enumerate(images):
        targets.append((f"images[{i}]", u))
    for i, u in enumerate(detail_images):
        targets.append((f"detail_images[{i}]", u))
    for i, u in enumerate(html_urls):
        targets.append((f"html[{i}]", u))

    print(f"\n총 {len(targets)}개 URL 검사 시작 (>{LIMIT_BYTES//1000}KB 표시)\n")

    over_count = 0
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for tag, url in targets:
            cl, status = await head_size(client, url)
            mark = ""
            if cl is not None and cl > LIMIT_BYTES:
                mark = " ⚠️ OVER"
                over_count += 1
            elif cl is None:
                # CL 없으면 실제 다운로드
                rb = await real_size(client, url)
                if rb > LIMIT_BYTES:
                    mark = f" ⚠️ OVER(real={rb})"
                    over_count += 1
                else:
                    mark = f" (real={rb})"
            print(f"{tag:20s} CL={cl} status={status}{mark}")
            print(f"  {url}")

    print(f"\n=== 결과: 900KB 초과 = {over_count} / {len(targets)} ===")


if __name__ == "__main__":
    asyncio.run(main())
