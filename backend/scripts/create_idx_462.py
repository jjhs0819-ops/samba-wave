"""#462 scalar 부분식 인덱스 수동 사전생성 (CONCURRENTLY, 트랜잭션 밖).

entrypoint stamp-to-head 가 마이그레이션을 스킵하므로 프로덕션에 직접 생성.
asyncpg 직접 연결 — CONCURRENTLY 는 트랜잭션/풀 밖 단일 커넥션에서 실행.
"""

import asyncio

import asyncpg

from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        for name, expr in (
            ("ix_samba_jobs_autotune_pending_pid", "(payload->'product_ids'->>0)"),
            (
                "ix_samba_jobs_autotune_pending_acc",
                "(payload->'target_account_ids'->>0)",
            ),
        ):
            sql = (
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON samba_jobs ({expr}) "
                "WHERE status = 'pending' AND job_type = 'autotune_transmit'"
            )
            print(f"생성 중: {name} ...")
            await conn.execute(sql)
            print(f"  완료: {name}")

        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename='samba_jobs' "
            "AND indexname IN ('ix_samba_jobs_autotune_pending_pid','ix_samba_jobs_autotune_pending_acc') "
            "ORDER BY indexname"
        )
        print("존재 확인:", [r["indexname"] for r in rows])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
