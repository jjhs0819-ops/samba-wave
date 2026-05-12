"""이종영 주문의 매칭 실패 원인 진단 — channel_id, product_id 키로 collected_product 매칭."""

import asyncio
import sys
sys.path.insert(0, "/app/backend")

from sqlalchemy import text
from backend.db.orm import get_read_session


TARGET = "2026051197491491"


async def main():
    async with get_read_session() as session:
        # 1) 이종영 주문 row
        r = await session.execute(text("""
            SELECT id, channel_id, product_id, product_name, source_site,
                   source_url, collected_product_id, customer_name
            FROM samba_order WHERE order_number = :on
        """), {"on": TARGET})
        rec = r.fetchone()
        if not rec:
            print("주문 없음")
            return
        d = dict(rec._mapping)
        print("이종영 주문 row:")
        for k, v in d.items():
            print(f"  {k}: {v}")

        ch_id = d["channel_id"]
        pid = d["product_id"]

        # 2) (channel_id, product_id) 정확 매칭 시도
        print(f"\n=== samba_collected_product에서 channel_id={ch_id}, product_id={pid} 매칭 ===")
        r = await session.execute(text("""
            SELECT id, name, source_site, source_url,
                   market_product_nos, registered_accounts
            FROM samba_collected_product
            WHERE registered_accounts @> jsonb_build_array(CAST(:cid AS text))
              AND (market_product_nos->>'product_id' = CAST(:pid AS text)
                   OR market_product_nos::text LIKE CAST(:like_pid AS text))
            LIMIT 5
        """), {"cid": ch_id, "pid": pid, "like_pid": f"%{pid}%"})
        for row in r.fetchall():
            print(dict(row._mapping))

        # 3) product_id 글로벌 매칭
        print(f"\n=== product_id={pid} 글로벌 매칭 ===")
        r = await session.execute(text("""
            SELECT id, name, source_site, source_url
            FROM samba_collected_product
            WHERE market_product_nos::text LIKE :like_pid
            LIMIT 10
        """), {"like_pid": f"%{pid}%"})
        for row in r.fetchall():
            print(dict(row._mapping))

        # 4) 다른 가디 주문 — 매칭 잘 된 예시
        print(f"\n=== 가디 channel_id={ch_id} 매칭된 주문 sample ===")
        r = await session.execute(text("""
            SELECT order_number, product_id, source_site, source_url, collected_product_id
            FROM samba_order
            WHERE channel_id = :cid AND source_site IS NOT NULL
            ORDER BY created_at DESC LIMIT 3
        """), {"cid": ch_id})
        for row in r.fetchall():
            print(dict(row._mapping))


asyncio.run(main())
