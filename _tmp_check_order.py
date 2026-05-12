"""이종영 주문 누락 원인 진단 — productOrderId/orderId/customer_name로 DB 조회."""

import asyncio
import asyncpg
import sys
sys.path.insert(0, '/app/backend')

from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=int(settings.write_db_port or 5432),
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    print("=" * 80)
    print("1) order_number = 2026051197491491 (productOrderId)")
    print("=" * 80)
    rows = await conn.fetch("""
        SELECT id, order_number, shipment_id, customer_name, channel_id,
               channel_name, paid_at, shipping_status, source, tenant_id, created_at
        FROM samba_order
        WHERE order_number = '2026051197491491'
        ORDER BY created_at DESC
    """)
    for r in rows:
        print(dict(r))
    print(f"-> {len(rows)} rows")

    print("\n" + "=" * 80)
    print("2) shipment_id = 2026051143770661 (orderId)")
    print("=" * 80)
    rows = await conn.fetch("""
        SELECT id, order_number, shipment_id, customer_name, channel_id,
               channel_name, paid_at, shipping_status, source, tenant_id, created_at
        FROM samba_order
        WHERE shipment_id = '2026051143770661'
        ORDER BY created_at DESC
    """)
    for r in rows:
        print(dict(r))
    print(f"-> {len(rows)} rows")

    print("\n" + "=" * 80)
    print("3) customer_name LIKE '%이종영%' (최근 10일)")
    print("=" * 80)
    rows = await conn.fetch("""
        SELECT id, order_number, customer_name, channel_id, channel_name,
               paid_at, shipping_status, source
        FROM samba_order
        WHERE customer_name LIKE '%이종영%'
          AND created_at >= NOW() - INTERVAL '10 days'
        ORDER BY created_at DESC
        LIMIT 20
    """)
    for r in rows:
        print(dict(r))
    print(f"-> {len(rows)} rows")

    print("\n" + "=" * 80)
    print("4) 가디(enclehhg@naver.com) 계정 정보")
    print("=" * 80)
    rows = await conn.fetch("""
        SELECT id, market_type, market_name, seller_id, is_active, tenant_id,
               (additional_fields->>'clientId') IS NOT NULL AS has_client_id,
               (additional_fields->>'clientSecret') IS NOT NULL AS has_client_secret,
               api_key IS NOT NULL AND api_key != '' AS has_api_key
        FROM samba_market_account
        WHERE market_type = 'smartstore' AND seller_id = 'enclehhg@naver.com'
    """)
    for r in rows:
        print(dict(r))

    print("\n" + "=" * 80)
    print("5) 가디 계정 최근 7일 스마트스토어 주문 (paid_at 시각 정밀)")
    print("=" * 80)
    if rows:
        gadi_id = rows[0]['id']
        orows = await conn.fetch("""
            SELECT order_number, customer_name, paid_at, shipping_status, created_at
            FROM samba_order
            WHERE channel_id = $1
              AND created_at >= NOW() - INTERVAL '7 days'
            ORDER BY paid_at DESC NULLS LAST
        """, gadi_id)
        for r in orows:
            print(dict(r))
        print(f"-> {len(orows)} rows")

    await conn.close()


asyncio.run(main())
