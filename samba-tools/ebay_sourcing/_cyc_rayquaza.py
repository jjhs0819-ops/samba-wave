import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from sqlalchemy import text as _sa_text

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_read_session() as s:
            rows = (
                await s.execute(
                    _sa_text(
                        "SELECT product_name, channel_name, status, paid_at, created_at "
                        "FROM samba_order WHERE product_name ILIKE '%rayquaza%' "
                        "OR product_name ILIKE '%레쿠자%' ORDER BY COALESCE(paid_at, created_at) DESC"
                    )
                )
            ).fetchall()
        print(f"레쿠자 주문 {len(rows)}건")
        for r in rows:
            print(" ", r)
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
