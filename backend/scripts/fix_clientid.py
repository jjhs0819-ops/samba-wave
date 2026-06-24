"""스마트스토어 계정 additional_fields에서 clientId 직접 제거."""
import asyncio
import asyncpg
from backend.core.config import settings

async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port, ssl=False,
        database=settings.write_db_name, user=settings.write_db_user,
        password=settings.write_db_password
    )
    rows = await conn.fetch(
        """SELECT id, account_label, additional_fields->>'clientId' as cid
           FROM samba_market_account
           WHERE market_type = 'smartstore'
             AND additional_fields->>'clientId' IS NOT NULL"""
    )
    print(f"대상 계정 {len(rows)}개:")
    for r in rows:
        print(f"  {r['account_label']}: clientId={r['cid']!r}")

    # json 타입이라 jsonb 캐스트 후 - 연산자, 결과 다시 json으로
    updated = await conn.execute(
        """UPDATE samba_market_account
           SET additional_fields = (additional_fields::jsonb - 'clientId')::json,
               updated_at = now()
           WHERE market_type = 'smartstore'
             AND additional_fields->>'clientId' IS NOT NULL"""
    )
    print(f"제거 완료: {updated}")
    await conn.close()

asyncio.run(main())
