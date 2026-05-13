"""'선택안함' 포함 옵션을 가진 상품 카운트.

문제: 무신사 수집기가 메인×엑스트라 2D 조합으로 options 를 만들면서
'XXX / 선택안함' 형태로 결합. 메인옵션이 1종이면 (FREE / 선택안함) 형태가
중복으로 들어가거나 스마트스토어가 거부.
"""

import asyncio
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

    # '선택안함' 포함 옵션이 1개라도 있는 무신사 상품
    rows = await conn.fetch(
        """
        SELECT p.id, p.site_product_id, p.brand, p.name, p.source_site
        FROM samba_collected_product p
        WHERE p.source_site IN ('MUSINSA','무신사')
          AND p.options IS NOT NULL
          AND jsonb_typeof(p.options::jsonb) = 'array'
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(p.options::jsonb) o
            WHERE o->>'name' LIKE '%선택안함%'
          )
        """
    )
    print(f"[총계] '선택안함' 옵션 포함 무신사 상품: {len(rows)}")

    by_brand: dict[str, int] = {}
    for r in rows:
        b = r["brand"] or "(없음)"
        by_brand[b] = by_brand.get(b, 0) + 1
    print("[브랜드별 상위 30]")
    for b, c in sorted(by_brand.items(), key=lambda x: -x[1])[:30]:
        print(f"  {b}: {c}")

    print("\n[샘플 5]")
    for r in rows[:5]:
        print(f"  id={r['id']} site={r['site_product_id']} brand={r['brand']} | {r['name'][:60]}")

    if not do_delete:
        print("\n(dry-run) 삭제하려면 인자 'DELETE' 전달")
        await conn.close()
        return

    ids = [r["id"] for r in rows]
    print(f"\n[삭제] {len(ids)}건 시작")

    # FK 관계 — 의존 테이블 우선 정리
    # 1) 마켓 등록 매핑 (있다면)
    # 2) 잡큐 (있다면)
    # 3) 마지막에 SambaCollectedProduct
    # 실제 FK 구조 모름 → 우선 collected_product 만 삭제 시도, FK 충돌 시 보고
    try:
        async with conn.transaction():
            res = await conn.execute(
                "DELETE FROM samba_collected_product WHERE id = ANY($1::text[])",
                ids,
            )
            print(f"[완료] {res}")
    except Exception as e:
        print(f"[삭제 실패] {e}")

    await conn.close()


if __name__ == "__main__":
    do_delete = len(sys.argv) > 1 and sys.argv[1] == "DELETE"
    asyncio.run(main(do_delete=do_delete))
