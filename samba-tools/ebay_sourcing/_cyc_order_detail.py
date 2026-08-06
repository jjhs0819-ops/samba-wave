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
            row = (
                await s.execute(
                    t(
                        """
                        SELECT order_number, status, payment_status, shipping_status,
                               product_name, quantity, sale_price, total_payment_amount,
                               cost, shipping_fee, revenue, profit, customer_name,
                               customer_address, tracking_number, source, sourcing_order_number,
                               notes, created_at, updated_at, paid_at
                        FROM samba_order WHERE collected_product_id = :p
                        """
                    ),
                    {"p": TARGET},
                )
            ).fetchall()
        for r in row:
            for k, v in zip(
                [
                    "order_number", "status", "payment_status", "shipping_status",
                    "product_name", "quantity", "sale_price", "total_payment_amount",
                    "cost", "shipping_fee", "revenue", "profit", "customer_name",
                    "customer_address", "tracking_number", "source", "sourcing_order_number",
                    "notes", "created_at", "updated_at", "paid_at",
                ],
                r,
            ):
                print(f"{k}: {v}")
            print("---")
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
