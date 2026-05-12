"""idle in transaction 세션 정리 — alembic_version lock 해소용.

기존 backend.db.orm의 write engine을 재사용해서 별도 인증정보 노출 없이 실행.
"""

import asyncio
from sqlalchemy import text
from backend.db.orm import get_write_engine


async def main():
    write_engine = get_write_engine()
    async with write_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT pid, application_name, query_start "
                    "FROM pg_stat_activity "
                    "WHERE state='idle in transaction' AND pid<>pg_backend_pid()"
                )
            )
        ).all()
        print(f"idle in transaction: {len(rows)}")
        terminated = 0
        for r in rows:
            try:
                ok = (
                    await conn.execute(
                        text("SELECT pg_terminate_backend(:p)"), {"p": r.pid}
                    )
                ).scalar()
                if ok:
                    terminated += 1
                    print(f"  TERMINATED pid={r.pid} app={r.application_name}")
            except Exception as e:
                print(f"  FAIL pid={r.pid}: {e}")
        print(f"terminated: {terminated}/{len(rows)}")
        remaining = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM pg_stat_activity "
                    "WHERE state='idle in transaction' AND pid<>pg_backend_pid()"
                )
            )
        ).scalar()
        print(f"remaining: {remaining}")


asyncio.run(main())
