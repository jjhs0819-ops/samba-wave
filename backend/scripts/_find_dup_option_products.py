"""중복조합 에러를 일으키는 상품 식별 + 삭제 스크립트.

조건:
- source_site = 'MUSINSA'
- options 가 1개 (FREE / ONE COLOR / 단일 사이즈)
- addon_options 존재 (NULL/빈배열 아님)

마켓 등록 실패한 상태이므로 SambaCollectedProduct 만 삭제 (정책/검색필터 매핑은 cascade 또는 보존).
"""

import asyncio
import json
import sys

import asyncpg
from backend.core.config import settings


async def main(do_delete: bool = False) -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )

    # 조건: 무신사 + 옵션 1개 + addon_options 보유
    rows = await conn.fetch(
        """
        WITH base AS MATERIALIZED (
          SELECT id, site_product_id, name, brand,
                 options::jsonb AS opt_j,
                 addon_options::jsonb AS addon_j
          FROM samba_collected_product
          WHERE source_site IN ('MUSINSA', '무신사')
            AND options IS NOT NULL
            AND addon_options IS NOT NULL
        ), typed AS MATERIALIZED (
          SELECT * FROM base
          WHERE jsonb_typeof(opt_j) = 'array'
            AND jsonb_typeof(addon_j) = 'array'
        )
        SELECT id, site_product_id, name, brand,
               jsonb_array_length(opt_j) AS opt_cnt,
               jsonb_array_length(addon_j) AS addon_cnt,
               opt_j->0->>'size' AS opt0_size,
               opt_j->0->>'name' AS opt0_name
        FROM typed
        WHERE jsonb_array_length(opt_j) = 1
          AND jsonb_array_length(addon_j) >= 1
        ORDER BY brand, id
        """
    )

    print(f"[총계] 대상 상품 수: {len(rows)}")
    by_brand: dict[str, int] = {}
    for r in rows:
        by_brand[r["brand"] or "(없음)"] = by_brand.get(r["brand"] or "(없음)", 0) + 1
    print("[브랜드별]")
    for b, c in sorted(by_brand.items(), key=lambda x: -x[1])[:30]:
        print(f"  {b}: {c}")

    print("\n[샘플 10개]")
    for r in rows[:10]:
        print(
            f"  id={r['id']} site={r['site_product_id']} brand={r['brand']} "
            f"opt={r['opt0_size'] or r['opt0_name']} addon={r['addon_cnt']} | {r['name'][:40]}"
        )

    if not do_delete:
        print("\n(dry-run) 삭제하려면 인자에 'DELETE' 전달")
        await conn.close()
        return

    ids = [r["id"] for r in rows]
    print(f"\n[삭제 시작] {len(ids)}건")

    # 의존 테이블 삭제 순서 — FK 관계상 자식부터
    # samba_collected_product 삭제 시 cascade 안 걸려있을 가능성 → 자식 먼저 정리
    # 실제 FK 구조 모르므로 collected_product 만 delete, FK 에러 나면 보강
    deleted = await conn.execute(
        "DELETE FROM samba_collected_product WHERE id = ANY($1::text[])",
        ids,
    )
    print(f"[완료] {deleted}")
    await conn.close()


if __name__ == "__main__":
    do_delete = len(sys.argv) > 1 and sys.argv[1] == "DELETE"
    asyncio.run(main(do_delete=do_delete))
