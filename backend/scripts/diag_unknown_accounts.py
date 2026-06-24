"""registered_accounts에 남아있는 삭제된 계정 ID 진단."""

import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main() -> None:
    import asyncpg

    from backend.core.config import settings

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    rows = await conn.fetch(
        """
        SELECT ra.account_id, COUNT(*) AS cnt
        FROM samba_collected_product cp,
             jsonb_array_elements_text(cp.registered_accounts::jsonb) AS ra(account_id)
        WHERE cp.registered_accounts IS NOT NULL
          AND cp.registered_accounts::text NOT IN ('[]', 'null', '')
          AND jsonb_typeof(cp.registered_accounts::jsonb) = 'array'
          AND NOT EXISTS (
              SELECT 1 FROM samba_market_account ma WHERE ma.id = ra.account_id
          )
        GROUP BY ra.account_id
        ORDER BY cnt DESC
        """
    )

    print(f"삭제된 계정 참조: {len(rows)}개")
    for r in rows:
        print(f"  {r['account_id']} → {r['cnt']}건 상품에 남아있음")

    total = sum(r["cnt"] for r in rows)
    print(f"\n영향 상품 합계(중복포함): {total}건")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
