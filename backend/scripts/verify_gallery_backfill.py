"""#342 gallery_include_sub backfill 검증 (READ-ONLY, 프로덕션 DB).

마이그레이션의 backfill 표현식 `(img_checks->>'sub')::boolean` 이 실제 데이터에서
캐스트 에러 없이 동작하는지 확인. 아무것도 변경하지 않는다(SELECT only).
"""

import asyncio

from sqlalchemy import text

from backend.db.orm import get_write_session


async def main() -> None:
    async with get_write_session() as session:
        total = (
            await session.execute(text("SELECT count(*) FROM samba_detail_template"))
        ).scalar()
        print(f"samba_detail_template 총 {total}건")

        # 컬럼 이미 존재하는지(중복 마이그레이션 안전성)
        col_exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='samba_detail_template' "
                    "AND column_name='gallery_include_sub'"
                )
            )
        ).first()
        print(f"gallery_include_sub 컬럼 존재: {bool(col_exists)}")

        # backfill 표현식 dry-run — 캐스트 에러 여부 + 분포 확인
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                      COALESCE((img_checks->>'sub')::boolean, TRUE) AS computed,
                      count(*) AS n
                    FROM samba_detail_template
                    WHERE img_checks IS NOT NULL
                    GROUP BY 1
                    """
                )
            )
        ).all()
        print("backfill 분포 (computed gallery_include_sub → 건수):")
        for r in rows:
            print(f"  {r.computed} → {r.n}건")

        # sub 키 원시값 샘플 (캐스트 위험 점검)
        sample = (
            await session.execute(
                text(
                    "SELECT id, img_checks->>'sub' AS sub_text "
                    "FROM samba_detail_template WHERE img_checks IS NOT NULL LIMIT 10"
                )
            )
        ).all()
        print("sub 원시값 샘플:")
        for r in sample:
            print(f"  {r.id}: sub_text={r.sub_text!r}")

        await session.rollback()  # 변경 없음 보장


if __name__ == "__main__":
    asyncio.run(main())
