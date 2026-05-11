"""GSShop 갱신이 어디서 일어나는지 추적 — 최근 갱신 상품의 price_history 1건 덤프."""

import asyncio
import json
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    try:
        # 최근 갱신된 GSShop 상품 5개 → price_history 가장 최근 스냅샷 확인
        rows = await conn.fetch(
            """
            SELECT site_product_id, name, last_refreshed_at, price_history, sale_status, sale_price
            FROM samba_collected_product
            WHERE source_site = 'GSShop'
              AND last_refreshed_at >= NOW() - INTERVAL '15 minutes'
              AND price_history IS NOT NULL
            ORDER BY last_refreshed_at DESC
            LIMIT 5
            """
        )
        print(f"[1] 최근 15분 내 갱신된 GSShop 상품 {len(rows)}개:")
        for r in rows:
            history = r["price_history"]
            if isinstance(history, str):
                try:
                    history = json.loads(history)
                except Exception:
                    history = []
            latest_snap = history[0] if history else {}
            print(f"\n  sid={r['site_product_id']} name={(r['name'] or '')[:30]!r}")
            print(f"    last_refreshed_at: {r['last_refreshed_at']}")
            print(f"    sale_status: {r['sale_status']} sale_price: {r['sale_price']}")
            print(f"    최신 snapshot keys: {sorted(latest_snap.keys())[:15]}")
            print(
                f"    최신 snapshot: ts={latest_snap.get('ts')}, source={latest_snap.get('source', '?')}, "
                f"changed={latest_snap.get('changed', '?')}, cost={latest_snap.get('cost', '?')}, "
                f"sale_status={latest_snap.get('sale_status', '?')}"
            )

        # 어떤 잡 타입으로 처리됐는지
        print("\n[2] 최근 15분 GSShop 관련 잡 큐:")
        rows = await conn.fetch(
            """
            SELECT id, type, status, owner_device_id, created_at, updated_at, payload
            FROM samba_job
            WHERE source_site = 'GSShop'
              AND updated_at >= NOW() - INTERVAL '15 minutes'
            ORDER BY updated_at DESC
            LIMIT 10
            """
        )
        for r in rows:
            payload = r["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            payload_short = {
                k: payload.get(k)
                for k in ["mode", "productId", "product_id", "siteProductId"]
                if k in payload
            }
            print(
                f"  {r['updated_at']} type={r['type']} status={r['status']} owner={r['owner_device_id']} payload={payload_short}"
            )

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
