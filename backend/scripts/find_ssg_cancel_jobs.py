"""SSG 주문 20260523-21034B 관련 cancel_order 잡 + notes 조회."""

import asyncio
import json

import asyncpg


async def main():
    from backend.core.config import settings

    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )
    try:
        # order 찾기 — 다양한 패턴
        ords = await conn.fetch(
            """
            SELECT id, order_number, sourcing_order_number, source_site,
                   sourcing_account_id, status, shipping_status, notes
            FROM samba_order
            WHERE sourcing_order_number = '2026052612122674'
            LIMIT 10
            """
        )
        for o in ords:
            print(f"order_id={o['id']}")
            print(f"  order_number={o['order_number']} sourcing_order={o['sourcing_order_number']} site={o['source_site']}")
            print(f"  status={o['status']} ship={o['shipping_status']} acct={o['sourcing_account_id']}")
            print(f"  notes:\n{(o['notes'] or '')[-800:]}\n")

            # 관련 cancel_order 잡
            jobs = await conn.fetch(
                """
                SELECT request_id, site, status, error, result, payload,
                       created_at, dispatched_at, completed_at
                FROM samba_sourcing_job
                WHERE job_type='cancel_order'
                  AND payload->>'orderId'=$1
                ORDER BY created_at DESC LIMIT 5
                """,
                o['id'],
            )
            for j in jobs:
                print(f"  JOB req={j['request_id']} site={j['site']} status={j['status']}")
                print(f"    created={j['created_at']} dispatched={j['dispatched_at']} completed={j['completed_at']}")
                print(f"    error={j['error']}")
                res = j['result']
                if isinstance(res, str): res = json.loads(res) if res else None
                if res:
                    print(f"    result={json.dumps(res, ensure_ascii=False, indent=4)}")
        if not ords:
            print("no order matched")
    finally:
        await conn.close()


asyncio.run(main())
