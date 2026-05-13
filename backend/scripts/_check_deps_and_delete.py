"""의존성 점검 + 삭제 실행.

대상 조건과 동일: 무신사 + options 내 '선택안함' 결합 포함.
1) registered_accounts 비어있지 않은 건 (등록된 건) 카운트만 — 삭제는 진행하지만 보고
2) FK 자식 테이블 식별: samba_collected_product 를 참조하는 테이블 자동 탐색
3) 자식부터 정리 후 본 테이블 삭제
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

    # 대상 id 수집
    target_rows = await conn.fetch(
        """
        SELECT p.id
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
    ids = [r["id"] for r in target_rows]
    print(f"[대상] {len(ids)}건")

    # 등록 여부
    reg_cnt = await conn.fetchval(
        """
        SELECT count(*) FROM samba_collected_product
        WHERE id = ANY($1::text[])
          AND registered_accounts IS NOT NULL
          AND jsonb_typeof(registered_accounts::jsonb) = 'array'
          AND jsonb_array_length(registered_accounts::jsonb) > 0
        """,
        ids,
    )
    print(f"[등록건] {reg_cnt}건이 마켓 등록 상태 (registered_accounts 비어있지 않음)")

    # FK 자식 테이블 식별
    fk_rows = await conn.fetch(
        """
        SELECT conrelid::regclass AS child_table,
               pg_get_constraintdef(c.oid) AS def
        FROM pg_constraint c
        WHERE c.contype = 'f'
          AND confrelid = 'samba_collected_product'::regclass
        """
    )
    print(f"\n[FK 자식 테이블 — samba_collected_product 참조] {len(fk_rows)}개")
    for r in fk_rows:
        print(f"  {r['child_table']}: {r['def']}")

    if not do_delete:
        print("\n(dry-run) 삭제하려면 'DELETE' 인자 전달")
        await conn.close()
        return

    # 삭제 (cascade 가 설정돼 있는지 위 def 확인 후 결정)
    # 일단 본 테이블만 시도 — FK 에러 나면 자식부터 처리
    print(f"\n[삭제 시도] {len(ids)}건")
    try:
        async with conn.transaction():
            res = await conn.execute(
                "DELETE FROM samba_collected_product WHERE id = ANY($1::text[])",
                ids,
            )
            print(f"[완료] {res}")
    except asyncpg.exceptions.ForeignKeyViolationError as e:
        print(f"[FK 충돌] {e}")
        print("자식 테이블 자동 정리 후 재시도가 필요합니다.")

    await conn.close()


if __name__ == "__main__":
    do_delete = len(sys.argv) > 1 and sys.argv[1] == "DELETE"
    asyncio.run(main(do_delete=do_delete))
