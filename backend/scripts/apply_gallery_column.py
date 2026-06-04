"""#342 gallery_include_sub 컬럼 prod 수동 적용 (마이그레이션 body와 동일).

entrypoint.sh 가 stamp→upgrade 구조라 신규 마이그레이션이 자동 적용 안 됨.
배포 전 이 스크립트로 DDL+backfill 직접 실행. idempotent(IF NOT EXISTS)라 재실행 안전.
"""

import asyncio

from sqlalchemy import text

from backend.db.orm import get_write_session


async def main() -> None:
    async with get_write_session() as session:
        before = (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='samba_detail_template' "
                    "AND column_name='gallery_include_sub'"
                )
            )
        ).first()
        print(f"적용 전 컬럼 존재: {bool(before)}")

        await session.execute(
            text(
                "ALTER TABLE samba_detail_template "
                "ADD COLUMN IF NOT EXISTS gallery_include_sub BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        result = await session.execute(
            text(
                "UPDATE samba_detail_template "
                "SET gallery_include_sub = COALESCE((img_checks->>'sub')::boolean, TRUE) "
                "WHERE img_checks IS NOT NULL"
            )
        )
        await session.commit()
        print(f"backfill UPDATE rowcount: {result.rowcount}")

        # 검증
        rows = (
            await session.execute(
                text(
                    "SELECT gallery_include_sub, count(*) AS n "
                    "FROM samba_detail_template GROUP BY 1 ORDER BY 1"
                )
            )
        ).all()
        print("적용 후 분포:")
        for r in rows:
            print(f"  gallery_include_sub={r.gallery_include_sub} → {r.n}건")


if __name__ == "__main__":
    asyncio.run(main())
