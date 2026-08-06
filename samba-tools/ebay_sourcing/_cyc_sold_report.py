"""KV(k-tcg_vault) eBay 포켓몬카드 판매내역 전체 조회 [컨테이너, 읽기전용]."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app/backend")

TENANT = "tn_01KRX6H1Q97JGPXRPB011985QT"
KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


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
                        """
                        SELECT product_name, quantity, sale_price, total_payment_amount,
                               cost, profit, status, paid_at, created_at
                        FROM samba_order
                        WHERE channel_id = :kv
                          AND (product_name ILIKE '%pokemon%' OR product_name ILIKE '%pokémon%')
                        ORDER BY COALESCE(paid_at, created_at) DESC
                        """
                    ),
                    {"kv": KV},
                )
            ).fetchall()
        print(f"총 {len(rows)}건\n")
        total_profit = 0.0
        total_revenue = 0.0
        cnt_cancel = 0
        for r in rows:
            name, qty, sp, total, cost, profit, status, paid, created = r
            total_profit += float(profit or 0)
            total_revenue += float(total or 0)
            if status and "cancel" in str(status).lower():
                cnt_cancel += 1
            when = (paid or created)
            print(f"{when} | {status:12s} | {name}")
        print(f"\n=== 합계: 매출${total_revenue:,.2f} 이익${total_profit:,.2f} 취소{cnt_cancel}건 ===")
    finally:
        current_tenant_id.reset(tok)


if __name__ == "__main__":
    asyncio.run(main())
