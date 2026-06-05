"""issue #356 backfill — 태그(__ai_image__)는 있는데 ai_image_transformed 컬럼이
FALSE로 잔존하는 구상품의 출하자격을 복구한다.

배경: ai_image_transformed BOOLEAN 컬럼 도입 이전에 변환된 상품, 또는 태그
통째 SET race로 컬럼만 누락된 상품이 출하 차단(컬럼 FALSE) 상태로 남음.
태그가 살아있으면 실제로는 변환 완료된 것이므로 컬럼을 TRUE로 맞춘다.

프로덕션 DB 직접 실행용 — VM 컨테이너에서 .venv/python 으로 실행.
"""

import asyncio

from sqlalchemy import text

from backend.db.orm import get_write_sessionmaker


async def main() -> None:
    Session = get_write_sessionmaker()
    async with Session() as session:
        # 1) 적용 전 대상 건수 확인
        before = await session.execute(
            text(
                """
                SELECT count(*) FROM samba_collected_product
                WHERE tags @> '["__ai_image__"]'::jsonb
                  AND ai_image_transformed = FALSE
                """
            )
        )
        target = before.scalar_one()
        print(f"[backfill] 복구 대상(태그 O / 컬럼 FALSE): {target:,}건")

        if target == 0:
            print("[backfill] 대상 없음 — 종료")
            return

        # 2) 컬럼 TRUE 로 복구
        result = await session.execute(
            text(
                """
                UPDATE samba_collected_product
                SET ai_image_transformed = TRUE
                WHERE tags @> '["__ai_image__"]'::jsonb
                  AND ai_image_transformed = FALSE
                """
            )
        )
        await session.commit()
        print(f"[backfill] UPDATE 완료: {result.rowcount:,}건")

        # 3) 검증 — 잔여 0 확인
        after = await session.execute(
            text(
                """
                SELECT count(*) FROM samba_collected_product
                WHERE tags @> '["__ai_image__"]'::jsonb
                  AND ai_image_transformed = FALSE
                """
            )
        )
        remain = after.scalar_one()
        print(f"[backfill] 잔여(여전히 FALSE): {remain:,}건")


if __name__ == "__main__":
    asyncio.run(main())
