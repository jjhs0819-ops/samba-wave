"""LOTTEON 소싱 상품의 이미지 URL을 11번가 등록 관점에서 검증."""

import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        # 실패 잡에 등장한 상품 1건 — LOTTEON 나이키 챌린저 우븐 팬츠 (LE1215788633)
        print("\n[1] LOTTEON 나이키 'LE1215788633' 상품의 images:")
        row = await conn.fetchrow(
            """
            SELECT id, name, images
            FROM samba_collected_product
            WHERE source_site='LOTTEON'
              AND site_product_id LIKE 'LE1215788633%'
            LIMIT 1
            """
        )
        if row:
            print(f"  id={row['id']} name={row['name']}")
            imgs = row["images"]
            if isinstance(imgs, str):
                import json as _j

                imgs = _j.loads(imgs)
            print(
                f"  images type={type(imgs).__name__}, len={len(imgs) if imgs else 0}"
            )
            if imgs:
                for i, u in enumerate(imgs[:8]):
                    print(f"    [{i}] {u}")

        # LOTTEON 소싱 + 11번가 가디 대상 unregistered 상품 임의 5건 — 이미지 패턴 확인
        print("\n[2] LOTTEON 미등록 11번가가디 대상 상품 5건의 images:")
        rows = await conn.fetch(
            """
            SELECT id, name, site_product_id, images
            FROM samba_collected_product
            WHERE source_site='LOTTEON'
              AND BTRIM(brand) = '나이키'
            LIMIT 5
            """
        )
        for r in rows:
            imgs = r["images"]
            if isinstance(imgs, str):
                import json as _j

                try:
                    imgs = _j.loads(imgs)
                except Exception:
                    imgs = []
            cnt = len(imgs) if imgs else 0
            first = imgs[0] if imgs else None
            print(
                f"  {r['site_product_id']} {r['name'][:40]} | images={cnt} first={first}"
            )

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
