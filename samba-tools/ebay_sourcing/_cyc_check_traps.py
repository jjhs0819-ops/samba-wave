import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
TARGETS = ["cp_01KYXWJTYVJ4S6JSY2VV2C6746", "cp_01KYY8VS1WP0Y42EQVE154D289"]


async def main():
    import backend.main  # noqa: F401
    from backend.core.tenant_context import current_tenant_id
    from backend.db.orm import get_read_session
    from sqlalchemy import text as t

    tok = current_tenant_id.set(TENANT)
    try:
        async with get_read_session() as s:
            for pid in TARGETS:
                rows = (
                    await s.execute(
                        t(
                            "SELECT order_number, status, payment_status, sale_price, cost, paid_at "
                            "FROM samba_order WHERE collected_product_id = :p"
                        ),
                        {"p": pid},
                    )
                ).fetchall()
                pinfo = (
                    await s.execute(
                        t("SELECT name, cost, sale_price, source_url FROM samba_collected_product WHERE id=:p"),
                        {"p": pid},
                    )
                ).first()
                print(f"[{pid}] {pinfo}")
                print(f"  주문 {len(rows)}건")
                for r in rows:
                    print("   ", r)
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
