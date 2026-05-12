"""마스마룰즈 에어팟 파우치(5006270760) 롯데ON pdItmsInfo 누락 진단.

검증 흐름:
1) DB에서 상품 조회 (category1~4, brand, material, origin, manufacturer 등)
2) detect_notice_group + build_lotteon_notice 직접 호출해 무엇이 나오는지
3) plugins/markets/lotteon.py 의 execute()가 실제 어떤 payload를 만드는지 추적
"""

import asyncio
import json
import logging
logging.basicConfig(level=logging.INFO)

from backend.db.orm import get_write_sessionmaker

SITE_PRODUCT_ID = "5006270760"
MUSINSA_ID = "3457620"


async def main():
    Session = get_write_sessionmaker()
    async with Session() as session:
        from sqlalchemy import text
        row = (await session.execute(text(
            """
            SELECT id, name, source_site, site_product_id,
                   category1, category2, category3, category4,
                   brand, material, origin, manufacturer,
                   care_instructions, quality_guarantee,
                   extra_data
              FROM samba_collected_product
             WHERE site_product_id = :a
                OR site_product_id = :b
                OR name LIKE '%Daily airpuds pouch%'
             ORDER BY updated_at DESC NULLS LAST
             LIMIT 1
            """
        ), {"a": SITE_PRODUCT_ID, "b": MUSINSA_ID})).mappings().first()
    if not row:
        print("NOT FOUND"); return
    r = dict(row)
    print("=== DB row ===")
    for k in ("id","name","source_site","site_product_id","category1","category2","category3","category4","brand","material","origin","manufacturer","care_instructions","quality_guarantee"):
        print(f"  {k}: {r.get(k)!r}")
    extra = r.get("extra_data")
    if isinstance(extra, str):
        try: extra = json.loads(extra)
        except Exception: extra = {}
    if isinstance(extra, dict):
        print("  extra_data keys:", list(extra.keys())[:30])

    # build_lotteon_notice 직접 호출
    from backend.domain.samba.proxy.notice_utils import (
        detect_notice_group, build_lotteon_notice
    )
    product = dict(r)
    if isinstance(extra, dict):
        product.update(extra)  # lotteon.py 실제 흐름과 유사하게 extra 머지
    group = detect_notice_group(product)
    print(f"\n=== detect_notice_group → {group!r} ===")
    notice = build_lotteon_notice(product)
    print(f"\n=== build_lotteon_notice 결과 ===")
    print(json.dumps(notice, ensure_ascii=False, indent=2)[:2000])

asyncio.run(main())
