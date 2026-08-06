import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
TARGET = "cp_01KYBVB1V0G9YKV8AKQR87CHMM"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from sqlalchemy import text as t

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_read_session() as s:
            row = (
                await s.execute(
                    t(
                        "SELECT ai_image_transformed, images, updated_at FROM samba_collected_product WHERE id=:p"
                    ),
                    {"p": TARGET},
                )
            ).first()
            print("현재상태:", row)

            jobs = (
                await s.execute(
                    t(
                        """
                        SELECT job_type, status, payload, created_at, error
                        FROM samba_jobs
                        WHERE payload::text LIKE :p
                        ORDER BY created_at DESC LIMIT 20
                        """
                    ),
                    {"p": f"%{TARGET}%"},
                )
            ).fetchall()
            print(f"\n관련 job {len(jobs)}건")
            for j in jobs:
                print(" ", j)
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
