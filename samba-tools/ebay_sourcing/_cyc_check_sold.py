import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
TARGET = "cp_01KYY9SA58GCE55WRVVG2Q1DA1"


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from sqlalchemy import text as t

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_read_session() as s:
            rows = (
                await s.execute(
                    t(
                        "SELECT order_number, status, sale_price, total_payment_amount, cost, profit, "
                        "paid_at, created_at FROM samba_order WHERE collected_product_id = :p "
                        "OR product_id = :p ORDER BY created_at DESC"
                    ),
                    {"p": TARGET},
                )
            ).fetchall()
        print(f"{len(rows)}건")
        for r in rows:
            print(" ", r)
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
